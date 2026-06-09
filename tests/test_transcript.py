"""Tests for the record/replay transcript module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dualify.transcript import (
    RecordingLLMClient,
    ReplayLLMClient,
    ResumingLLMClient,
    TranscriptExhaustedError,
    TranscriptPromptMismatchError,
)


class FakeLLMClient:
    """Deterministic stand-in for a real LLM client."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, float]] = []

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        self.calls.append((prompt, temperature))
        if not self._responses:
            raise AssertionError("fake LLM exhausted; test wrote more calls than responses")
        return self._responses.pop(0)

    def healthcheck(self) -> None:
        return None


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_recording_writes_metadata_header_and_per_call_records(tmp_path: Path) -> None:
    transcript = tmp_path / "run.jsonl"
    fake = FakeLLMClient([{"answer": 1}, {"answer": 2}])
    recorder = RecordingLLMClient(
        inner=fake,
        transcript_path=transcript,
        model="test-model",
        base_url="http://example",
        provider="ollama",
    )
    assert recorder.generate_json("first prompt") == {"answer": 1}
    assert recorder.generate_json("second prompt", temperature=0.7) == {"answer": 2}
    recorder.close()

    lines = _read_jsonl(transcript)
    assert len(lines) == 3
    metadata = lines[0]["transcript_metadata"]
    assert metadata["model"] == "test-model"
    assert metadata["base_url"] == "http://example"
    assert metadata["provider"] == "ollama"
    assert metadata["version"] == 1
    assert "recorded_at_utc" in metadata

    assert lines[1]["call_index"] == 0
    assert lines[1]["prompt"] == "first prompt"
    assert lines[1]["response"] == {"answer": 1}
    assert lines[1]["temperature"] == 0.0
    assert lines[2]["call_index"] == 1
    assert lines[2]["temperature"] == 0.7


def test_round_trip_record_then_replay(tmp_path: Path) -> None:
    transcript = tmp_path / "rt.jsonl"
    responses = [{"a": i} for i in range(5)]
    fake = FakeLLMClient(list(responses))
    recorder = RecordingLLMClient(
        inner=fake,
        transcript_path=transcript,
        model="m",
        base_url="b",
        provider="p",
    )
    prompts = [f"prompt {i}" for i in range(5)]
    recorded = [recorder.generate_json(p) for p in prompts]
    recorder.close()
    assert recorded == responses

    player = ReplayLLMClient.from_path(transcript)
    replayed = [player.generate_json(p) for p in prompts]
    assert replayed == responses
    assert player.remaining_calls() == 0


def test_replay_detects_prompt_hash_drift(tmp_path: Path) -> None:
    transcript = tmp_path / "drift.jsonl"
    fake = FakeLLMClient([{"x": 1}])
    recorder = RecordingLLMClient(
        inner=fake,
        transcript_path=transcript,
        model="m",
        base_url="b",
        provider="p",
    )
    recorder.generate_json("original prompt")
    recorder.close()

    player = ReplayLLMClient.from_path(transcript)
    with pytest.raises(TranscriptPromptMismatchError) as exc_info:
        player.generate_json("mutated prompt")
    msg = str(exc_info.value)
    assert "prompt hash mismatch" in msg
    assert "--record-transcript" in msg


def test_replay_raises_when_transcript_exhausted(tmp_path: Path) -> None:
    transcript = tmp_path / "short.jsonl"
    fake = FakeLLMClient([{"x": 1}])
    recorder = RecordingLLMClient(
        inner=fake,
        transcript_path=transcript,
        model="m",
        base_url="b",
        provider="p",
    )
    recorder.generate_json("only prompt")
    recorder.close()

    player = ReplayLLMClient.from_path(transcript)
    player.generate_json("only prompt")
    with pytest.raises(TranscriptExhaustedError) as exc_info:
        player.generate_json("would be call 2")
    assert "transcript" in str(exc_info.value)


def test_replay_non_strict_mode_skips_hash_check(tmp_path: Path) -> None:
    transcript = tmp_path / "loose.jsonl"
    fake = FakeLLMClient([{"x": 1}])
    recorder = RecordingLLMClient(
        inner=fake,
        transcript_path=transcript,
        model="m",
        base_url="b",
        provider="p",
    )
    recorder.generate_json("original")
    recorder.close()

    player = ReplayLLMClient.from_path(transcript, strict_prompts=False)
    # Different prompt is accepted in non-strict mode; useful for analysis
    # where the caller is intentionally re-issuing the same call shape but
    # has tweaked whitespace or formatting.
    assert player.generate_json("DIFFERENT") == {"x": 1}


