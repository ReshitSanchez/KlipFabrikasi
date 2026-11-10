"""Yayın platformları. Her modül `find_live(game: dict) -> list[dict]` sağlar.

Dönen sözlük alanları: platform, slug, display_name, platform_stream_id, url, channel_url,
title, viewers, language, started_at (unix), chat_ref
"""
from datetime import datetime


def iso_to_ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
