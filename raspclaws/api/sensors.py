"""카메라 스트림 및 초음파 API."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from ..robot import Robot
from .deps import get_robot

router = APIRouter(tags=["sensors"])
BOUNDARY = "frame"


# ------------------------------------------------------------ 카메라
class CameraSettingsIn(BaseModel):
    hflip: bool | None = None
    vflip: bool | None = None
    quality: int | None = Field(None, ge=20, le=95)


async def _mjpeg(request: Request, robot: Robot):
    last = -1
    while not await request.is_disconnected():
        last, frame = await asyncio.to_thread(robot.camera.wait_frame, last, 2.0)
        if frame is None:
            await asyncio.sleep(0.5)
            continue
        yield (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
               f"Content-Length: {len(frame)}\r\n\r\n").encode() + frame + b"\r\n"


@router.get("/video_feed", include_in_schema=False)
@router.get("/api/camera/stream")
async def stream(request: Request, robot: Robot = Depends(get_robot)):
    if not robot.camera.enabled:
        raise HTTPException(503, "카메라가 비활성화되어 있습니다")
    return StreamingResponse(_mjpeg(request, robot),
                             media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
                             headers={"Cache-Control": "no-store"})


@router.get("/api/camera/snapshot")
async def snapshot(robot: Robot = Depends(get_robot)):
    frame = await asyncio.to_thread(robot.camera.snapshot)
    if frame is None:
        raise HTTPException(503, "카메라 프레임을 가져올 수 없습니다")
    return Response(frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/api/camera")
def camera_info(robot: Robot = Depends(get_robot)):
    return robot.camera.snapshot_info()


@router.put("/api/camera")
def camera_settings(body: CameraSettingsIn, robot: Robot = Depends(get_robot)):
    cam = robot.camera
    if body.hflip is not None:
        cam.hflip = body.hflip
    if body.vflip is not None:
        cam.vflip = body.vflip
    if body.quality is not None:
        cam.quality = body.quality
    return cam.snapshot_info()


# ------------------------------------------------------------ 초음파
class SonarIn(BaseModel):
    angle: float = Field(..., ge=0, le=180)


@router.get("/api/sonar")
def sonar(robot: Robot = Depends(get_robot)):
    return robot.sonar.snapshot()


@router.put("/api/sonar")
def sonar_point(body: SonarIn, robot: Robot = Depends(get_robot)):
    robot.sonar.point(body.angle)
    return robot.sonar.snapshot()


@router.post("/api/sonar/scan")
def sonar_scan(robot: Robot = Depends(get_robot)):
    return {"started": robot.sonar.scan()}
