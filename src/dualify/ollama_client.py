import json
from dataclasses import dataclass
from typing import Protocol

import requests


class LLMClient(Protocol):
    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict: ...

    def healthcheck(self) -> None: ...


def _extract_json_object(raw_text: str) -> dict:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise json.JSONDecodeError("No JSON object found in model response", raw_text, 0)
    return json.loads(raw_text[start : end + 1])


@dataclass
class OllamaClient:
    model: str
    base_url: str = "http://127.0.0.1:11434"
    timeout_sec: int = 30

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature},
        }
        response = requests.post(url, json=payload, timeout=self.timeout_sec)
        response.raise_for_status()
        body = response.json()
        raw_text = body.get("response", "{}")
        return json.loads(raw_text)

    def healthcheck(self) -> None:
        url = f"{self.base_url}/api/version"
        response = requests.get(url, timeout=10)
        response.raise_for_status()


@dataclass
class OpenAICompatibleClient:
    model: str
    base_url: str
    api_key: str = ""
    timeout_sec: int = 60

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        url = f"{self.base_url}/v1/completions"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "max_tokens": 1024,
            "temperature": temperature,
        }
        response = requests.post(
            url,
            json=payload,
            headers=self._headers(),
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices", [])
        if not isinstance(choices, list) or not choices:
            raise ValueError("Completion response has no choices")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ValueError("Completion response choice has invalid shape")
        text = first_choice.get("text", "")
        if not isinstance(text, str):
            raise ValueError("Completion response text is not a string")
        return _extract_json_object(text)

    def healthcheck(self) -> None:
        url = f"{self.base_url}/v1/models"
        response = requests.get(url, headers=self._headers(), timeout=10)
        response.raise_for_status()


def create_llm_client(
    *,
    provider: str,
    model: str,
    base_url: str,
    api_key: str = "",
) -> LLMClient:
    normalized_base_url = base_url.rstrip("/")
    if provider == "ollama":
        return OllamaClient(model=model, base_url=normalized_base_url)
    if provider == "openai":
        return OpenAICompatibleClient(
            model=model,
            base_url=normalized_base_url,
            api_key=api_key,
        )
    raise ValueError(f"Unsupported provider: {provider}")

