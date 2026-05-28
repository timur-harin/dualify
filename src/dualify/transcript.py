"""Record-and-replay support for LLM calls.

Dualify runs depend on a live LLM endpoint. That makes artifact
evaluation, CI, and bug-bisection painful: reviewers must reproduce a
local Ollama install, supply API keys, or accept that runs are
non-deterministic across model versions.

This module adds three thin wrappers around the ``LLMClient`` protocol:

* ``RecordingLLMClient`` forwards every call to a backing client and
  appends ``(prompt, prompt_sha256, temperature, response)`` to a
  JSONL transcript. The first line of the file is a metadata header
  recording model / base_url / timestamp.
* ``ReplayLLMClient`` loads a transcript and serves responses in the
  order they were recorded. Every call verifies the prompt's SHA-256
  against the recorded hash, so a silent prompt-template change does
  not produce a silent verdict change. On mismatch or exhaustion the
  client raises a clear, named exception.
* ``ResumingLLMClient`` serves cached responses from an existing
  transcript prefix and falls through to a live client (and appends to
  the same file) for calls past the prefix. The hash check still runs
  for cached calls, so divergence is caught at the exact boundary
  where it happens. This is the right mode after an interrupted run.

The transcript format is intentionally line-oriented so it streams,
diffs cleanly, and survives partial writes. All file handles are
opened with ``buffering=1`` (line buffering) so each record reaches
the OS as soon as its trailing newline is written -- a ``tail -f``
on the transcript shows progress in real time.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from dualify.ollama_client import LLMClient

TRANSCRIPT_FORMAT_VERSION = 1


class TranscriptError(RuntimeError):
    """Base class for replay-related errors."""


class TranscriptExhaustedError(TranscriptError):
    """Raised when more LLM calls happen than the transcript recorded."""


class TranscriptPromptMismatchError(TranscriptError):
    """Raised when the live prompt does not match the recorded prompt hash.

    Catching this in tests / CI is how a prompt-template drift is surfaced
    without producing a silent verdict difference.
    """


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_header(model: str, base_url: str, provider: str) -> dict[str, Any]:
    return {
        "transcript_metadata": {
            "version": TRANSCRIPT_FORMAT_VERSION,
            "recorded_at_utc": datetime.now(UTC).isoformat(),
            "model": model,
            "base_url": base_url,
            "provider": provider,
        }
    }


@dataclass
class RecordingLLMClient:
    """Wraps a real client and appends every call to ``transcript_path``."""

    inner: LLMClient
    transcript_path: Path
    model: str
    base_url: str
    provider: str
    _call_index: int = 0
    _handle: IO[str] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        # ``w`` truncates so a re-run produces a clean transcript; users who
        # want to append should use ``ResumingLLMClient`` (or rename first).
        # ``buffering=1`` -> line buffered, so each JSONL record is visible to
        # ``tail -f`` and to a subsequent resume the moment it is written.
        self._handle = self.transcript_path.open("w", encoding="utf-8", buffering=1)
        header = _build_header(self.model, self.base_url, self.provider)
        self._handle.write(json.dumps(header, ensure_ascii=False) + "\n")
        self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        with contextlib.suppress(Exception):
            self.close()

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        response = self.inner.generate_json(prompt, temperature=temperature)
        record = {
            "call_index": self._call_index,
            "prompt_sha256": _sha256_hex(prompt),
            "temperature": temperature,
            "prompt": prompt,
            "response": response,
        }
        assert self._handle is not None, "transcript handle closed"
        self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._handle.flush()
        self._call_index += 1
        return response

    def healthcheck(self) -> None:
        self.inner.healthcheck()


@dataclass
class ReplayLLMClient:
    """Serves LLM responses from a recorded transcript -- no network calls."""

    transcript_path: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    records: list[dict[str, Any]] = field(default_factory=list)
    _cursor: int = 0
    strict_prompts: bool = True

    @classmethod
    def from_path(cls, path: Path, *, strict_prompts: bool = True) -> ReplayLLMClient:
        metadata, records = _load_transcript(path)
        return cls(
            transcript_path=path,
            metadata=metadata,
            records=records,
            strict_prompts=strict_prompts,
        )

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        if self._cursor >= len(self.records):
            raise TranscriptExhaustedError(
                f"transcript {self.transcript_path} has {len(self.records)} call(s); "
                f"caller attempted call #{self._cursor + 1}. "
                "Re-record with --record-transcript or shorten the input set."
            )
        record = self.records[self._cursor]
        self._cursor += 1
        if self.strict_prompts:
            _verify_prompt_hash(record, prompt, self.transcript_path)
        response = record.get("response", {})
        if not isinstance(response, dict):
            raise TranscriptError(
                f"transcript {self.transcript_path}: call #{record.get('call_index', '?')} "
                "response is not a JSON object."
            )
        return response

    def healthcheck(self) -> None:
        # No remote endpoint; the transcript is the truth.
        return None

    def remaining_calls(self) -> int:
        return max(0, len(self.records) - self._cursor)


def _load_transcript(
    path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read a transcript file into (metadata, records).

    Used by both ``ReplayLLMClient.from_path`` and ``ResumingLLMClient`` so
    they share the same parsing rules.
    """
    metadata: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise TranscriptError(
                    f"transcript {path}: line {line_no} is not valid JSON ({exc})"
                ) from exc
            if "transcript_metadata" in payload:
                metadata = payload["transcript_metadata"]
                continue
            records.append(payload)
    return metadata, records


