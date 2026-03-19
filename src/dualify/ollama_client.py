import json
from dataclasses import dataclass

import requests


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

