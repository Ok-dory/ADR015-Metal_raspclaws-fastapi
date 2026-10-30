"""머리(카메라) 팬/틸트 제어.

- move/stop: 버튼·키보드용. 누르고 있는 동안 끝점 방향으로 일정 속도 이동
- velocity: 조이스틱용. -1~1 값으로 방향과 속도를 동시에 지정
- look: 절대 각도 지정 (영상 위 드래그 조준 등)
멈춘 뒤에는 release_when_idle 설정에 따라 PWM 이 해제되어 헌팅이 생기지 않습니다.
"""
from __future__ import annotations

from ..robot_layout import HEAD_PAN, HEAD_TILT
from ..servo import ServoController

AXES = {"pan": HEAD_PAN, "tilt": HEAD_TILT}
DEADZONE = 0.12


class HeadController:
    def __init__(self, servos: ServoController, speed: float = 60.0,
                 max_speed: float = 120.0) -> None:
        self.servos = servos
        self.speed = speed          # 버튼 이동 속도 (deg/s)
        self.max_speed = max_speed  # 조이스틱 최대 속도 (deg/s)

    def move(self, axis: str, direction: int, speed: float | None = None) -> None:
        ch = AXES[axis]
        lo, hi = self.servos.logical_limits(ch)
        self.servos.set_angle(ch, hi if direction > 0 else lo, speed=speed or self.speed)

    def stop(self, axis: str) -> None:
        self.servos.hold(AXES[axis])

    def velocity(self, pan: float, tilt: float) -> None:
        """pan: +왼쪽/-오른쪽, tilt: +위/-아래, 각 -1~1."""
        for axis, v in (("pan", pan), ("tilt", tilt)):
            v = max(-1.0, min(1.0, v))
            if abs(v) < DEADZONE:
                self.stop(axis)
            else:
                self.move(axis, 1 if v > 0 else -1, speed=self.max_speed * abs(v))

    def look(self, pan: float | None = None, tilt: float | None = None) -> None:
        for axis, val in (("pan", pan), ("tilt", tilt)):
            if val is None:
                continue
            ch = AXES[axis]
            lo, hi = self.servos.logical_limits(ch)
            self.servos.set_angle(ch, max(lo, min(hi, val)))

    def center(self) -> None:
        self.look(pan=90.0, tilt=90.0)

    def snapshot(self) -> dict:
        return {
            "pan": round(self.servos.get_angle(HEAD_PAN), 1),
            "tilt": round(self.servos.get_angle(HEAD_TILT), 1),
            "pan_limits": self.servos.logical_limits(HEAD_PAN),
            "tilt_limits": self.servos.logical_limits(HEAD_TILT),
        }
