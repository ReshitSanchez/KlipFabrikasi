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


# Ayardaki model sağlayıcıda yoksa (sağlayıcılar eski modelleri kaldırabiliyor) sırayla denenecek modeller
PREFERRED_CHAT = [
    "openai/gpt-oss-120b", "llama-3.3-70b-versatile", "meta-llama/llama-4-maverick-17b-128e-instruct",
    "moonshotai/kimi-k2-instruct", "qwen/qwen3-32b", "meta-llama/llama-4-scout-17b-16e-instruct",
    "openai/gpt-oss-20b", "llama-3.1-8b-instant",
]
_NOT_CHAT = ("whisper", "guard", "safeguard", "tts", "playai", "orpheus", "distil", "embed", "compound", "prompt-guard")


def list_models(base: str, key: str) -> list[str]:
    r = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    return [m["id"] for m in r.json().get("data", []) if m.get("active", True)]


def pick_available(base: str, key: str, configured: str, preferred: list[str], chat: bool = True) -> str | None:
    """Ayardaki model yoksa sağlayıcıdaki uygun bir modeli seçer ve hatırlar."""
    try:
        ids = list_models(base, key)
    except Exception as e:  # noqa: BLE001
        log.warning("Model listesi alınamadı: %s", e)
        return None
    for m in preferred:
        if m in ids and m != configured:
            return m
    if chat:
        rest = [m for m in ids if not any(x in m.lower() for x in _NOT_CHAT) and m != configured]
        return rest[0] if rest else None
    return None


def model_override(kind: str) -> str | None:
    return db.kv_get(f"model_override:{kind}")


def set_model_override(kind: str, configured: str, new: str) -> None:
    db.kv_set(f"model_override:{kind}", new)
    db.alert(f"🤖 '{configured}' modeli artık kullanılamıyor; otomatik olarak '{new}' modeline geçildi. "
             f"Kalıcı yapmak için config.yaml'da ilgili model satırını '{new}' yapabilirsiniz.",
             level="warning", key=f"model-{kind}-{new}", dedupe_hours=24 * 7)
    log.warning("Model '%s' bulunamadı, '%s' kullanılıyor", configured, new)


def chat_json(system: str, user: str, purpose: str = "llm", max_tokens: int = 1500, retries: int = 3) -> dict:
    """Sohbet modeline sorar, JSON nesnesi döndürür."""
    base = str(config.get("llm.base_url", "https://api.groq.com/openai/v1")).rstrip("/")
    configured = config.get("llm.model", "llama-3.3-70b-versatile")
    model = model_override("chat") or configured
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": float(config.get("llm.temperature", 0.4)),
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if "gpt-oss" in model:  # düşünen modeller: kısa düşünme, yanıta yer kalsın
        body["reasoning_effort"] = "low"
        body["max_tokens"] = max(max_tokens, 2000)
    last_err: Exception | None = None
    switched = False
    for attempt in range(retries + 1):
        try:
            r = requests.post(f"{base}/chat/completions", json=body, timeout=120,
                              headers={"Authorization": f"Bearer {_key()}"})
            if r.status_code in (400, 404) and not switched and (
                    r.status_code == 404 or "model" in r.text.lower() and (
                    "decommission" in r.text.lower() or "not found" in r.text.lower()
                    or "does not exist" in r.text.lower())):
                new = pick_available(base, _key(), model, PREFERRED_CHAT)
                if new:
                    set_model_override("chat", configured, new)
                    body["model"] = model = new
                    if "gpt-oss" in new:
                        body["reasoning_effort"] = "low"
                        body["max_tokens"] = max(max_tokens, 2000)
                    else:
                        body.pop("reasoning_effort", None)
                    switched = True
                    continue
            if r.status_code >= 400 and r.status_code not in (429,) and r.status_code < 500:
                log.warning("LLM %s yanıtı: %s", r.status_code, r.text[:300])
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
