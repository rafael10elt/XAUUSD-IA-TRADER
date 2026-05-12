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

    def chat(
        self,
        question: str,
        *,
        context: str = "",
        history: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        if not self.available():
            return {
                "answer": "A camada de IA está desativada ou sem credenciais válidas.",
                "raw": None,
            }

        prompt_parts = [
            "Você é um assistente de trading para XAUUSD em português do Brasil.",
            "Responda de forma objetiva, prática e segura.",
            "Não invente resultados; se faltar dado, diga que não tem informação suficiente.",
        ]
        if context.strip():
            prompt_parts.append("Contexto atual do robô:")
            prompt_parts.append(context.strip())
        if history:
            prompt_parts.append("Histórico recente da conversa:")
            for role, text in history[-6:]:
                prompt_parts.append(f"{role}: {text}")
        prompt_parts.append(f"Pergunta: {question.strip()}")
        prompt_parts.append("Resposta:")
        prompt = "\n".join(prompt_parts)

        url = f"https://api-inference.huggingface.co/models/{self.model}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 220,
                "temperature": 0.3,
                "return_full_text": False,
                "do_sample": True,
            },
            "options": {"wait_for_model": True},
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
            resp.raise_for_status()
            data = resp.json()
            answer = ""
            if isinstance(data, list) and data:
                first = data[0]
                if isinstance(first, dict):
                    answer = str(first.get("generated_text") or first.get("summary_text") or "")
            elif isinstance(data, dict):
                answer = str(data.get("generated_text") or data.get("summary_text") or data)
            if not answer.strip():
                answer = str(data)[:2000]
            return {"answer": answer.strip(), "raw": data}
        except Exception as exc:
            return {
                "answer": f"Falha ao consultar a IA: {exc}",
                "raw": None,
            }
