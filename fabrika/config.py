"""config.yaml ve .env okuma. Ayarlar dosya değişince otomatik yeniden okunur."""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

BASE_DIR = Path(os.environ.get("FABRIKA_HOME", os.getcwd())).resolve()
CONFIG_PATH = Path(os.environ.get("FABRIKA_CONFIG", BASE_DIR / "config.yaml"))

if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env", override=False)

_lock = threading.Lock()
_cache: dict[str, Any] = {"mtime": None, "data": None}

LANGUAGE_NAMES = {
    "hi": "Hindi",
    "ja": "Japanese",
    "es": "Latin American Spanish",
    "pt-BR": "Brazilian Portuguese",
    "pt": "Portuguese",
    "en": "English",
    "tr": "Turkish",
    "de": "German",
    "fr": "French",
    "ar": "Arabic",
    "id": "Indonesian",
    "ru": "Russian",
    "ko": "Korean",
}


def load() -> dict:
    """Ayarları döndürür; dosya değiştiyse yeniden okur."""
    with _lock:
        mtime = CONFIG_PATH.stat().st_mtime
        if _cache["data"] is None or _cache["mtime"] != mtime:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                _cache["data"] = yaml.safe_load(f) or {}
            _cache["mtime"] = mtime
        return _cache["data"]


def get(path: str, default: Any = None) -> Any:
    """Noktalı yol ile ayar okur: get("highlights.min_score", 7)."""
    node: Any = load()
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def path(rel: str | os.PathLike) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else BASE_DIR / p


def data_dir() -> Path:
    d = path(get("general.data_dir", "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def output_dir() -> Path:
    d = path(get("general.output_dir", "output"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def assets_dir() -> Path:
    return path(get("general.assets_dir", "assets"))


def active_game(now: datetime | None = None) -> dict:
    """Şu an geçerli oyun kategorisi (test = GTA 5, main = GTA 6)."""
    g = get("game", {}) or {}
    force = (g.get("force") or "").strip().lower()
    if force in ("test", "main"):
        mode = force
    else:
        now = now or datetime.now(timezone.utc)
        switch = g.get("switch_to_main_at")
        mode = "main"
        if switch:
            if isinstance(switch, datetime):
                sw = switch
            else:
                sw = datetime.fromisoformat(str(switch))
            if sw.tzinfo is None:
                sw = sw.replace(tzinfo=timezone.utc)
            mode = "main" if now >= sw else "test"
    out = dict(g.get(mode) or {})
    out["mode"] = mode
    return out


def channels(enabled_only: bool = True) -> list[dict]:
    out = []
    for ch in get("channels", []) or []:
        if enabled_only and not ch.get("enabled", True):
            continue
        out.append(ch)
    return out


def channel(name: str) -> dict | None:
    for ch in get("channels", []) or []:
        if ch.get("name") == name:
            return ch
    return None


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, LANGUAGE_NAMES.get(code.split("-")[0], code))
