from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class HuggingFaceAdvisor:
    enabled: bool = False
    model: str = ""
    timeout_seconds: int = 12
    api_key: str = ""

    def __post_init__(self) -> None:
        if not self.api_key:
            self.api_key = os.getenv("HF_API_KEY", "").strip()
        if not self.model:
            self.model = os.getenv("HF_MODEL", "").strip()

    def available(self) -> bool:
        return self.enabled and bool(self.api_key and self.model)

    def score_context(self, prompt: str) -> dict[str, Any]:
        if not self.available():
            return {
                "score": 0.5,
                "summary": "AI layer disabled; falling back to deterministic logic.",
            }

        url = f"https://api-inference.huggingface.co/models/{self.model}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"inputs": prompt}

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
            resp.raise_for_status()
            data = resp.json()
            return {
                "score": 0.7,
                "summary": data if isinstance(data, str) else str(data)[:2000],
            }
        except Exception as exc:
            return {
                "score": 0.5,
                "summary": f"AI call failed: {exc}",
            }

