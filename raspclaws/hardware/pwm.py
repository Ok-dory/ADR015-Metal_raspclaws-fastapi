"""PWM 출력 백엔드.

상위 계층은 '채널 + 펄스폭(µs)'만 알면 되도록 하드웨어를 추상화합니다.
기존 예제는 set_angle() 호출마다 adafruit_motor.servo.Servo 객체를 새로 만들었지만,
여기서는 duty_cycle 레지스터에 직접 값을 써서 오버헤드를 줄였습니다.

라즈베리파이에서는 PCA9685 를 찾지 못해도 '가짜(mock)'로 바꾸지 않고
ReconnectingBackend 가 몇 초마다 다시 연결을 시도합니다.
(배터리 스위치가 꺼져 있거나 전압이 낮아 서보 드라이버가 응답하지 않는 경우,
 웹 화면은 정상인데 로봇만 안 움직이는 혼란을 막기 위함)
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Protocol

log = logging.getLogger(__name__)


class PWMBackend(Protocol):
    name: str
    connected: bool
    generation: int   # 재연결될 때마다 증가 → 컨트롤러가 전체 출력을 다시 보냄

    def write_pulse(self, channel: int, pulse_us: float | None) -> None:
        """pulse_us=None 이면 해당 채널 출력 OFF (서보 토크 해제)."""

    def close(self) -> None: ...


def on_raspberry_pi() -> bool:
    try:
        return "raspberry pi" in Path("/proc/device-tree/model").read_text(errors="ignore").lower()
    except OSError:
        return False


# PCA9685 레지스터
_MODE1, _MODE2, _PRESCALE, _LED0_ON_L = 0x00, 0x01, 0xFE, 0x06
_RESTART, _AUTO_INC, _SLEEP = 0x80, 0x20, 0x10
_OSC_HZ = 25_000_000


class PCA9685Backend:
    """PCA9685 를 smbus2 로 직접 제어 (Adafruit Blinka 불필요).

    Blinka 는 import 시 GPIO 라이브러리(gpiod) 버전까지 검사해서, 서보와 무관한
    패키지 버전 문제로 서보 제어 전체가 막히는 일이 있었습니다. 필요한 레지스터는
    몇 개뿐이라 직접 다루는 편이 단순하고 안정적입니다.
    """

    name = "pca9685"
    connected = True
    generation = 0

    def __init__(self, address: int = 0x5F, frequency: int = 50, bus: int = 1,
                 smbus_factory: Callable[[int], object] | None = None) -> None:
        if smbus_factory is None:
            try:
                from smbus2 import SMBus as smbus_factory
            except ImportError:
                from smbus import SMBus as smbus_factory  # python3-smbus (apt)
        self._lock = threading.Lock()
        self._addr = address
        self._bus = smbus_factory(bus)
        try:
            self._bus.write_byte_data(address, _MODE1, 0x00)          # 리셋 (= Adafruit reset)
            prescale = int(_OSC_HZ / 4096.0 / frequency + 0.5) - 1     # Adafruit 와 같은 계산
            prescale = max(3, min(255, prescale))
            old = self._bus.read_byte_data(address, _MODE1)
            self._bus.write_byte_data(address, _MODE1, (old & 0x7F) | _SLEEP)
            self._bus.write_byte_data(address, _PRESCALE, prescale)
            self._bus.write_byte_data(address, _MODE1, old)
            time.sleep(0.005)
            self._bus.write_byte_data(address, _MODE1, old | _RESTART | _AUTO_INC)
        except Exception:
            self._bus.close()
            raise
        self.frequency = _OSC_HZ / 4096.0 / (prescale + 1)
        self._period_us = 1_000_000.0 / self.frequency
        log.info("PCA9685 @0x%02X, %.1f Hz (smbus 직접 제어)", address, self.frequency)

    def write_pulse(self, channel: int, pulse_us: float | None) -> None:
        if pulse_us is None:
            regs = [0, 0, 0, 0x10]                        # FULL OFF
        else:
            off = int(round(pulse_us / self._period_us * 4096))
            off = max(0, min(4095, off))
            regs = [0, 0, off & 0xFF, off >> 8]
        with self._lock:
            self._bus.write_i2c_block_data(self._addr, _LED0_ON_L + 4 * channel, regs)

    def close(self) -> None:
        with self._lock:
            try:
                self._bus.write_byte_data(self._addr, _MODE1, 0x00)   # Adafruit deinit 과 동일
            except OSError:
                pass
            finally:
                self._bus.close()


class AdafruitPCA9685Backend:
    """(예비) Adafruit 라이브러리 사용. RASPCLAWS_PCA_DRIVER=adafruit 일 때만."""

    name = "pca9685"
    connected = True
    generation = 0

    def __init__(self, address: int = 0x5F, frequency: int = 50) -> None:
        import board  # adafruit-blinka
        import busio
        from adafruit_pca9685 import PCA9685

        self._lock = threading.Lock()
        self._i2c = busio.I2C(board.SCL, board.SDA)
        try:
            self._pca = PCA9685(self._i2c, address=address)
            self._pca.frequency = frequency
        except Exception:
            self._i2c.deinit()
            raise
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


class ReconnectingBackend:
    """실제 드라이버를 감싸서, 연결이 안 되거나 끊기면 자동으로 다시 연결.

    연결되지 않은 동안의 출력은 버리고, 다시 연결되면 generation 을 올려
    서보 컨트롤러가 모든 서보의 현재 위치를 다시 보내도록 합니다.
    """

    def __init__(self, factory: Callable[[], PWMBackend], retry_interval: float = 3.0) -> None:
        self._factory = factory
        self.retry_interval = retry_interval
        self._dev: PWMBackend | None = None
        self._lock = threading.Lock()
        self._closed = False
        self.generation = 0
        self.error: str | None = None
        self.since = time.time()
        self._try_connect()
        if self._dev is None:
            threading.Thread(target=self._retry_loop, name="pwm-reconnect", daemon=True).start()

    @property
    def connected(self) -> bool:
        return self._dev is not None

    @property
    def name(self) -> str:
        return "pca9685" if self.connected else "disconnected"

    def _try_connect(self) -> bool:
        try:
            dev = self._factory()
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            if msg != self.error:
                log.error("서보 드라이버(PCA9685) 연결 실패 — %s초마다 다시 시도합니다: %s",
                          self.retry_interval, msg)
            self.error = msg
            return False
        with self._lock:
            self._dev = dev
            self.generation += 1
            self.error = None
            self.since = time.time()
        log.info("서보 드라이버(PCA9685) 연결됨")
        return True

    def _retry_loop(self) -> None:
        while not self._closed and self._dev is None:
            time.sleep(self.retry_interval)
            if not self._closed:
                self._try_connect()

    def _lost(self, exc: Exception) -> None:
        with self._lock:
            dev, self._dev = self._dev, None
            self.error = f"{type(exc).__name__}: {exc}"
            self.since = time.time()
        log.error("서보 드라이버 통신 끊김 — 다시 연결을 시도합니다: %s", exc)
        try:
            if dev:
                dev.close()
        except Exception:
            pass
        threading.Thread(target=self._retry_loop, name="pwm-reconnect", daemon=True).start()

    def write_pulse(self, channel: int, pulse_us: float | None) -> None:
        dev = self._dev
        if dev is None:
            return
        try:
            dev.write_pulse(channel, pulse_us)
        except OSError as exc:      # I2C 응답 없음 (전원 차단 등)
            self._lost(exc)

    def close(self) -> None:
        self._closed = True
        dev, self._dev = self._dev, None
        if dev:
            dev.close()

    def snapshot(self) -> dict:
        return {"connected": self.connected, "error": self.error, "since": self.since}


class MockBackend:
    """하드웨어 없이 PC에서 개발·테스트할 때 사용하는 가짜 백엔드."""

    name = "mock"
    connected = True
    generation = 0

    def __init__(self) -> None:
        self.outputs: dict[int, float | None] = {}
        self.write_count = 0

    def write_pulse(self, channel: int, pulse_us: float | None) -> None:
        self.outputs[channel] = pulse_us
        self.write_count += 1

    def close(self) -> None:
        self.outputs.clear()


def create_backend(kind: str, address: int, frequency: int, driver: str = "native") -> PWMBackend:
    """kind: mock | pca9685 | auto
    auto: 라즈베리파이면 PCA9685(연결될 때까지 재시도), 그 외(PC 개발)는 mock.
    driver: native(smbus 직접, 기본) | adafruit
    """
    kind = kind.lower()
    if kind == "mock":
        return MockBackend()
    cls = AdafruitPCA9685Backend if driver.lower() == "adafruit" else PCA9685Backend
    if kind == "auto" and not on_raspberry_pi():
        try:
            return cls(address, frequency)
        except Exception as exc:
            log.warning("라즈베리파이가 아니고 PCA9685 도 없어 mock 으로 실행합니다: %s", exc)
            return MockBackend()
    return ReconnectingBackend(lambda: cls(address, frequency))
