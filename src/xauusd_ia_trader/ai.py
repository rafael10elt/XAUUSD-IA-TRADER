from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import requests


# ---------------------------------------------------------------------------
# Provider detection helpers
# ---------------------------------------------------------------------------

_GROQ_MODELS: set[str] = {
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
    "gemma-7b-it",
}

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_HF_ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"
_HF_INFERENCE_URL = "https://api-inference.huggingface.co/models/{model}"


def _detect_provider(api_key: str, model: str) -> str:
    """Return 'groq' or 'huggingface' based on key prefix and model name."""
    if api_key.startswith("gsk_"):
        return "groq"
    if model in _GROQ_MODELS:
        return "groq"
    return "huggingface"


# ---------------------------------------------------------------------------
# Main advisor class
# ---------------------------------------------------------------------------

@dataclass
class HuggingFaceAdvisor:
    """AI advisor that transparently supports Groq and HuggingFace backends."""

    enabled: bool = False
    model: str = ""
    timeout_seconds: int = 12
    api_key: str = ""

    def __post_init__(self) -> None:
        if not self.api_key:
            self.api_key = os.getenv("HF_API_KEY", "").strip()
        if not self.model:
            self.model = os.getenv("HF_MODEL", "").strip()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def available(self) -> bool:
        return self.enabled and bool(self.api_key and self.model)

    @property
    def provider(self) -> str:
        return _detect_provider(self.api_key, self.model)

    # ------------------------------------------------------------------
    # Internal: OpenAI-compatible chat (Groq + HF Router)
    # ------------------------------------------------------------------

    def _openai_chat(
        self,
        url: str,
        model: str,
        question: str,
        *,
        context: str = "",
        history: list[tuple[str, str]] | None = None,
    ) -> tuple[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
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
            "max_tokens": 512,
            "stream": False,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
        if resp.status_code in (404, 422):
            raise FileNotFoundError(f"Modelo indisponível no provider: {model} (HTTP {resp.status_code})")
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

    # ------------------------------------------------------------------
    # Internal: HuggingFace text-generation fallback
    # ------------------------------------------------------------------

    def _hf_text_generation(self, prompt: str) -> dict[str, Any]:
        url = _HF_INFERENCE_URL.format(model=self.model)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 512,
                "temperature": 0.3,
                "return_full_text": False,
                "do_sample": True,
            },
            "options": {"wait_for_model": True},
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
        if resp.status_code == 404:
            raise FileNotFoundError(f"Modelo não disponível na API HF: {self.model}")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # score_context (used by autonomous trader loop)
    # ------------------------------------------------------------------

    def score_context(self, prompt: str) -> dict[str, Any]:
        if not self.available():
            return {
                "score": 0.5,
                "summary": "Camada de IA desativada; usando lógica determinística.",
            }
        try:
            if self.provider == "groq":
                answer, _ = self._openai_chat(
                    _GROQ_URL, self.model, prompt
                )
                return {"score": 0.7, "summary": answer or str(prompt)[:200]}
            else:
                data = self._hf_text_generation(prompt)
                return {
                    "score": 0.7,
                    "summary": data if isinstance(data, str) else str(data)[:2000],
                }
        except Exception as exc:
            return {"score": 0.5, "summary": f"Falha na IA: {exc}"}

    # ------------------------------------------------------------------
    # chat (used by GUI chat tab)
    # ------------------------------------------------------------------

    def chat(
        self,
        question: str,
        *,
        context: str = "",
        history: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        if not self.available():
            return {
                "answer": (
                    "A camada de IA está desativada ou sem credenciais válidas. "
                    "Configure a HF API Key e o modelo na aba IA e clique em 'Aplicar configuração IA'."
                ),
                "raw": None,
                "backend": "disabled",
            }

        try:
            if self.provider == "groq":
                # Groq: single call, model already known
                answer, data = self._openai_chat(
                    _GROQ_URL,
                    self.model,
                    question,
                    context=context,
                    history=history,
                )
                if answer.strip():
                    return {"answer": answer.strip(), "raw": data, "backend": f"groq:{self.model}"}
                return {
                    "answer": "A IA não retornou resposta. Tente novamente.",
                    "raw": data,
                    "backend": f"groq:{self.model}",
                }

            else:
                # HuggingFace: try router first, then text-generation fallback
                candidates = self._hf_candidate_models()
                router_errors: list[str] = []

                for model in candidates:
                    try:
                        answer, data = self._openai_chat(
                            _HF_ROUTER_URL,
                            model,
                            question,
                            context=context,
                            history=history,
                        )
                        if answer.strip():
                            return {"answer": answer.strip(), "raw": data, "backend": f"hf-router:{model}"}
                    except Exception as exc:
                        router_errors.append(f"{model}: {exc}")

                # Fallback to text-generation
                prompt_parts = [
                    "Você é um assistente de trading para XAUUSD em português do Brasil.",
                    "Responda de forma objetiva, prática e segura.",
                ]
                if context.strip():
                    prompt_parts += ["Contexto:", context.strip()]
                if history:
                    for role, text in history[-4:]:
                        prompt_parts.append(f"{role}: {text}")
                prompt_parts += [f"Pergunta: {question.strip()}", "Resposta:"]
                data = self._hf_text_generation("\n".join(prompt_parts))
                answer = ""
                if isinstance(data, list) and data:
                    first = data[0]
                    if isinstance(first, dict):
                        answer = str(first.get("generated_text") or first.get("summary_text") or "")
                elif isinstance(data, dict):
                    answer = str(data.get("generated_text") or data.get("summary_text") or data)
                if not answer.strip():
                    answer = str(data)[:2000]
                return {"answer": answer.strip(), "raw": data, "backend": f"hf-text-gen:{self.model}"}

        except Exception as exc:
            return {
                "answer": f"Falha ao consultar a IA: {exc}",
                "raw": None,
                "backend": "error",
            }

    def _hf_candidate_models(self) -> list[str]:
        preferred = [
            self.model,
            "Qwen/Qwen2.5-7B-Instruct",
            "Qwen/Qwen2.5-7B-Instruct-1M",
            "google/gemma-2-2b-it",
        ]
        seen: set[str] = set()
        candidates: list[str] = []
        for item in preferred:
            m = str(item or "").strip()
            if not m or m in seen:
                continue
            seen.add(m)
            candidates.append(m)
        return candidates