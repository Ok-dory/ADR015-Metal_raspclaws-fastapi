"""로봇의 물리적 서보 배치 정의 (프로젝트 지침에서 확정한 채널 맵).

     왼쪽  다리: 안쪽(hip) CH0, 2, 4 / 바깥쪽(lift) CH1, 3, 5
     오른쪽 다리: 안쪽(hip) CH6, 8, 10 / 바깥쪽(lift) CH7, 9, 11
     머리/카메라: CH12 좌우 회전(pan), CH13 상하 틸트(tilt)
     초음파 센서: CH14 센서 회전

앞/중간/뒤 순서와 회전 부호는 Adeept 원본 Move.py 의 보행 코드에서 가져왔습니다.
  - 앞다리: CH0/1, CH10/11   중간: CH2/3, CH8/9   뒷다리: CH4/5, CH6/7
  - CH6~11 쪽은 CH0~5 쪽과 서보가 대칭 장착되어 회전 부호가 반대
  (원본 Move.py 주석의 left_I~III = CH0~5, right_I~III = CH6~11 과 일치)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServoSpec:
    channel: int
    name: str
    group: str                      # "leg" | "head" | "aux"
    min_angle: float = 0.0          # 물리 각도 안전 한계
    max_angle: float = 180.0
    inverted: bool = False          # 논리 +방향과 물리 회전 방향이 반대인 경우
    default_speed: float | None = None  # deg/s, None = 즉시 이동
    # 정지 상태로 일정 시간 지나면 PWM 출력을 끊어 헌팅(부르르 떨림)을 원천 차단
    release_when_idle: bool = False
    idle_release_s: float = 0.8


@dataclass(frozen=True)
class LegSpec:
    name: str
    side: str      # "L" | "R"
    hip: int       # 앞뒤 스윙 서보 채널
    lift: int      # 상하 서보 채널


LEGS: tuple[LegSpec, ...] = (
    LegSpec("LF", "L", hip=0, lift=1),
    LegSpec("LM", "L", hip=2, lift=3),
    LegSpec("LR", "L", hip=4, lift=5),
    LegSpec("RF", "R", hip=10, lift=11),
    LegSpec("RM", "R", hip=8, lift=9),
    LegSpec("RR", "R", hip=6, lift=7),
)

# 트라이포드 보행 그룹 (원본 Move.py 와 동일: {0,4,8} / {10,6,2})
TRIPOD_A = ("LF", "LR", "RM")
TRIPOD_B = ("RF", "RR", "LM")

# 머리 서보 역할 매핑 (식별 후 필요하면 바꿔 주세요)
HEAD_PAN = 12    # 좌우 회전 (lookleft / lookright)
HEAD_TILT = 13   # 상하 틸트 (up / down)
ULTRASONIC = 14  # 초음파 센서 회전


def _leg_servos() -> list[ServoSpec]:
    specs: list[ServoSpec] = []
    for leg in LEGS:
        # CH6~11 은 대칭 장착 → 논리 +방향(앞/위)이 물리적으로 반대
        mirrored = leg.hip >= 6
        specs.append(ServoSpec(leg.hip, f"{leg.name}_hip", "leg", inverted=mirrored))
        specs.append(ServoSpec(leg.lift, f"{leg.name}_lift", "leg", inverted=mirrored))
    return specs


SERVOS: tuple[ServoSpec, ...] = tuple(
    sorted(
        _leg_servos()
        + [
            # 머리 서보: 부드러운 이동 + 유휴 시 PWM 해제로 헌팅 억제
            # 원본 Move.py: up = CH13 각도 감소 → 논리 +(위)와 물리 방향이 반대
            ServoSpec(HEAD_TILT, "head_tilt", "head", min_angle=30, max_angle=150,
                      inverted=True, default_speed=90, release_when_idle=True),
            ServoSpec(HEAD_PAN, "head_pan", "head", min_angle=20, max_angle=160,
                      default_speed=120, release_when_idle=True),
            ServoSpec(ULTRASONIC, "ultrasonic", "head", min_angle=30, max_angle=150,
                      default_speed=90, release_when_idle=True),
            ServoSpec(15, "spare_15", "aux"),
        ],
        key=lambda s: s.channel,
    )
)

SERVO_BY_CHANNEL = {s.channel: s for s in SERVOS}
LEG_BY_NAME = {leg.name: leg for leg in LEGS}
