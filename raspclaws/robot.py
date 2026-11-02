"""로봇 전체를 묶는 퍼사드(Facade).

웹 서버, 비전 모듈, 자율 동작 등 어떤 기능이든
이 Robot 객체 하나만 받아서 쓰면 되도록 설계했습니다.
"""
from __future__ import annotations

import logging
import threading
import time

from . import system_info, version
from .config import Settings
from .hardware import create_backend
from .hardware.remap import ChannelRemap
from .motion import GaitEngine, HeadController, SnagGuard, SonarController
from .peripherals import BatteryMonitor, CameraService, ImuSensor, OledDisplay, UltrasonicSensor
from .peripherals.oled import local_ip
from .robot_layout import SERVOS, ULTRASONIC
from .servo import CalibrationStore, ServoController
from .sim import SimWorld

log = logging.getLogger(__name__)


class Robot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        backend = create_backend(settings.backend, settings.i2c_address, settings.pwm_frequency,
                                 settings.pca_driver)
        # 포트 바꾸기(채널 재배치)를 맨 바깥에 씌움 → 나머지 코드는 원래 채널 번호 사용
        backend = ChannelRemap(backend, settings.data_dir / "channel_map.json")
        self.backend = backend
        # 실제 로봇 여부: 서보 드라이버 연결과 무관하게 판단 (드라이버가 안 잡혀도
        # OLED·센서는 따로 동작하고, 드라이버는 연결될 때까지 재시도)
        hw = backend.name != "mock"

        self.servos = ServoController(backend, SERVOS, settings,
                                      CalibrationStore(settings.calibration_file))
        self.gait = GaitEngine(self.servos)
        self.head = HeadController(self.servos)

        self.battery = BatteryMonitor(enabled=settings.battery and hw)
        # 테스트 모드(서보 mock)에서는 가상 주행으로 초음파 거리를 흉내 냄
        self.sim = None if hw else SimWorld(self.gait)
        sensor = UltrasonicSensor(enabled=settings.ultrasonic and hw,
                                  mock_angle=lambda: self.servos.get_angle(ULTRASONIC),
                                  mock_front=self.sim.front_distance if self.sim else None)
        self.sonar = SonarController(self.servos, sensor)
        self.camera = CameraService(enabled=settings.camera,
                                    width=settings.camera_width, height=settings.camera_height)
        self.imu = ImuSensor(enabled=settings.imu and hw, mock_motion=self.gait.motion_info)
        self.snag = SnagGuard(self.gait, self.imu, settings.data_dir,
                              sonar=self.sonar, simulated=not hw)
        self.version = version.snapshot(settings.data_dir)   # 시작 시 한 번 읽음
        self._started = time.monotonic()
        self.oled = OledDisplay(self._oled_lines, enabled=settings.oled and hw)

    # ------------------------------------------------------------ 수명주기
    def start(self, stand: bool = True) -> None:
        self.servos.start()
        self.gait.start()
        self.battery.start()
        if self.sim:
            self.sim.start()
        self.sonar.start()
        self.imu.start()
        self.snag.start()
        self.oled.start()
        if stand:
            self.gait.stand()
            self.head.center()
            self.sonar.point(90.0)
            # 서기 자세가 안정된 뒤 그 자세를 자세 센서의 기준으로 저장
            threading.Timer(2.0, self.imu.set_reference).start()
        log.info("Robot started (backend=%s)", self.backend.name)

    def shutdown(self) -> None:
        self.oled.stop(farewell=["RaspClaws", "", "SERVER STOPPED"])
        self.snag.stop()
        if self.sim:
            self.sim.stop()
        self.imu.stop()
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
        snag_line = {"backoff": "SNAG! backing off", "stepover": "SNAG! step-over",
                     "blocked": "BLOCKED - stopped"}.get(self.snag.state)
        return [
            f"RaspClaws  {time.strftime('%H:%M')}",
            f"IP {local_ip()}",
            self._oled_status_line(),
            snag_line or f"MOVE {move} / {self.gait.speed_mode.upper()}",
            f"{bat_txt}  {temp:.0f}C" if temp is not None else bat_txt,
        ]

    def _oled_status_line(self) -> str:
        """서보 드라이버 미연결 경고 > 부팅 후 60초 업데이트 결과 > 서버 상태."""
        if not self.backend.connected:
            return "SERVO DRV: NO LINK!" if int(time.monotonic()) % 2 else "CHECK BATTERY SW"
        commit = self.version.get("commit") or "-"
        upd = self.version.get("update")
        if upd and time.monotonic() - self._started < 60:
            return f"{upd['oled']} {commit}"
        return f"WEB :{self.settings.port} v{commit}"

    def status(self) -> dict:
        return {
            "backend": self.backend.name,
            "servo_driver": {"connected": self.backend.connected,
                             "error": getattr(self.backend, "error", None),
                             "swaps": self.backend.swaps},
            "moving": self.gait.direction,
            "speed_mode": self.gait.speed_mode,
        }

    def full_state(self) -> dict:
        return {
            **self.status(),
            **system_info.snapshot(),
            "drive": self.gait.snapshot(),
            "version": self.version,
            "snag": self.snag.snapshot(),
            "battery": self.battery.snapshot(),
            "head": self.head.snapshot(),
            "sonar": self.sonar.snapshot(),
            "camera": self.camera.snapshot_info(),
            "oled": {"available": self.oled.available, "lines": self.oled.lines},
            "servos": self.servos.snapshot(),
        }
