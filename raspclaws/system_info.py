"""CPU 온도/사용률, RAM 사용률 (기존 WEBUI의 Hard Ware 모듈 대체)."""
from __future__ import annotations

from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

_THERMAL = Path("/sys/class/thermal/thermal_zone0/temp")


def cpu_temperature() -> float | None:
    try:
        return round(int(_THERMAL.read_text().strip()) / 1000.0, 1)
    except (OSError, ValueError):
        return None


def snapshot() -> dict:
    data = {"cpu_temp": cpu_temperature(), "cpu_usage": None, "ram_usage": None}
    if psutil:
        data["cpu_usage"] = psutil.cpu_percent(interval=None)
        data["ram_usage"] = psutil.virtual_memory().percent
    return data
