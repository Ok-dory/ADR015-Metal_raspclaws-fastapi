"""다리 걸림 감지 설정 · 기록 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..robot import Robot
from .deps import get_robot

router = APIRouter(prefix="/snag", tags=["snag"])


class SnagConfigIn(BaseModel):
    enabled: bool | None = None
    tilt_threshold: float | None = Field(None, ge=2, le=45)
    gyro_threshold: float | None = Field(None, ge=20, le=500)
    hold_time: float | None = Field(None, ge=0, le=2)
    min_stride: float | None = Field(None, ge=0, le=1)
    backoff_time: float | None = Field(None, ge=0.2, le=5)
    backoff_speed: float | None = Field(None, ge=0.1, le=1)
    stepover_time: float | None = Field(None, ge=0.5, le=10)
    lift_scale: float | None = Field(None, ge=1, le=2.2)
    max_retries: int | None = Field(None, ge=0, le=5)
    reset_time: float | None = Field(None, ge=0.5, le=30)


class RecordIn(BaseModel):
    label: str = Field("", max_length=30, description="파일 이름에 붙일 메모 (예: 평지, 걸림)")


@router.get("")
def snag_state(robot: Robot = Depends(get_robot)):
    return robot.snag.snapshot()


@router.put("")
def snag_config(body: SnagConfigIn, robot: Robot = Depends(get_robot)):
    robot.snag.update_config(**body.model_dump(exclude_none=True))
    return robot.snag.snapshot()


@router.post("/test")
def snag_test(robot: Robot = Depends(get_robot)):
    """걷는 중일 때 회복 동작(후진 → 넘어가기 걸음)을 시험 실행."""
    if not robot.snag.config.enabled:
        raise HTTPException(409, "걸림 감지가 꺼져 있습니다")
    if not robot.snag.trigger_test():
        raise HTTPException(409, "걷는 중일 때만 시험할 수 있습니다")
    return {"started": True}


@router.post("/calibrate")
def snag_calibrate(robot: Robot = Depends(get_robot)):
    """지금 서 있는 자세를 자세 센서의 기준(수평)으로 저장."""
    roll, pitch = robot.snag.calibrate()
    return {"ref_roll": round(roll, 2), "ref_pitch": round(pitch, 2)}


@router.post("/record/start")
def record_start(body: RecordIn, robot: Robot = Depends(get_robot)):
    return {"name": robot.snag.start_recording(body.label)}


@router.post("/record/stop")
def record_stop(robot: Robot = Depends(get_robot)):
    return {"name": robot.snag.stop_recording()}


@router.get("/logs")
def logs(robot: Robot = Depends(get_robot)):
    return robot.snag.list_logs()


@router.get("/logs/{name}")
def log_file(name: str, robot: Robot = Depends(get_robot)):
    path = robot.snag.log_path(name)
    if path is None:
        raise HTTPException(404, "기록 파일이 없습니다")
    return FileResponse(path, media_type="text/csv", filename=name)
