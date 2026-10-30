"""상단 OLED(SSD1306 128x64, I2C 0x3C) 상태 표시 (원본 OLED.py 대체).

표시 내용 (2초마다 갱신)
    RaspClaws  12:03
    IP 192.168.1.48
    WEB :5000  OK
    MOVE forward / FAST
    BAT 7.9V 79%  45C
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)


def local_ip() -> str:
    """기본 경로로 나가는 인터페이스의 IP (실제 패킷은 보내지 않음)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "no network"


class OledDisplay:
    def __init__(self, line_provider: Callable[[], list[str]], enabled: bool = True,
                 interval: float = 2.0) -> None:
        self._provider = line_provider
        self.interval = interval
        self._device = None
        self._canvas = None
        self.lines: list[str] = []
        self._running = threading.Event()
        if enabled:
            try:
                from luma.core.interface.serial import i2c
                from luma.core.render import canvas
                from luma.oled.device import ssd1306

                self._device = ssd1306(i2c(port=1, address=0x3C), rotate=0)
                self._canvas = canvas
                log.info("OLED 연결됨")
            except Exception as exc:
                log.warning("OLED 사용 불가: %s", exc)

    @property
    def available(self) -> bool:
        return self._device is not None

    def start(self) -> None:
        self._running.set()
        threading.Thread(target=self._loop, name="oled", daemon=True).start()

    def _loop(self) -> None:
        while self._running.is_set():
            try:
                self.lines = self._provider()[:5]
                self._draw(self.lines)
            except Exception as exc:
                log.debug("OLED 갱신 실패: %s", exc)
            time.sleep(self.interval)

    def _draw(self, lines: list[str]) -> None:
        if not self._device:
            return
        with self._canvas(self._device) as draw:
            for i, text in enumerate(lines):
                draw.text((0, i * 13), text, fill="white")

    def show_message(self, lines: list[str]) -> None:
        """즉시 표시 (종료 메시지 등)."""
        self.lines = lines
        try:
            self._draw(lines)
        except Exception:
            pass

    def stop(self, farewell: list[str] | None = None) -> None:
        self._running.clear()
        if farewell:
            self.show_message(farewell)