def _verify_prompt_hash(
    record: dict[str, Any],
    prompt: str,
    transcript_path: Path,
) -> None:
    expected_hash = record.get("prompt_sha256")
    actual_hash = _sha256_hex(prompt)
    if expected_hash != actual_hash:
        raise TranscriptPromptMismatchError(
            f"transcript {transcript_path}: call #{record.get('call_index', '?')} "
            f"prompt hash mismatch (expected={expected_hash}, actual={actual_hash}). "
            "A prompt template likely changed since the transcript was recorded; "
            "re-record with --record-transcript or shorten the input set."
        )


@dataclass
class ResumingLLMClient:
    """Serve a recorded transcript prefix, then fall through to a live client.

    The intended use case is "I interrupted a run; continue from where it
    stopped without re-issuing the LLM calls that already succeeded."

    Behavior:

    * Reads the existing transcript at ``transcript_path`` (header + N
      records). Opens the same file in append mode.
    * For the first N calls, verifies the prompt hash against the cached
      record and returns the cached response. A mismatch raises
      ``TranscriptPromptMismatchError`` at the exact boundary, so a
      changed prompt template surfaces immediately rather than silently
      poisoning the suffix.
    * For calls N+1, N+2, ... forwards to ``inner`` and appends a new
      record with the next ``call_index`` to the same file.

    The header is left untouched -- the original model / provider /
    base_url metadata stays as the canonical record. (We don't try to
    reconcile if the resumed run uses a different live model; that
    would be a different transcript.)
    """

    inner: LLMClient
    transcript_path: Path
    strict_prompts: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    cached_records: list[dict[str, Any]] = field(default_factory=list)
    _cursor: int = 0
    _next_call_index: int = 0
    _handle: IO[str] | None = field(default=None, init=False, repr=False)

    @classmethod
    def from_path(
        cls,
        inner: LLMClient,
        path: Path,
        *,
        strict_prompts: bool = True,
    ) -> ResumingLLMClient:
        metadata, records = _load_transcript(path)
        next_index = 0
        for record in records:
            idx = record.get("call_index")
            if isinstance(idx, int) and idx >= next_index:
                next_index = idx + 1
        # If call_index was missing for some reason, fall back to count.
        next_index = max(next_index, len(records))
        return cls(
            inner=inner,
            transcript_path=path,
            strict_prompts=strict_prompts,
            metadata=metadata,
            cached_records=records,
            _next_call_index=next_index,
        )

    def __post_init__(self) -> None:
        # Open in append mode so the existing prefix is preserved. Line
        # buffered for the same reason RecordingLLMClient is.
        self._handle = self.transcript_path.open("a", encoding="utf-8", buffering=1)

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        with contextlib.suppress(Exception):
            self.close()

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        if self._cursor < len(self.cached_records):
            record = self.cached_records[self._cursor]
            self._cursor += 1
            if self.strict_prompts:
                _verify_prompt_hash(record, prompt, self.transcript_path)
            response = record.get("response", {})
            if not isinstance(response, dict):
                raise TranscriptError(
                    f"transcript {self.transcript_path}: call "
                    f"#{record.get('call_index', '?')} response is not a JSON object."
                )
            return response

        response = self.inner.generate_json(prompt, temperature=temperature)
        new_record = {
            "call_index": self._next_call_index,
            "prompt_sha256": _sha256_hex(prompt),
            "temperature": temperature,
            "prompt": prompt,
            "response": response,
        }
        assert self._handle is not None, "transcript handle closed"
        self._handle.write(json.dumps(new_record, ensure_ascii=False) + "\n")
        self._handle.flush()
        self._next_call_index += 1
        self._cursor += 1
        return response

    def healthcheck(self) -> None:
        # Only ping the live endpoint if we may actually need it (i.e. the
        # cached prefix doesn't cover all calls this run will make). We
        # can't know that ahead of time, so do the check eagerly -- the
        # caller can swap a no-op client in if they want to suppress it.
        self.inner.healthcheck()

    def cached_remaining(self) -> int:
        return max(0, len(self.cached_records) - self._cursor)

    def appended_count(self) -> int:
        return max(0, self._cursor - len(self.cached_records))