def test_replay_healthcheck_is_noop(tmp_path: Path) -> None:
    transcript = tmp_path / "empty.jsonl"
    transcript.write_text(json.dumps({"transcript_metadata": {"version": 1}}) + "\n")
    player = ReplayLLMClient.from_path(transcript)
    # Should not raise, regardless of network state.
    player.healthcheck()


class _StubLLM:
    """Returns the same well-formed extraction payload for every call."""

    def __init__(self) -> None:
        self.call_count = 0

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        self.call_count += 1
        return {
            "args": ["x"],
            "return_type": "bool",
            "domain_constraints": [],
            "postcondition": "ret == (x > 0)",
            "confidence": "low",
            "notes": f"stub call {self.call_count}",
        }

    def healthcheck(self) -> None:
        return None


def test_end_to_end_record_then_replay_produces_identical_report(tmp_path: Path) -> None:
    """The artifact-evaluation use case: record a real run, replay it offline,
    and verify the second report matches the first byte-for-byte (modulo
    timestamps and run_id)."""
    from dualify.runner import run_experiment

    transcript = tmp_path / "rt_e2e.jsonl"

    recorder = RecordingLLMClient(
        inner=_StubLLM(),
        transcript_path=transcript,
        model="stub",
        base_url="stub",
        provider="stub",
    )
    recorded_report = run_experiment(
        model="stub",
        base_url="stub",
        benchmark_name="synthetic",
        client_override=recorder,
    )
    recorder.close()
    assert recorded_report["summary"]["total_cases"] >= 1

    player = ReplayLLMClient.from_path(transcript)
    replayed_report = run_experiment(
        model="stub",
        base_url="stub",
        benchmark_name="synthetic",
        client_override=player,
    )
    assert player.remaining_calls() == 0

    def _strip_volatile(report: dict) -> dict:
        scrubbed = dict(report)
        scrubbed.pop("run_id", None)
        scrubbed.pop("ran_at_utc", None)
        return scrubbed

    assert _strip_volatile(recorded_report) == _strip_volatile(replayed_report)


def test_recording_is_line_buffered_visible_mid_stream(tmp_path: Path) -> None:
    """Each generate_json call must commit its record to disk immediately,
    so a sibling process reading the file (or a subsequent resume) sees the
    prefix without waiting for the recorder to close."""
    transcript = tmp_path / "live.jsonl"
    fake = FakeLLMClient([{"i": 0}, {"i": 1}, {"i": 2}])
    recorder = RecordingLLMClient(
        inner=fake,
        transcript_path=transcript,
        model="m",
        base_url="b",
        provider="p",
    )
    # Header is written eagerly in __post_init__.
    assert transcript.read_text().count("\n") == 1

    recorder.generate_json("first")
    assert transcript.read_text().count("\n") == 2  # header + 1 record

    recorder.generate_json("second")
    assert transcript.read_text().count("\n") == 3  # header + 2 records

    recorder.close()
    assert transcript.read_text().count("\n") == 3  # closing does not add a line


def test_resume_serves_cached_prefix_then_falls_through(tmp_path: Path) -> None:
    transcript = tmp_path / "interrupted.jsonl"

    # Phase 1: a recording that we will "interrupt" after 2 of 4 calls.
    fake1 = FakeLLMClient([{"i": 0}, {"i": 1}])
    recorder = RecordingLLMClient(
        inner=fake1,
        transcript_path=transcript,
        model="m",
        base_url="b",
        provider="p",
    )
    recorder.generate_json("p0")
    recorder.generate_json("p1")
    recorder.close()
    assert len(_read_jsonl(transcript)) == 3  # header + 2 records

    # Phase 2: resume against a live client that only knows the suffix.
    fake2 = FakeLLMClient([{"i": 2}, {"i": 3}])
    resumer = ResumingLLMClient.from_path(inner=fake2, path=transcript)
    assert resumer.cached_remaining() == 2

    # First two calls -> cached, no live LLM call.
    assert resumer.generate_json("p0") == {"i": 0}
    assert resumer.generate_json("p1") == {"i": 1}
    assert fake2.calls == []  # nothing forwarded yet
    assert resumer.cached_remaining() == 0
    assert resumer.appended_count() == 0

    # Next two calls -> forwarded to inner and appended.
    assert resumer.generate_json("p2") == {"i": 2}
    assert resumer.generate_json("p3") == {"i": 3}
    assert [c[0] for c in fake2.calls] == ["p2", "p3"]
    assert resumer.appended_count() == 2
    resumer.close()

    # Final transcript = header + 4 records, contiguous call_index 0..3.
    records = _read_jsonl(transcript)
    assert len(records) == 5
    assert records[0]["transcript_metadata"]["model"] == "m"
    assert [r["call_index"] for r in records[1:]] == [0, 1, 2, 3]
    assert [r["prompt"] for r in records[1:]] == ["p0", "p1", "p2", "p3"]


