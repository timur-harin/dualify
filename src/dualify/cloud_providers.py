"""Rate-limit and retry profiles for hosted OpenAI-compatible providers.

Limits sourced from https://github.com/mnfst/awesome-free-llm-apis (Groq/SambaNova
free tiers, 2026). ``min_interval_sec`` is derived from RPM with a small buffer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CloudProviderProfile:
    name: str
    rpm: int
    rpd: int | None
    min_interval_sec: float
    timeout_sec: int
    max_retries: int
    backoff_base_sec: float
    max_backoff_sec: float


# Groq: llama-3.3-70b-versatile — 30 RPM, 1,000 RPD (free tier).
GROQ = CloudProviderProfile(
    name="groq",
    rpm=30,
    rpd=1000,
    min_interval_sec=2.1,
    timeout_sec=120,
    max_retries=6,
    backoff_base_sec=2.0,
    max_backoff_sec=60.0,
)

# SambaNova: gemma-4-31B-it — 20 RPM, 20 RPD, 200K TPD (free tier).
SAMBANOVA = CloudProviderProfile(
    name="sambanova",
    rpm=20,
    rpd=20,
    min_interval_sec=3.2,
    timeout_sec=180,
    max_retries=8,
    backoff_base_sec=3.0,
    max_backoff_sec=90.0,
)

# OpenRouter free ``:free`` models — 20 RPM, 200 RPD (default free tier).
OPENROUTER_FREE = CloudProviderProfile(
    name="openrouter",
    rpm=20,
    rpd=200,
    min_interval_sec=3.2,
    timeout_sec=180,
    max_retries=8,
    backoff_base_sec=3.0,
    max_backoff_sec=90.0,
)


def profile_for_base_url(base_url: str) -> CloudProviderProfile | None:
    host = base_url.lower()
    if "groq.com" in host:
        return GROQ
    if "sambanova.ai" in host:
        return SAMBANOVA
    if "openrouter.ai" in host:
        return OPENROUTER_FREE
    return None
