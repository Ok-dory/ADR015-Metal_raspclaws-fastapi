"""트라이포드(삼각) 보행 엔진.

한 주기(phase 0→1) 동안 TRIPOD_A 와 TRIPOD_B 가 반 주기씩 엇갈려
'들고 앞으로(swing)' → '딛고 뒤로(stance)' 동작을 반복합니다.
보행 패턴을 바꾸고 싶으면 _leg_pose() 만 수정하면 됩니다.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass

from ..robot_layout import LEGS, TRIPOD_A
from ..servo import ServoController

log = logging.getLogger(__name__)

# 방향별 (왼쪽 다리 계수, 오른쪽 다리 계수)
DIRECTIONS: dict[str, tuple[int, int]] = {
    "forward": (1, 1),
    "backward": (-1, -1),
    "left": (-1, 1),    # 제자리 좌회전
    "right": (1, -1),   # 제자리 우회전
}


@dataclass
class GaitParams:
    step_amplitude: float = 18.0   # hip 스윙 진폭(deg)
    lift_height: float = 25.0      # 다리 드는 높이(deg)
    lift_sign: int = 1             # 다리가 '위'로 가는 논리 방향 (+1/-1)
    period_fast: float = 0.8       # 한 주기 시간(s)
    period_slow: float = 1.4
    rate_hz: float = 50.0


class GaitEngine:
    def __init__(self, servos: ServoController, params: GaitParams | None = None) -> None:
        self.servos = servos
        self.params = params or GaitParams()
        self.fast = False
        self._direction: str | None = None
        self._phase = 0.0
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ 외부 API
    @property
    def direction(self) -> str | None:
        return self._direction

    @property
    def period(self) -> float:
        return self.params.period_fast if self.fast else self.params.period_slow

    def move(self, direction: str) -> None:
        if direction not in DIRECTIONS:
            raise ValueError(f"알 수 없는 방향: {direction}")
        with self._lock:
            self._direction = direction

    def stop(self) -> None:
        with self._lock:
            self._direction = None

    def stand(self) -> None:
        """모든 다리를 중립 자세로."""
        self.stop()
        pose = {}
        for leg in LEGS:
            pose[leg.hip] = 90.0
            pose[leg.lift] = 90.0
        self.servos.set_many(pose, speed=120)

    def start(self) -> None:
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="gait", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2)

    # ------------------------------------------------------------------ 내부
    def _leg_pose(self, phase: float, dir_coef: int) -> tuple[float, float]:
        """phase(0~1) → (hip 논리각, lift 논리각)."""
        p = self.params
        if phase < 0.5:   # swing: 들어서 뒤→앞
            t = phase / 0.5
            swing = -p.step_amplitude + 2 * p.step_amplitude * t
            lift = math.sin(math.pi * t) * p.lift_height
        else:             # stance: 딛고 앞→뒤 (몸이 앞으로 나아감)
            t = (phase - 0.5) / 0.5
            swing = p.step_amplitude - 2 * p.step_amplitude * t
            lift = 0.0
        return 90.0 + swing * dir_coef, 90.0 + lift * p.lift_sign

    def _loop(self) -> None:
        dt = 1.0 / self.params.rate_hz
        was_moving = False
        while self._running.is_set():
            t0 = time.monotonic()
            with self._lock:
                direction = self._direction
            if direction is None:
                if was_moving:
                    self._phase = 0.0
                    self.stand()
                    was_moving = False
            else:
                was_moving = True
                self._phase = (self._phase + dt / self.period) % 1.0
                lcoef, rcoef = DIRECTIONS[direction]
                pose: dict[int, float] = {}
                for leg in LEGS:
                    leg_phase = self._phase if leg.name in TRIPOD_A else (self._phase + 0.5) % 1.0
                    coef = lcoef if leg.side == "L" else rcoef
                    hip, lift = self._leg_pose(leg_phase, coef)
                    pose[leg.hip] = hip
                    pose[leg.lift] = lift
                self.servos.set_many(pose, speed=None)
            time.sleep(max(0.0, dt - (time.monotonic() - t0)))
