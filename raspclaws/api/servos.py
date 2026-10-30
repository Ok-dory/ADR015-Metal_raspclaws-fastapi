"""서보 개별 제어 및 캘리브레이션 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends
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


@router.put("/servos/{channel}")
def set_servo(body: AngleIn, channel: int = Depends(check_channel),
              robot: Robot = Depends(get_robot)):
    robot.servos.set_angle(channel, body.angle, speed=body.speed)
    return {"channel": channel, "target": body.angle}


@router.post("/servos/{channel}/release")
def release_servo(channel: int = Depends(check_channel), robot: Robot = Depends(get_robot)):
    robot.servos.release(channel)
    return {"channel": channel, "engaged": False}


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
