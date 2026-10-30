"""보행 및 머리 제어 API."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..robot import Robot
from .deps import get_robot

router = APIRouter(tags=["motion"])


class SpeedIn(BaseModel):
    mode: Literal["fast", "slow"]


class DriveIn(BaseModel):
    vx: float = Field(..., ge=-1, le=1, description="전진량 (+전진 / -후진)")
    wz: float = Field(0.0, ge=-1, le=1, description="회전량 (+좌회전 / -우회전)")


class LookIn(BaseModel):
    pan: float | None = Field(None, ge=0, le=180)
    tilt: float | None = Field(None, ge=0, le=180)


@router.post("/motion/{direction}")
def move(direction: Literal["forward", "backward", "left", "right", "stop"],
         robot: Robot = Depends(get_robot)):
    if direction == "stop":
        robot.gait.stop()
    else:
        robot.gait.move(direction)
    return robot.status()


@router.put("/motion/drive")
def drive(body: DriveIn, robot: Robot = Depends(get_robot)):
    """조이스틱처럼 전진량·회전량을 연속값으로 지정 (곡선 보행)."""
    robot.gait.drive(body.vx, body.wz)
    return robot.gait.snapshot()


@router.post("/stand")
def stand(robot: Robot = Depends(get_robot)):
    robot.gait.stand()
    robot.head.center()
    return robot.status()


@router.put("/motion/speed")
def set_speed(body: SpeedIn, robot: Robot = Depends(get_robot)):
    robot.gait.fast = body.mode == "fast"
    return robot.status()


@router.put("/head")
def look(body: LookIn, robot: Robot = Depends(get_robot)):
    robot.head.look(pan=body.pan, tilt=body.tilt)
    return {"pan": body.pan, "tilt": body.tilt}


@router.post("/head/center")
def head_center(robot: Robot = Depends(get_robot)):
    robot.head.center()
    return {"centered": True}
