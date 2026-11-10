"""Ortak yardımcılar: ffmpeg çağrıları, servis döngüsü, sistem bilgisi."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import traceback
from pathlib import Path
from typing import Callable

import numpy as np

from . import config, db
from .log import get as get_log

log = get_log("utils")


def run(cmd: list[str], timeout: float | None = None, check: bool = True) -> subprocess.CompletedProcess:
    log.debug("RUN %s", " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"Komut başarısız ({p.returncode}): {' '.join(cmd[:4])}...\n{p.stderr[-2000:]}")
    return p


def ffprobe_duration(path: str | Path) -> float:
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            timeout=60, check=False)
    try:
        return float(json.loads(p.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def ffprobe_video(path: str | Path) -> dict:
    p = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height", "-of", "json", str(path)], timeout=60, check=False)
    try:
        s = json.loads(p.stdout)["streams"][0]
        return {"width": int(s["width"]), "height": int(s["height"])}
    except Exception:
        return {"width": 0, "height": 0}


def has_audio(path: str | Path) -> bool:
    p = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
             "-of", "csv=p=0", str(path)], timeout=60, check=False)
    return bool(p.stdout.strip())


def audio_db_per_second(path: str | Path, sr: int = 8000) -> np.ndarray:
    """Dosyanın sesini saniye saniye dBFS olarak döndürür."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    p = subprocess.run(cmd, capture_output=True, timeout=600)
    if p.returncode != 0 or not p.stdout:
        return np.zeros(0)
    a = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    n = len(a) // sr
    if n == 0:
        return np.zeros(0)
    a = a[: n * sr].reshape(n, sr)
    rms = np.sqrt(np.mean(a * a, axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-9)


def extract_audio(src: str | Path, dst: str | Path, start: float = 0, duration: float | None = None) -> Path:
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(src)]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", str(dst)]
    run(cmd, timeout=300)
    return Path(dst)


def safe_name(s: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", s or "x").strip("_")
    return (s or "x")[:maxlen]


def disk_used_percent(p: str | Path | None = None) -> float:
    u = shutil.disk_usage(str(p or config.data_dir()))
    return 100.0 * u.used / u.total


def remove(p: str | Path | None) -> None:
    if not p:
        return
    try:
        pp = Path(p)
        if pp.is_dir():
            shutil.rmtree(pp, ignore_errors=True)
        elif pp.exists():
            pp.unlink()
    except OSError as e:
        log.warning("Silinemedi %s: %s", p, e)


def system_info() -> dict:
    cpu = os.cpu_count() or 1
    ram_gb = 0.0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    ram_gb = int(line.split()[1]) / 1024 / 1024
                    break
    except OSError:
        pass
    du = shutil.disk_usage(str(config.data_dir()))
    os_name = ""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    os_name = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return {"cpu": cpu, "ram_gb": round(ram_gb, 1), "disk_total_gb": round(du.total / 1e9, 1),
            "disk_free_gb": round(du.free / 1e9, 1), "os": os_name}


def auto_concurrency() -> int:
    """Sunucu gücüne göre aynı anda kaydedilecek yayın sayısı."""
    v = config.get("streams.max_concurrent", "auto")
    if str(v).lower() != "auto":
        try:
            return max(1, int(v))
        except ValueError:
            pass
    info = system_info()
    # Kayıt ucuzdur; asıl yük anı bulma + kurgu (CPU). Yayın başına ~2 çekirdek, ~1.5 GB RAM, ~15 GB disk.
    n = min(info["cpu"] // 2, int(info["ram_gb"] / 1.5), int(info["disk_total_gb"] * 0.6 / 15))
    return max(1, min(n, int(config.get("streams.max_auto", 6))))


def service_loop(name: str, fn: Callable[[], float | None], default_interval: float = 30) -> None:
    """Bir servisi sonsuza kadar çalıştırır. Hata olursa kaydeder ve devam eder."""
    slog = get_log(name)
    slog.info("%s servisi başladı", name)
    errors = 0
    while True:
        try:
            db.heartbeat(name)
            wait = fn()
            errors = 0
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            errors += 1
            slog.error("Hata: %s\n%s", e, traceback.format_exc())
            if errors in (5, 50):
                db.alert(f"⚠️ {name} servisi üst üste {errors} kez hata verdi: {str(e)[:300]}",
                         level="error", key=f"svc-err-{name}", dedupe_hours=3)
            wait = min(300, 10 * errors)
        time.sleep(wait if wait is not None else default_interval)
