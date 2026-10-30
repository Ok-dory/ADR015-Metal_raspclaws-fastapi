"""초음파 거리 센서 (원본 Ultra.py 기준: TRIG=GPIO23, ECHO=GPIO24, 최대 2m)."""
from __future__ import annotations

import logging
import math
import random
from typing import Callable

log = logging.getLogger(__name__)

TRIG_PIN = 23
ECHO_PIN = 24
MAX_DISTANCE_M = 2.0


class UltrasonicSensor:
    def __init__(self, enabled: bool = True,
                 mock_angle: Callable[[], float] | None = None) -> None:
        self._sensor = None
        self._mock_angle = mock_angle
        if enabled:
            try:
                from gpiozero import DistanceSensor
                self._sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN,
                                              max_distance=MAX_DISTANCE_M)
                log.info("초음파 센서 연결됨 (TRIG=%d, ECHO=%d)", TRIG_PIN, ECHO_PIN)
            except Exception as exc:
                log.warning("초음파 센서 사용 불가 → mock: %s", exc)

    @property
    def is_mock(self) -> bool:
        return self._sensor is None

    def distance_cm(self) -> float | None:
        if self._sensor is not None:
            try:
                return round(self._sensor.distance * 100.0, 1)
            except Exception:
                return None
        # Mock: 센서 각도에 따라 달라지는 가상의 벽 (레이더 화면 테스트용)
        angle = self._mock_angle() if self._mock_angle else 90.0
        base = 60 + 50 * math.cos(math.radians((angle - 90) * 2))
        return round(base + random.uniform(-2, 2), 1)

    def close(self) -> None:
        if self._sensor is not None:
            self._sensor.close()
