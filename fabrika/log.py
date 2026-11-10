import logging
import sys

from . import config

_configured = False


def get(name: str) -> logging.Logger:
    global _configured
    if not _configured:
        level = getattr(logging, str(config.get("general.log_level", "INFO")).upper(), logging.INFO)
        logging.basicConfig(
            level=level,
            stream=sys.stdout,
            format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        for noisy in ("googleapiclient", "urllib3", "websockets", "httpx", "chat_downloader"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        _configured = True
    return logging.getLogger(name)
