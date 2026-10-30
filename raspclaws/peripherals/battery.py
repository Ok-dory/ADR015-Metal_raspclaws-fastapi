"""배터리 전압 측정 (Robot HAT V3.3 의 ADS7830 ADC, 원본 Voltage.py 기준).

ADS7830 @ I2C 0x48, 채널 0, 기준전압 5.2V, 분압비 1k/(3k+1k)
18650 2직렬: 만충 8.4V, 경고 6.0V
"""
from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import deque

log = logging.getLogger(__name__)

ADC_ADDRESS = 0x48
ADC_CHANNEL = 0
ADC_VREF = 5.2
DIVISION_RATIO = 1000 / (3000 + 1000)
FULL_VOLTAGE = 8.4
WARN_VOLTAGE = 6.0


class _ADS7830:
    def __init__(self) -> None:
        try:
            from smbus2 import SMBus
        except ImportError:
            from smbus import SMBus  # python3-smbus (apt)
        self._bus = SMBus(1)

    def read(self, chn: int) -> int:
        cmd = 0x84 | (((chn << 2 | chn >> 1) & 0x07) << 4)
        return self._bus.read_byte_data(ADC_ADDRESS, cmd)


class BatteryMonitor:
    def __init__(self, enabled: bool = True) -> None:
        self._adc = None
        self.voltage: float | None = None
        self._samples: deque[float] = deque(maxlen=10)
        self._running = threading.Event()
        if enabled:
            try:
                self._adc = _ADS7830()
                self._adc.read(ADC_CHANNEL)
                log.info("배터리 ADC(ADS7830) 연결됨")
            except Exception as exc:
                self._adc = None
                log.warning("배터리 ADC 사용 불가: %s", exc)

    @property
    def available(self) -> bool:
        return self._adc is not None

    def start(self) -> None:
        if not self._adc:
            return
        self._running.set()
        threading.Thread(target=self._loop, name="battery", daemon=True).start()

    def stop(self) -> None:
        self._running.clear()

    def _loop(self) -> None:
        while self._running.is_set():
            try:
                raw = self._adc.read(ADC_CHANNEL)
                self._samples.append(raw / 255.0 * ADC_VREF / DIVISION_RATIO)
                if len(self._samples) == self._samples.maxlen:
                    med = statistics.median(self._samples)
                    good = [v for v in self._samples if abs(v - med) < 1.0]
                    if good:
                        self.voltage = sum(good) / len(good)
                    self._samples.clear()
            except OSError as exc:
                log.debug("배터리 읽기 실패: %s", exc)
            time.sleep(0.1)

    @property
    def percent(self) -> int | None:
        if self.voltage is None:
            return None
        p = (self.voltage - WARN_VOLTAGE) / (FULL_VOLTAGE - WARN_VOLTAGE) * 100
        return int(max(0, min(100, p)))

    def snapshot(self) -> dict:
        return {
            "available": self.available,
            "voltage": round(self.voltage, 2) if self.voltage is not None else None,
            "percent": self.percent,
            "low": self.voltage is not None and self.voltage < WARN_VOLTAGE,
        }
