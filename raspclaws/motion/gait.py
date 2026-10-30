"""트라이포드(삼각) 보행 엔진 — 아날로그 주행 방식.

drive(vx, wz) 로 '전진량'과 '회전량'을 -1~1 연속값으로 받습니다.
    vx: +1 전진 ~ -1 후진
    wz: +1 좌회전 ~ -1 우회전
좌우 다리의 보폭을 다르게 해서(탱크식 차동 조향) 곡선 보행을 만듭니다.
    왼쪽 보폭 = vx - wz,  오른쪽 보폭 = vx + wz   (±1 을 넘으면 비율 유지하며 정규화)
    예) vx=1, wz=0     → 직진
        vx=1, wz=0.3   → 왼쪽으로 완만하게 휘며 전진
        vx=0, wz=1     → 제자리 좌회전
기울인 양만큼 보폭과 걸음 속도가 함께 줄어들어 미세 조작이 가능합니다.

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

# 기존 버튼/명령 호환: 방향 이름 → (vx, wz)
DIRECTIONS: dict[str, tuple[float, float]] = {
    "forward": (1.0, 0.0),
    "backward": (-1.0, 0.0),
    "left": (0.0, 1.0),     # 제자리 좌회전
    "right": (0.0, -1.0),   # 제자리 우회전
}


@dataclass
class GaitParams:
    step_amplitude: float = 18.0   # 최대 hip 스윙 진폭(deg)
    lift_height: float = 25.0      # 다리 드는 높이(deg)
    lift_sign: int = 1             # 다리가 '위'로 가는 논리 방향 (+1/-1)
    period_fast: float = 0.8       # 최대 입력일 때 한 주기 시간(s)
    period_slow: float = 1.4
    min_cadence: float = 0.5       # 입력이 아주 작을 때 걸음 속도 비율 (0~1)
    deadzone: float = 0.08         # 이보다 작은 입력은 정지로 간주
    slew_rate: float = 3.0         # 보폭 계수 변화 속도(1/s) — 급변 시 다리 튐 방지
    rate_hz: float = 50.0


def side_coefficients(vx: float, wz: float) -> tuple[float, float]:
    """(vx, wz) → (왼쪽 보폭 계수, 오른쪽 보폭 계수), 각 -1~1."""
    left, right = vx - wz, vx + wz
    peak = max(1.0, abs(left), abs(right))
    return left / peak, right / peak


class GaitEngine:
    def __init__(self, servos: ServoController, params: GaitParams | None = None) -> None:
        self.servos = servos
        self.params = params or GaitParams()
        self.fast = False
        self._target = (0.0, 0.0)       # 요청된 (vx, wz)
        self._coef = [0.0, 0.0]         # 실제 적용 중인 (왼쪽, 오른쪽) 보폭 계수
        self._phase = 0.0
        self._walking = False
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ 외부 API
    def drive(self, vx: float, wz: float) -> None:
        vx = max(-1.0, min(1.0, float(vx)))
        wz = max(-1.0, min(1.0, float(wz)))
        if math.hypot(vx, wz) < self.params.deadzone:
            vx = wz = 0.0
        with self._lock:
            self._target = (vx, wz)

    def move(self, direction: str) -> None:
        if direction not in DIRECTIONS:
            raise ValueError(f"알 수 없는 방향: {direction}")
        self.drive(*DIRECTIONS[direction])

    def stop(self) -> None:
        self.drive(0.0, 0.0)

    def stand(self) -> None:
        """모든 다리를 중립 자세로."""
        with self._lock:
            self._target = (0.0, 0.0)
            self._coef = [0.0, 0.0]
            self._walking = False
            self._phase = 0.0
        pose = {}
        for leg in LEGS:
            pose[leg.hip] = 90.0
            pose[leg.lift] = 90.0
        self.servos.set_many(pose, speed=120)

    @property
    def target(self) -> tuple[float, float]:
        return self._target

    @property
    def direction(self) -> str | None:
        """대표 방향 이름 (상태 표시용). 정지면 None."""
        vx, wz = self._target
        if vx == 0 and wz == 0:
            return None
        if abs(vx) >= abs(wz) * 2:
            return "forward" if vx > 0 else "backward"
        if abs(wz) >= abs(vx) * 2:
            return "left" if wz > 0 else "right"
        return ("forward" if vx > 0 else "backward") + ("-left" if wz > 0 else "-right")

    @property
    def period(self) -> float:
        return self.params.period_fast if self.fast else self.params.period_slow

    def snapshot(self) -> dict:
        vx, wz = self._target
        return {
            "vx": round(vx, 2), "wz": round(wz, 2),
            "left": round(self._coef[0], 2), "right": round(self._coef[1], 2),
            "direction": self.direction,
        }

    def start(self) -> None:
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="gait", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2)

    # ------------------------------------------------------------------ 내부
    def _leg_pose(self, phase: float, coef: float) -> tuple[float, float]:
        """phase(0~1), 보폭 계수 → (hip 논리각, lift 논리각)."""
        p = self.params
        if phase < 0.5:   # swing: 들어서 뒤→앞
            t = phase / 0.5
            swing = -1.0 + 2.0 * t
            lift = math.sin(math.pi * t) * p.lift_height
        else:             # stance: 딛고 앞→뒤 (몸이 앞으로 나아감)
            t = (phase - 0.5) / 0.5
            swing = 1.0 - 2.0 * t
            lift = 0.0
        return 90.0 + swing * p.step_amplitude * coef, 90.0 + lift * p.lift_sign

    def _step_coefficients(self, dt: float) -> tuple[float, float]:
        with self._lock:
            goal = side_coefficients(*self._target)
            max_step = self.params.slew_rate * dt
            for i in (0, 1):
                diff = goal[i] - self._coef[i]
                self._coef[i] += max(-max_step, min(max_step, diff))
            return self._coef[0], self._coef[1]

    def _loop(self) -> None:
        dt = 1.0 / self.params.rate_hz
        while self._running.is_set():
            t0 = time.monotonic()
            try:
                self._tick(dt)
            except Exception:
                log.exception("보행 루프 오류")
            time.sleep(max(0.0, dt - (time.monotonic() - t0)))

    def _tick(self, dt: float) -> None:
        left, right = self._step_coefficients(dt)
        magnitude = max(abs(left), abs(right))
        stopped = self._target == (0.0, 0.0)

        if magnitude < 0.02:
            if self._walking and stopped:
                self.stand()          # 완전히 멈추면 중립 자세로 복귀
            return

        self._walking = True
        # 입력이 작을수록 보폭(계수)과 걸음 속도가 함께 줄어듦
        p = self.params
        cadence = p.min_cadence + (1.0 - p.min_cadence) * magnitude
        self._phase = (self._phase + dt * cadence / self.period) % 1.0

        pose: dict[int, float] = {}
        for leg in LEGS:
            leg_phase = self._phase if leg.name in TRIPOD_A else (self._phase + 0.5) % 1.0
            coef = left if leg.side == "L" else right
            hip, lift = self._leg_pose(leg_phase, coef)
            pose[leg.hip] = hip
            pose[leg.lift] = lift
        self.servos.set_many(pose, speed=None)