def test_resume_detects_prompt_drift_at_boundary(tmp_path: Path) -> None:
    """If the caller re-issues a different prompt for an already-recorded
    call, the resume must raise immediately rather than silently producing
    a stale response (or worse, poisoning the suffix)."""
    transcript = tmp_path / "drift.jsonl"
    fake1 = FakeLLMClient([{"x": 1}])
    recorder = RecordingLLMClient(
        inner=fake1,
        transcript_path=transcript,
        model="m",
        base_url="b",
        provider="p",
    )
    recorder.generate_json("original prompt")
    recorder.close()

    fake2 = FakeLLMClient([])
    resumer = ResumingLLMClient.from_path(inner=fake2, path=transcript)
    with pytest.raises(TranscriptPromptMismatchError) as exc_info:
        resumer.generate_json("mutated prompt")
    assert "prompt hash mismatch" in str(exc_info.value)
    assert fake2.calls == []  # never forwarded
    resumer.close()


def test_resume_full_run_equals_record_from_scratch(tmp_path: Path) -> None:
    """Round-trip: record-all and (record-half + resume-rest) must yield
    byte-identical transcripts modulo the metadata timestamp."""
    prompts = [f"prompt {i}" for i in range(5)]
    responses = [{"i": i} for i in range(5)]

    # Path A: record from scratch.
    scratch = tmp_path / "scratch.jsonl"
    rec_a = RecordingLLMClient(
        inner=FakeLLMClient(list(responses)),
        transcript_path=scratch,
        model="m",
        base_url="b",
        provider="p",
    )
    for p in prompts:
        rec_a.generate_json(p)
    rec_a.close()

    # Path B: record first 2, then resume with the remaining 3.
    split = tmp_path / "split.jsonl"
    rec_b = RecordingLLMClient(
        inner=FakeLLMClient(list(responses[:2])),
        transcript_path=split,
        model="m",
        base_url="b",
        provider="p",
    )
    rec_b.generate_json(prompts[0])
    rec_b.generate_json(prompts[1])
    rec_b.close()

    resumer = ResumingLLMClient.from_path(
        inner=FakeLLMClient(list(responses[2:])),
        path=split,
    )
    # First two calls are served from the cached prefix.
    resumer.generate_json(prompts[0])
    resumer.generate_json(prompts[1])
    # Remaining three are forwarded.
    for p in prompts[2:]:
        resumer.generate_json(p)
    resumer.close()

    records_a = _read_jsonl(scratch)[1:]  # drop header
    records_b = _read_jsonl(split)[1:]
    # call_index, prompt, prompt_sha256, temperature, response must all match.
    for ra, rb in zip(records_a, records_b, strict=True):
        assert ra["call_index"] == rb["call_index"]
        assert ra["prompt"] == rb["prompt"]
        assert ra["prompt_sha256"] == rb["prompt_sha256"]
        assert ra["temperature"] == rb["temperature"]
        assert ra["response"] == rb["response"]


def test_resume_on_empty_transcript_acts_like_recording(tmp_path: Path) -> None:
    """If the existing transcript holds only a header (no records yet),
    resume should forward every call to the live client."""
    transcript = tmp_path / "header_only.jsonl"
    # Write only the metadata header.
    transcript.write_text(json.dumps({"transcript_metadata": {"version": 1, "model": "m"}}) + "\n")
    fake = FakeLLMClient([{"x": 1}, {"x": 2}])
    resumer = ResumingLLMClient.from_path(inner=fake, path=transcript)
    assert resumer.cached_remaining() == 0
    assert resumer.generate_json("a") == {"x": 1}
    assert resumer.generate_json("b") == {"x": 2}
    resumer.close()
    records = _read_jsonl(transcript)
    assert len(records) == 3
    assert [r["call_index"] for r in records[1:]] == [0, 1]
