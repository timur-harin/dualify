"""Tests for the record/replay transcript module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dualify.transcript import (
    RecordingLLMClient,
    ReplayLLMClient,
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
