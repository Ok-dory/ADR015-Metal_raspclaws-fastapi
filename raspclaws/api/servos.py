"""서보 개별 제어 및 캘리브레이션 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..robot import Robot
from .deps import check_channel, get_robot

router = APIRouter(tags=["servos"])


class AngleIn(BaseModel):
    angle: float = Field(..., ge=0, le=180, description="논리 각도 (90 = 중립)")
    speed: float | None = Field(None, gt=0, description="deg/s, 생략 시 즉시 이동")


class NudgeIn(BaseModel):
    delta: float = Field(..., ge=-30, le=30)


class CenterIn(BaseModel):
    center: float = Field(..., ge=0, le=180)


@router.get("/servos")
def list_servos(robot: Robot = Depends(get_robot)):
    return robot.servos.snapshot()


class SwapIn(BaseModel):
    a: int = Field(..., ge=0, le=15)
    b: int = Field(..., ge=0, le=15)


@router.get("/servos/swaps")
def get_swaps(robot: Robot = Depends(get_robot)):
    return {"swaps": robot.backend.swaps}


@router.put("/servos/swaps")
def set_swap(body: SwapIn, robot: Robot = Depends(get_robot)):
    """두 채널의 출력 포트를 맞바꿈 (예: CH2 서보를 CH15 포트에 꽂아 사용)."""
    try:
        robot.backend.set_swap(body.a, body.b)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"swaps": robot.backend.swaps}


@router.delete("/servos/swaps")
def clear_swaps(robot: Robot = Depends(get_robot)):
    robot.backend.clear()
    return {"swaps": []}


@router.put("/servos/{channel}")
def set_servo(body: AngleIn, channel: int = Depends(check_channel),
              robot: Robot = Depends(get_robot)):
    robot.servos.set_angle(channel, body.angle, speed=body.speed)
    return {"channel": channel, "target": body.angle}


@router.post("/servos/{channel}/release")
def release_servo(channel: int = Depends(check_channel), robot: Robot = Depends(get_robot)):
    robot.servos.release(channel)
    return {"channel": channel, "engaged": False}


class ExerciseIn(BaseModel):
    amplitude: float = Field(18.0, ge=2, le=40)
    period: float | None = Field(None, ge=0.3, le=3, description="생략 시 현재 보행 속도")
    duration: float = Field(5.0, ge=1, le=20)


@router.post("/servos/{channel}/exercise")
def exercise_servo(body: ExerciseIn | None = None, channel: int = Depends(check_channel),
                   robot: Robot = Depends(get_robot)):
    """보행과 같은 속도로 한 채널만 반복 왕복 (걸을 때만 이상한 서보 진단용)."""
    body = body or ExerciseIn()
    if robot.gait.direction is not None:
        raise HTTPException(409, "걷는 중에는 시험할 수 없습니다")
    period = body.period or robot.gait.period
    robot.servos.exercise(channel, body.amplitude, period, body.duration)
    return {"channel": channel, "amplitude": body.amplitude, "period": period}


@router.post("/servos/{channel}/identify")
def identify_servo(channel: int = Depends(check_channel), robot: Robot = Depends(get_robot)):
    robot.servos.identify(channel)
    return {"channel": channel}


# ------------------------------------------------------------ 캘리브레이션
@router.post("/calibration/{channel}/nudge")
def nudge(body: NudgeIn, channel: int = Depends(check_channel),
          robot: Robot = Depends(get_robot)):
    return {"channel": channel, "center": robot.servos.nudge_center(channel, body.delta)}


@router.put("/calibration/{channel}")
def set_center(body: CenterIn, channel: int = Depends(check_channel),
               robot: Robot = Depends(get_robot)):
    return {"channel": channel, "center": robot.servos.set_center(channel, body.center)}


@router.post("/calibration/save")
def save(robot: Robot = Depends(get_robot)):
    robot.servos.save_calibration()
    return {"saved": str(robot.settings.calibration_file)}


@router.post("/calibration/reset")
def reset(robot: Robot = Depends(get_robot)):
    robot.servos.reset_centers()
    return {"reset": True}
