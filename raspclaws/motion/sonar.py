"""초음파 센서 회전(CH14) + 거리 측정 + 부채꼴 스캔."""
from __future__ import annotations

import logging
import threading
import time

from ..peripherals import UltrasonicSensor
from ..robot_layout import ULTRASONIC
from ..servo import ServoController

log = logging.getLogger(__name__)


class SonarController:
    def __init__(self, servos: ServoController, sensor: UltrasonicSensor,
                 speed: float = 90.0) -> None:
        self.servos = servos
        self.sensor = sensor
        self.speed = speed
        self.distance: float | None = None
        self.scan_points: list[dict] = []   # [{"angle": 논리각, "distance": cm}]
        self.scan_time: float | None = None
        self._scanning = threading.Event()
        self._running = threading.Event()

    # ------------------------------------------------------------ 회전
    @property
    def angle(self) -> float:
        return self.servos.get_angle(ULTRASONIC)

    def rotate(self, direction: int) -> None:
        """+1 = 왼쪽, -1 = 오른쪽 (누르고 있는 동안 연속 회전)."""
        lo, hi = self.servos.logical_limits(ULTRASONIC)
        self.servos.set_angle(ULTRASONIC, hi if direction > 0 else lo, speed=self.speed)

    def stop_rotate(self) -> None:
        self.servos.hold(ULTRASONIC)

    def point(self, angle: float) -> None:
        lo, hi = self.servos.logical_limits(ULTRASONIC)
        self.servos.set_angle(ULTRASONIC, max(lo, min(hi, angle)))

    # ------------------------------------------------------------ 측정
    def start(self) -> None:
        self._running.set()
        threading.Thread(target=self._poll, name="sonar", daemon=True).start()

    def stop(self) -> None:
        self._running.clear()

    def _poll(self) -> None:
        while self._running.is_set():
            if not self._scanning.is_set():
                self.distance = self.sensor.distance_cm()
            time.sleep(0.1)

    @property
    def scanning(self) -> bool:
        return self._scanning.is_set()

    def scan(self, start: float = 35, end: float = 145, step: float = 10) -> bool:
        """부채꼴 스캔을 백그라운드로 시작. 이미 스캔 중이면 False."""
        if self._scanning.is_set():
            return False
        self._scanning.set()
        threading.Thread(target=self._scan, args=(start, end, step),
                         name="sonar-scan", daemon=True).start()
        return True

    def _scan(self, start: float, end: float, step: float) -> None:
        try:
            lo, hi = self.servos.logical_limits(ULTRASONIC)
            start, end = max(lo, start), min(hi, end)
            points: list[dict] = []
            self.servos.set_angle(ULTRASONIC, start, speed=180)
            time.sleep(0.5)
            a = start
            while a <= end + 1e-6:
                self.servos.set_angle(ULTRASONIC, a, speed=180)
                time.sleep(0.18)
                reads = [d for d in (self.sensor.distance_cm() for _ in range(3)) if d is not None]
                dist = sorted(reads)[len(reads) // 2] if reads else None
                points.append({"angle": round(a, 1), "distance": dist})
                self.distance = dist
                self.scan_points = list(points)
                a += step
            self.scan_time = time.time()
            self.servos.set_angle(ULTRASONIC, 90.0)
        except Exception:
            log.exception("초음파 스캔 오류")
        finally:
            self._scanning.clear()

    def snapshot(self) -> dict:
        return {
            "angle": round(self.angle, 1),
            "distance": self.distance,
            "scanning": self.scanning,
            "scan": self.scan_points,
            "scan_time": self.scan_time,
            "mock": self.sensor.is_mock,
        }
