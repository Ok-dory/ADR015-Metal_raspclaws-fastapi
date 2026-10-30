"""전역 설정.

환경변수(RASPCLAWS_*)로 덮어쓸 수 있습니다. 예)
    RASPCLAWS_BACKEND=mock python run.py      # PC에서 하드웨어 없이 개발
    RASPCLAWS_PORT=5001 python run.py
    RASPCLAWS_CAMERA=0 python run.py          # 카메라 끄기
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default):
    raw = os.environ.get(f"RASPCLAWS_{name}")
    if raw is None:
        return default
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(raw, 0)  # 0x5F 같은 16진수 표기 허용
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, Path):
        return Path(raw)
    return raw


@dataclass(frozen=True)
class Settings:
    # --- 웹 서버 ---
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env("PORT", 5000))

    # --- PWM 하드웨어 (Robot HAT V3.3 의 PCA9685) ---
    # "auto": PCA9685 초기화를 시도하고 실패하면 mock 으로 대체
    backend: str = field(default_factory=lambda: _env("BACKEND", "auto"))
    i2c_address: int = field(default_factory=lambda: _env("I2C_ADDRESS", 0x5F))
    pwm_frequency: int = field(default_factory=lambda: _env("PWM_FREQ", 50))
    min_pulse_us: float = field(default_factory=lambda: _env("MIN_PULSE_US", 500.0))
    max_pulse_us: float = field(default_factory=lambda: _env("MAX_PULSE_US", 2400.0))
    actuation_range: float = 180.0

    # --- 서보 제어 루프 ---
    control_hz: float = field(default_factory=lambda: _env("CONTROL_HZ", 50.0))
    # 펄스 변화량이 이 값(µs) 미만이면 I2C 쓰기를 생략 → 미세 떨림/버스 부하 감소
    write_deadband_us: float = field(default_factory=lambda: _env("DEADBAND_US", 4.0))

    # --- 주변장치 (False 로 끄기) ---
    camera: bool = field(default_factory=lambda: _env("CAMERA", True))
    camera_width: int = field(default_factory=lambda: _env("CAMERA_WIDTH", 640))
    camera_height: int = field(default_factory=lambda: _env("CAMERA_HEIGHT", 480))
    oled: bool = field(default_factory=lambda: _env("OLED", True))
    battery: bool = field(default_factory=lambda: _env("BATTERY", True))
    ultrasonic: bool = field(default_factory=lambda: _env("ULTRASONIC", True))

    # --- 데이터 ---
    data_dir: Path = field(default_factory=lambda: _env("DATA_DIR", PROJECT_ROOT / "data"))

    @property
    def calibration_file(self) -> Path:
        return self.data_dir / "servos_init.json"


settings = Settings()
