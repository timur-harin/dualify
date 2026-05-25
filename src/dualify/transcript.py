"""Record-and-replay support for LLM calls.

Dualify runs depend on a live LLM endpoint. That makes artifact
evaluation, CI, and bug-bisection painful: reviewers must reproduce a
local Ollama install, supply API keys, or accept that runs are
non-deterministic across model versions.

This module adds two thin wrappers around the ``LLMClient`` protocol:

* ``RecordingLLMClient`` forwards every call to a backing client and
  appends ``(prompt, prompt_sha256, temperature, response)`` to a
  JSONL transcript. The first line of the file is a metadata header
  recording model / base_url / timestamp.
* ``ReplayLLMClient`` loads a transcript and serves responses in the
  order they were recorded. Every call verifies the prompt's SHA-256
  against the recorded hash, so a silent prompt-template change does
  not produce a silent verdict change. On mismatch or exhaustion the
  client raises a clear, named exception.

The transcript format is intentionally line-oriented so it streams,
diffs cleanly, and survives partial writes.
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
        # want to append should rename the file first.
        self._handle = self.transcript_path.open("w", encoding="utf-8")
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
            expected_hash = record.get("prompt_sha256")
            actual_hash = _sha256_hex(prompt)
            if expected_hash != actual_hash:
                raise TranscriptPromptMismatchError(
                    f"transcript {self.transcript_path}: call #{record.get('call_index', '?')} "
                    f"prompt hash mismatch (expected={expected_hash}, actual={actual_hash}). "
                    "A prompt template likely changed since the transcript was recorded; "
                    "re-record with --record-transcript."
                )
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
