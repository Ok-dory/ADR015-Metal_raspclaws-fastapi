"""로봇 전체를 묶는 퍼사드(Facade).

웹 서버, 비전 모듈, 자율 동작 등 어떤 기능이든
이 Robot 객체 하나만 받아서 쓰면 되도록 설계했습니다.
"""
from __future__ import annotations

import logging
import time

from . import system_info
from .config import Settings
from .hardware import create_backend
from .motion import GaitEngine, HeadController, SonarController
from .peripherals import BatteryMonitor, CameraService, OledDisplay, UltrasonicSensor
from .peripherals.oled import local_ip
from .robot_layout import SERVOS, ULTRASONIC
from .servo import CalibrationStore, ServoController

log = logging.getLogger(__name__)


class Robot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        backend = create_backend(settings.backend, settings.i2c_address, settings.pwm_frequency)
        self.backend_name = backend.name
        hw = backend.name != "mock"

        self.servos = ServoController(backend, SERVOS, settings,
                                      CalibrationStore(settings.calibration_file))
        self.gait = GaitEngine(self.servos)
        self.head = HeadController(self.servos)

        self.battery = BatteryMonitor(enabled=settings.battery and hw)
        sensor = UltrasonicSensor(enabled=settings.ultrasonic and hw,
                                  mock_angle=lambda: self.servos.get_angle(ULTRASONIC))
        self.sonar = SonarController(self.servos, sensor)
        self.camera = CameraService(enabled=settings.camera,
                                    width=settings.camera_width, height=settings.camera_height)
        self.oled = OledDisplay(self._oled_lines, enabled=settings.oled and hw)

    # ------------------------------------------------------------ 수명주기
    def start(self, stand: bool = True) -> None:
        self.servos.start()
        self.gait.start()
        self.battery.start()
        self.sonar.start()
        self.oled.start()
        if stand:
            self.gait.stand()
            self.head.center()
            self.sonar.point(90.0)
        log.info("Robot started (backend=%s)", self.backend_name)

    def shutdown(self) -> None:
        self.oled.stop(farewell=["RaspClaws", "", "SERVER STOPPED"])
        self.sonar.stop()
        self.sonar.sensor.close()
        self.battery.stop()
        self.camera.close()
        self.gait.shutdown()
        self.servos.stop()
        log.info("Robot stopped")

    # ------------------------------------------------------------ 상태
    def _oled_lines(self) -> list[str]:
        bat = self.battery.snapshot()
        temp = system_info.cpu_temperature()
        bat_txt = f"BAT {bat['voltage']:.1f}V {bat['percent']}%" if bat["voltage"] else "BAT --"
        if bat["low"]:
            bat_txt += " LOW!"
        move = self.gait.direction or "stop"
        return [
            f"RaspClaws  {time.strftime('%H:%M')}",
            f"IP {local_ip()}",
            f"WEB :{self.settings.port}  OK",
            f"MOVE {move} / {'FAST' if self.gait.fast else 'SLOW'}",
            f"{bat_txt}  {temp:.0f}C" if temp is not None else bat_txt,
        ]

    def status(self) -> dict:
        return {
            "backend": self.backend_name,
            "moving": self.gait.direction,
            "speed_mode": "fast" if self.gait.fast else "slow",
        }

    def full_state(self) -> dict:
        return {
            **self.status(),
            **system_info.snapshot(),
            "battery": self.battery.snapshot(),
            "head": self.head.snapshot(),
            "sonar": self.sonar.snapshot(),
            "camera": self.camera.snapshot_info(),
            "oled": {"available": self.oled.available, "lines": self.oled.lines},
            "servos": self.servos.snapshot(),
        }
