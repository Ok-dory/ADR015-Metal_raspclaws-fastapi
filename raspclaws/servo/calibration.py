"""서보 영점(center) 캘리브레이션 저장/불러오기.

기존 WEBUI의 'PWM INIT SET → SETPWM → Servos_Init.json' 흐름을 대체합니다.
Adeept 원본 Servos_Init.json 을 data/ 에 복사해 두면 자동으로 읽어옵니다.
여기서 center 는 '논리 각도 90°일 때 실제로 보낼 물리 각도'입니다.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_CENTER = 90.0


class CalibrationStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[int, float]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            # Adeept 원본 형식 {"servo_angles": [16개]} 도 그대로 가져오기
            if isinstance(data, dict) and isinstance(data.get("servo_angles"), list):
                return {i: float(v) for i, v in enumerate(data["servo_angles"])}
            centers = data.get("centers", data) if isinstance(data, dict) else {}
            return {int(k): float(v) for k, v in centers.items()}
        except Exception as exc:
            log.error("캘리브레이션 파일을 읽지 못했습니다(%s): %s", self.path, exc)
            return {}

    def save(self, centers: dict[int, float]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "centers": {str(ch): round(v, 2) for ch, v in sorted(centers.items())},
        }
        # 원자적 쓰기: 저장 중 전원이 꺼져도 파일이 깨지지 않도록
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)
        log.info("캘리브레이션 저장: %s", self.path)
