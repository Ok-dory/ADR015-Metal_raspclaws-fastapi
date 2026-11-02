"""현재 코드 버전(git)과 마지막 업데이트 결과(data/update_status.json)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import PROJECT_ROOT

# 결과 코드 → (웹 표시, OLED 표시[ASCII])
RESULT_TEXT = {
    "updated": ("부팅 시 새 버전으로 업데이트", "UPDATED"),
    "latest": ("부팅 시 확인 · 최신", "LATEST"),
    "offline": ("부팅 시 네트워크 없음 · 기존 버전", "OFFLINE"),
    "skipped": ("업데이트 건너뜀", "UPD SKIPPED"),
    "rolledback": ("새 버전 점검 실패 · 이전 버전으로 복구", "ROLLBACK"),
    "disabled": ("자동 업데이트 꺼짐", "AUTO-UPD OFF"),
    "manual": ("update.sh 로 업데이트", "UPDATED"),
}


def git_version(root: Path = PROJECT_ROOT) -> dict:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%h%x1f%s%x1f%cI"],
            capture_output=True, text=True, timeout=3, check=True).stdout.strip()
        commit, subject, date = out.split("\x1f")
        return {"commit": commit, "subject": subject, "date": date}
    except Exception:
        return {"commit": None, "subject": None, "date": None}


def update_status(data_dir: Path) -> dict | None:
    try:
        st = json.loads((data_dir / "update_status.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    web, oled = RESULT_TEXT.get(st.get("result", ""), (st.get("result", ""), "UPD ?"))
    st["text"] = web
    st["oled"] = oled
    return st


def snapshot(data_dir: Path) -> dict:
    return {**git_version(), "update": update_status(data_dir)}
