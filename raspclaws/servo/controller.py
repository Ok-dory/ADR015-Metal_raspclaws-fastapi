"""서보 컨트롤러.

- API/보행 코드는 '목표 각도'만 설정하고, 실제 I2C 출력은 전용 스레드가 일정 주기로 처리
- 각도 체계
    논리 각도(logical): 0~180, 90 = 캘리브레이션된 중립 자세
    물리 각도(physical): center + (logical - 90) * (반전이면 -1), 안전 한계로 클램프
- 떨림(Jitter/Hunting) 완화 기능
    1) 속도 제한 스무딩: 급격한 목표 변화로 인한 오버슈트 감소
    2) 쓰기 데드밴드: 의미 없는 미세 펄스 변화는 버스에 쓰지 않음
    3) 유휴 시 PWM 해제(release_when_idle): 정지 상태에서 토크를 끊어 헌팅 원천 차단
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

from ..config import Settings
from ..hardware import PWMBackend
from ..robot_layout import ServoSpec
from .calibration import DEFAULT_CENTER, CalibrationStore

log = logging.getLogger(__name__)

_DEFAULT = object()  # "스펙의 기본 속도 사용" 표시용


@dataclass
class _ServoState:
    spec: ServoSpec
    center: float = DEFAULT_CENTER
    target: float = 90.0      # 논리 각도
    current: float = 90.0     # 논리 각도 (스무딩 중간값)
    speed: float | None = None
    engaged: bool = False     # PWM 출력 중인지
    last_pulse: float | None = None
    last_motion: float = field(default_factory=time.monotonic)


class ServoController:
    def __init__(self, backend: PWMBackend, specs: Iterable[ServoSpec],
                 settings: Settings, calibration: CalibrationStore) -> None:
        self.backend = backend
        self.settings = settings
        self.calibration = calibration
        self._lock = threading.RLock()
        self._states: dict[int, _ServoState] = {s.channel: _ServoState(spec=s) for s in specs}
        for ch, center in calibration.load().items():
            if ch in self._states:
                self._states[ch].center = center
        self._thread: threading.Thread | None = None
        self._running = threading.Event()

    # ------------------------------------------------------------------ 수명주기
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="servo-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2)
        self.backend.close()

    # ------------------------------------------------------------------ 변환
    def _physical(self, st: _ServoState, logical: float) -> float:
        sign = -1.0 if st.spec.inverted else 1.0
        phys = st.center + (logical - 90.0) * sign
        return max(st.spec.min_angle, min(st.spec.max_angle, phys))

    def _pulse(self, phys: float) -> float:
        s = self.settings
        return s.min_pulse_us + (s.max_pulse_us - s.min_pulse_us) * phys / s.actuation_range

    def _state(self, channel: int) -> _ServoState:
        try:
            return self._states[channel]
        except KeyError:
            raise KeyError(f"정의되지 않은 서보 채널: {channel}") from None

    # ------------------------------------------------------------------ 명령
    def set_angle(self, channel: int, angle: float, speed=_DEFAULT) -> None:
        """논리 각도로 이동. speed: deg/s, None=즉시, 생략=스펙 기본값."""
        with self._lock:
            st = self._state(channel)
            st.target = max(0.0, min(180.0, float(angle)))
            st.speed = st.spec.default_speed if speed is _DEFAULT else speed
            if not st.engaged:
                # 해제 상태였다면 실제 위치를 모르므로 현재값=목표로 두고 바로 출력
                st.current = st.target if st.speed is None else st.current
                st.engaged = True
            st.last_motion = time.monotonic()

    def set_many(self, angles: dict[int, float], speed=None) -> None:
        with self._lock:
            for ch, a in angles.items():
                self.set_angle(ch, a, speed)

    def logical_limits(self, channel: int) -> tuple[float, float]:
        """물리 안전 한계에 대응하는 논리 각도 범위 (연속 이동 시 끝점으로 사용)."""
        with self._lock:
            st = self._state(channel)
            sign = -1.0 if st.spec.inverted else 1.0
            a = 90.0 + (st.spec.min_angle - st.center) * sign
            b = 90.0 + (st.spec.max_angle - st.center) * sign
            lo, hi = sorted((a, b))
            return max(0.0, lo), min(180.0, hi)

    def get_angle(self, channel: int) -> float:
        with self._lock:
            return self._state(channel).current

    def hold(self, channel: int) -> None:
        """현재 위치에서 정지 (머리 연속 이동 종료 등)."""
        with self._lock:
            st = self._state(channel)
            st.target = st.current
            st.last_motion = time.monotonic()

    def release(self, channel: int) -> None:
        with self._lock:
            st = self._state(channel)
            st.engaged = False
            st.last_pulse = None
            self.backend.write_pulse(channel, None)

    def release_all(self) -> None:
        with self._lock:
            for ch in self._states:
                self.release(ch)

    # ------------------------------------------------------------------ 캘리브레이션
    def nudge_center(self, channel: int, delta: float) -> float:
        with self._lock:
            st = self._state(channel)
            st.center = max(st.spec.min_angle, min(st.spec.max_angle, st.center + delta))
            self.set_angle(channel, 90.0, speed=None)
            return st.center

    def set_center(self, channel: int, value: float) -> float:
        with self._lock:
            st = self._state(channel)
            st.center = max(st.spec.min_angle, min(st.spec.max_angle, float(value)))
            self.set_angle(channel, 90.0, speed=None)
            return st.center

    def reset_centers(self) -> None:
        with self._lock:
            for ch, st in self._states.items():
                st.center = DEFAULT_CENTER
                if st.engaged:
                    self.set_angle(ch, 90.0, speed=None)

    def save_calibration(self) -> None:
        with self._lock:
            centers = {ch: st.center for ch, st in self._states.items()}
        self.calibration.save(centers)

    def identify(self, channel: int, amplitude: float = 15.0) -> None:
        """해당 채널 서보를 좌우로 흔들어 물리 위치를 확인 (비동기 실행)."""
        self._state(channel)

        def _wiggle() -> None:
            base = self.get_angle(channel)
            for a in (base + amplitude, base - amplitude, base + amplitude, base):
                self.set_angle(channel, a, speed=120)
                time.sleep(0.35)

        threading.Thread(target=_wiggle, name=f"identify-{channel}", daemon=True).start()

    # ------------------------------------------------------------------ 상태
    def snapshot(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "channel": ch,
                    "name": st.spec.name,
                    "group": st.spec.group,
                    "angle": round(st.current, 1),
                    "target": round(st.target, 1),
                    "center": round(st.center, 1),
                    "physical": round(self._physical(st, st.current), 1),
                    "inverted": st.spec.inverted,
                    "engaged": st.engaged,
                    "release_when_idle": st.spec.release_when_idle,
                }
                for ch, st in sorted(self._states.items())
            ]

    # ------------------------------------------------------------------ 제어 루프
    def _loop(self) -> None:
        period = 1.0 / self.settings.control_hz
        last = time.monotonic()
        while self._running.is_set():
            now = time.monotonic()
            dt = now - last
            last = now
            try:
                self._tick(now, dt)
            except Exception:
                log.exception("서보 제어 루프 오류")
            time.sleep(max(0.0, period - (time.monotonic() - now)))

    def _tick(self, now: float, dt: float) -> None:
        deadband = self.settings.write_deadband_us
        with self._lock:
            for ch, st in self._states.items():
                if not st.engaged:
                    continue
                # 1) 스무딩
                if st.current != st.target:
                    if st.speed is None:
                        st.current = st.target
                    else:
                        step = st.speed * dt
                        diff = st.target - st.current
                        st.current = st.target if abs(diff) <= step else st.current + step * (1 if diff > 0 else -1)
                    st.last_motion = now

                at_target = st.current == st.target

                # 2) 유휴 해제
                if (st.spec.release_when_idle and at_target
                        and now - st.last_motion > st.spec.idle_release_s):
                    self.backend.write_pulse(ch, None)
                    st.engaged = False
                    st.last_pulse = None
                    continue

                # 3) 데드밴드 적용 출력
                pulse = round(self._pulse(self._physical(st, st.current)), 1)
                if st.last_pulse is None:
                    changed = True
                else:
                    gap = abs(pulse - st.last_pulse)
                    changed = gap >= deadband or (at_target and gap > 0)
                if changed:
                    self.backend.write_pulse(ch, pulse)
                    st.last_pulse = pulse
