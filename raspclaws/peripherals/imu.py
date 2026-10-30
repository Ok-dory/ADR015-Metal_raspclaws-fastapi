"""MPU6050 자세 센서 (Robot HAT V3.3 의 I2C 0x68, 원본 Move.py 와 동일).

- 100Hz 로 가속도·자이로를 읽어 상보 필터로 roll/pitch(도)를 계산
- 센서 장착 방향이 개체마다 다를 수 있으므로, 서 있는 자세를 '기준 자세'로
  잡아 두고 그 기준에서 얼마나 기울었는지(tilt)를 걸림 감지에 사용
- 하드웨어가 없으면 보행 흔들림을 흉내 내는 Mock 으로 동작하며,
  inject_snag() 로 '다리 걸림' 상황을 재현할 수 있음 (테스트용)
"""
from __future__ import annotations

import logging
import math
import random
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

MPU_ADDRESS = 0x68
ACCEL_LSB = 16384.0   # ±2g
GYRO_LSB = 131.0      # ±250 °/s
ALPHA = 0.96          # 상보 필터 (자이로 비중)


class _MPU6050:
    def __init__(self) -> None:
        try:
            from smbus2 import SMBus
        except ImportError:
            from smbus import SMBus
        self._bus = SMBus(1)
        self._bus.write_byte_data(MPU_ADDRESS, 0x6B, 0x00)   # sleep 해제
        self._bus.write_byte_data(MPU_ADDRESS, 0x1A, 0x03)   # DLPF ~44Hz (진동 노이즈 감소)
        self._bus.write_byte_data(MPU_ADDRESS, 0x1B, 0x00)   # 자이로 ±250°/s
        self._bus.write_byte_data(MPU_ADDRESS, 0x1C, 0x00)   # 가속도 ±2g

    def read(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        raw = self._bus.read_i2c_block_data(MPU_ADDRESS, 0x3B, 14)

        def s16(i: int) -> int:
            v = (raw[i] << 8) | raw[i + 1]
            return v - 65536 if v & 0x8000 else v

        accel = (s16(0) / ACCEL_LSB, s16(2) / ACCEL_LSB, s16(4) / ACCEL_LSB)
        gyro = (s16(8) / GYRO_LSB, s16(10) / GYRO_LSB, s16(12) / GYRO_LSB)
        return accel, gyro


class ImuSensor:
    def __init__(self, enabled: bool = True,
                 mock_motion: Callable[[], tuple[float, float]] | None = None) -> None:
        """mock_motion: Mock 일 때 (보행 위상 0~1, 보행 세기 0~1) 를 돌려주는 함수."""
        self._dev: _MPU6050 | None = None
        self._mock_motion = mock_motion
        self._mock_snag_until = 0.0
        self._mock_snag_dir = 1.0
        if enabled:
            try:
                self._dev = _MPU6050()
                self._dev.read()
                log.info("MPU6050 연결됨")
            except Exception as exc:
                self._dev = None
                log.warning("MPU6050 사용 불가 → mock: %s", exc)

        self.roll = 0.0          # 도
        self.pitch = 0.0
        self.gyro = (0.0, 0.0, 0.0)
        self.accel = (0.0, 0.0, 1.0)
        self.ref_roll = 0.0      # 기준 자세
        self.ref_pitch = 0.0
        self.ready = False
        self._lock = threading.Lock()
        self._running = threading.Event()

    @property
    def is_mock(self) -> bool:
        return self._dev is None

    # ------------------------------------------------------------ 측정
    def _read(self, dt: float):
        if self._dev is not None:
            return self._dev.read()
        # Mock: 보행 위상에 맞춰 살짝 흔들리고, 모의 걸림 동안 크게 기울어짐
        phase, amount = self._mock_motion() if self._mock_motion else (0.0, 0.0)
        sway_r = 2.0 * amount * math.sin(2 * math.pi * phase)
        sway_p = 1.2 * amount * math.cos(2 * math.pi * phase)
        if time.monotonic() < self._mock_snag_until:
            sway_r += 16.0 * self._mock_snag_dir
            sway_p += 6.0
        r, p = math.radians(sway_r), math.radians(sway_p)
        noise = lambda s: random.gauss(0, s)  # noqa: E731
        accel = (-math.sin(p) + noise(0.01), math.sin(r) * math.cos(p) + noise(0.01),
                 math.cos(r) * math.cos(p) + noise(0.01))
        gyro = ((sway_r - self.roll) / max(dt, 1e-3) + noise(0.5),
                (sway_p - self.pitch) / max(dt, 1e-3) + noise(0.5), noise(0.5))
        return accel, gyro

    def _loop(self) -> None:
        dt = 0.01
        last = time.monotonic()
        while self._running.is_set():
            now = time.monotonic()
            dt = max(1e-3, now - last)
            last = now
            try:
                (ax, ay, az), (gx, gy, gz) = self._read(dt)
                acc_roll = math.degrees(math.atan2(ay, az))
                acc_pitch = math.degrees(math.atan2(-ax, math.hypot(ay, az)))
                with self._lock:
                    if not self.ready:
                        self.roll, self.pitch = acc_roll, acc_pitch
                        self.ready = True
                    else:
                        self.roll = ALPHA * (self.roll + gx * dt) + (1 - ALPHA) * acc_roll
                        self.pitch = ALPHA * (self.pitch + gy * dt) + (1 - ALPHA) * acc_pitch
                    self.gyro = (gx, gy, gz)
                    self.accel = (ax, ay, az)
            except OSError as exc:
                log.debug("MPU6050 읽기 실패: %s", exc)
            time.sleep(max(0.0, 0.01 - (time.monotonic() - now)))

    def start(self) -> None:
        self._running.set()
        threading.Thread(target=self._loop, name="imu", daemon=True).start()

    def stop(self) -> None:
        self._running.clear()

    # ------------------------------------------------------------ 기준 자세
    def set_reference(self, samples: int = 30) -> tuple[float, float]:
        """현재(서 있는) 자세를 기준으로 저장. 약 0.3초 평균."""
        rs, ps = [], []
        for _ in range(samples):
            rs.append(self.roll)
            ps.append(self.pitch)
            time.sleep(0.01)
        self.ref_roll, self.ref_pitch = sum(rs) / len(rs), sum(ps) / len(ps)
        return self.ref_roll, self.ref_pitch

    @property
    def tilt(self) -> float:
        """기준 자세 대비 기울어진 정도(도)."""
        return math.hypot(self.roll - self.ref_roll, self.pitch - self.ref_pitch)

    @property
    def gyro_rate(self) -> float:
        """roll·pitch 축 회전 속도 크기(°/s). 보행 방향 전환(yaw)은 제외."""
        return math.hypot(self.gyro[0], self.gyro[1])

    def inject_snag(self, duration: float = 0.6) -> None:
        """(Mock 전용) 다리 걸림으로 몸통이 기울어지는 상황을 재현."""
        self._mock_snag_dir = random.choice((-1.0, 1.0))
        self._mock_snag_until = time.monotonic() + duration

    def snapshot(self) -> dict:
        return {
            "available": self.ready,
            "mock": self.is_mock,
            "roll": round(self.roll - self.ref_roll, 1),
            "pitch": round(self.pitch - self.ref_pitch, 1),
            "tilt": round(self.tilt, 1),
            "gyro": round(self.gyro_rate, 1),
        }
