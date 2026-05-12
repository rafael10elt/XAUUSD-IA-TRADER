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

    def _candidate_models(self) -> list[str]:
        preferred = [
            self.model,
            "Qwen/Qwen2.5-7B-Instruct",
            "Qwen/Qwen2.5-7B-Instruct-1M",
            "google/gemma-2-2b-it",
        ]
        seen: set[str] = set()
        candidates: list[str] = []
        for item in preferred:
            model = str(item or "").strip()
            if not model or model in seen:
                continue
            seen.add(model)
            candidates.append(model)
        return candidates

    def _router_chat(
        self,
        model: str,
        question: str,
        *,
        context: str = "",
        history: list[tuple[str, str]] | None = None,
    ) -> tuple[str, Any]:
        url = "https://router.huggingface.co/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "Você é um assistente de trading para XAUUSD em português do Brasil. "
                    "Responda de forma objetiva, prática e segura. "
                    "Não invente resultados; se faltar dado, diga que não tem informação suficiente."
                ),
            }
        ]
        if context.strip():
            messages.append({"role": "system", "content": f"Contexto atual do robô:\n{context.strip()}"})
        if history:
            for role, text in history[-6:]:
                messages.append({"role": "user" if role == "user" else "assistant", "content": text})
        messages.append({"role": "user", "content": question.strip()})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 220,
            "stream": False,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
        if resp.status_code == 404:
            raise FileNotFoundError(f"Model or provider unavailable for {self.model}")
        resp.raise_for_status()
        data = resp.json()
        answer = ""
        if isinstance(data, dict):
            choices = data.get("choices") or []
            if choices and isinstance(choices, list):
                first = choices[0] or {}
                message = first.get("message") or {}
                if isinstance(message, dict):
                    answer = str(message.get("content") or "").strip()
                if not answer:
                    answer = str(first.get("text") or "").strip()
        return answer, data

    def _text_generation(self, prompt: str) -> dict[str, Any]:
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
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
        if resp.status_code == 404:
            raise FileNotFoundError(f"Model not available on api-inference for {self.model}")
        resp.raise_for_status()
        return resp.json()

    def score_context(self, prompt: str) -> dict[str, Any]:
        if not self.available():
            return {
                "score": 0.5,
                "summary": "AI layer disabled; falling back to deterministic logic.",
            }

        try:
            data = self._text_generation(prompt)
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

        try:
            router_errors: list[str] = []
            for model in self._candidate_models():
                try:
                    answer, data = self._router_chat(model, question, context=context, history=history)
                    if answer.strip():
                        return {"answer": answer.strip(), "raw": data, "backend": f"router:{model}"}
                except Exception as exc:
                    router_errors.append(f"{model}: {exc}")

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
            data = self._text_generation(prompt)
            answer = ""
            if isinstance(data, list) and data:
                first = data[0]
                if isinstance(first, dict):
                    answer = str(first.get("generated_text") or first.get("summary_text") or "")
            elif isinstance(data, dict):
                answer = str(data.get("generated_text") or data.get("summary_text") or data)
            if not answer.strip():
                answer = str(data)[:2000]
            return {"answer": answer.strip(), "raw": data, "backend": f"text-generation:{self.model}"}
        except Exception as exc:
            detail = f"{exc}"
            return {"answer": f"Falha ao consultar a IA: {detail}", "raw": None, "backend": "error"}
