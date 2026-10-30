"""PWM 출력 백엔드.

상위 계층은 '채널 + 펄스폭(µs)'만 알면 되도록 하드웨어를 추상화합니다.
기존 예제는 set_angle() 호출마다 adafruit_motor.servo.Servo 객체를 새로 만들었지만,
여기서는 duty_cycle 레지스터에 직접 값을 써서 오버헤드를 줄였습니다.
"""
from __future__ import annotations

import logging
import threading
from typing import Protocol

log = logging.getLogger(__name__)


class PWMBackend(Protocol):
    name: str

    def write_pulse(self, channel: int, pulse_us: float | None) -> None:
        """pulse_us=None 이면 해당 채널 출력 OFF (서보 토크 해제)."""

    def close(self) -> None: ...


class PCA9685Backend:
    name = "pca9685"

    def __init__(self, address: int = 0x5F, frequency: int = 50) -> None:
        import board  # adafruit-blinka
        import busio
        from adafruit_pca9685 import PCA9685

        self._lock = threading.Lock()
        self._i2c = busio.I2C(board.SCL, board.SDA)
        self._pca = PCA9685(self._i2c, address=address)
        self._pca.frequency = frequency
        # 프리스케일러 반올림으로 실제 주파수가 조금 다를 수 있어 읽어온 값을 사용
        self._period_us = 1_000_000.0 / self._pca.frequency
        log.info("PCA9685 @0x%02X, %.1f Hz", address, self._pca.frequency)

    def write_pulse(self, channel: int, pulse_us: float | None) -> None:
        if pulse_us is None:
            duty = 0
        else:
            duty = int(round(pulse_us / self._period_us * 0xFFFF))
            duty = max(0, min(0xFFFF, duty))
        with self._lock:
            self._pca.channels[channel].duty_cycle = duty

    def close(self) -> None:
        with self._lock:
            try:
                self._pca.deinit()  # 모든 출력 OFF
            finally:
                self._i2c.deinit()


class MockBackend:
    """하드웨어 없이 PC에서 개발·테스트할 때 사용하는 가짜 백엔드."""

    name = "mock"

    def __init__(self) -> None:
        self.outputs: dict[int, float | None] = {}
        self.write_count = 0

    def write_pulse(self, channel: int, pulse_us: float | None) -> None:
        self.outputs[channel] = pulse_us
        self.write_count += 1

    def close(self) -> None:
        self.outputs.clear()


def create_backend(kind: str, address: int, frequency: int) -> PWMBackend:
    kind = kind.lower()
    if kind == "mock":
        return MockBackend()
    try:
        return PCA9685Backend(address, frequency)
    except Exception as exc:  # ImportError, OSError(I2C 없음) 등
        if kind == "pca9685":
            raise
        log.warning("PCA9685 초기화 실패 → mock 백엔드로 실행합니다: %s", exc)
        return MockBackend()
