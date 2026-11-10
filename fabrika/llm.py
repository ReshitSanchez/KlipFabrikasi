"""OpenAI uyumlu LLM istemcisi (Groq, OpenRouter, OpenAI, DeepSeek...). JSON çıktı + maliyet takibi."""
from __future__ import annotations

import json
import re
import time

import requests

from . import config, db
from .log import get as get_log

log = get_log("llm")


class LLMError(RuntimeError):
    pass


def _key() -> str:
    k = config.env("LLM_API_KEY") or config.env("GROQ_API_KEY")
    if not k:
        raise LLMError("LLM_API_KEY .env dosyasında yok")
    return k


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def chat_json(system: str, user: str, purpose: str = "llm", max_tokens: int = 1500, retries: int = 3) -> dict:
    """Sohbet modeline sorar, JSON nesnesi döndürür."""
    base = str(config.get("llm.base_url", "https://api.groq.com/openai/v1")).rstrip("/")
    model = config.get("llm.model", "llama-3.3-70b-versatile")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": float(config.get("llm.temperature", 0.4)),
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.post(f"{base}/chat/completions", json=body, timeout=120,
                              headers={"Authorization": f"Bearer {_key()}"})
            if r.status_code == 429 or r.status_code >= 500:
                wait = float(r.headers.get("retry-after", 0) or 0) or (5 * (attempt + 1))
                log.warning("LLM %s, %ss bekleniyor", r.status_code, wait)
                time.sleep(min(wait, 60))
                continue
            if r.status_code == 400 and "response_format" in r.text and "response_format" in body:
                body.pop("response_format")  # bazı modeller JSON modunu desteklemez
                continue
            r.raise_for_status()
            data = r.json()
            usage = data.get("usage") or {}
            cost = (usage.get("prompt_tokens", 0) * float(config.get("llm.price_input_per_million", 0.6))
                    + usage.get("completion_tokens", 0) * float(config.get("llm.price_output_per_million", 0.8))) / 1e6
            db.add_cost("llm", cost, purpose)
            content = data["choices"][0]["message"].get("content") or ""
            return _extract_json(content)
        except (requests.RequestException, ValueError, KeyError) as e:
            last_err = e
            log.warning("LLM denemesi %d başarısız: %s", attempt + 1, e)
            time.sleep(3 * (attempt + 1))
    raise LLMError(f"LLM yanıt vermedi: {last_err}")
