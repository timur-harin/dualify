import json
import os
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

    def _debug_raw(self, label: str, raw_text: str) -> None:
        if os.environ.get("DUALIFY_DEBUG_LLM_RAW", "0") != "1":
            return
        snippet = raw_text[:500].replace("\n", "\\n")
        print(f"[dualify-debug] {label}: {snippet}")

    def _extract_choice_text(self, choice: dict, *, chat_mode: bool) -> str:
        if not isinstance(choice, dict):
            raise ValueError("Completion response choice has invalid shape")
        if chat_mode:
            message = choice.get("message", {})
            if not isinstance(message, dict):
                raise ValueError("Chat completion choice message has invalid shape")
            content = message.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                text_parts: list[str] = []
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text", "")
                        if isinstance(text, str):
                            text_parts.append(text)
                return "\n".join(text_parts)
            raise ValueError("Chat completion content has invalid shape")
        text = choice.get("text", "")
        if not isinstance(text, str):
            raise ValueError("Completion response text is not a string")
        return text

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        prefer_chat = os.environ.get("DUALIFY_OPENAI_USE_CHAT", "1") == "1"
        attempts = [True, False] if prefer_chat else [False, True]
        last_exc: Exception | None = None

        for chat_mode in attempts:
            endpoint = "/v1/chat/completions" if chat_mode else "/v1/completions"
            url = f"{self.base_url}{endpoint}"
            if chat_mode:
                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Return only a strict JSON object.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 1024,
                    "temperature": temperature,
                    "response_format": {"type": "json_object"},
                }
            else:
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "max_tokens": 1024,
                    "temperature": temperature,
                }
            try:
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
                text = self._extract_choice_text(choices[0], chat_mode=chat_mode)
                self._debug_raw("chat" if chat_mode else "completion", text)
                return _extract_json_object(text)
            except Exception as exc:
                last_exc = exc
                continue

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("No completion mode succeeded")

    def healthcheck(self) -> None:
        url = f"{self.base_url}/v1/models"
        try:
            response = requests.get(url, headers=self._headers(), timeout=10)
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Cannot reach OpenAI-compatible API at {self.base_url!r}: {exc}"
            ) from exc
        if response.status_code == 401:
            raise RuntimeError(
                "API returned 401 Unauthorized. "
                "Set a valid DUALIFY_API_KEY or GROQ_API_KEY in the environment, "
                "or pass --api-key."
            )
        if response.status_code == 403:
            raise RuntimeError(
                "API returned 403 Forbidden. Check API key permissions and base URL."
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Health check failed ({response.status_code}): {response.text[:500]}"
            ) from exc


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
        if not (api_key or "").strip():
            raise ValueError(
                "Provider 'openai' requires an API key. "
                "Set DUALIFY_API_KEY or GROQ_API_KEY in .env, or pass --api-key."
            )
        return OpenAICompatibleClient(
            model=model,
            base_url=normalized_base_url,
            api_key=api_key.strip(),
        )
    raise ValueError(f"Unsupported provider: {provider}")

