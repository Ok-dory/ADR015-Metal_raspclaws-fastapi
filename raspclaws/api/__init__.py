from fastapi import APIRouter

from . import motion, sensors, servos, snag, system, ws

api_router = APIRouter(prefix="/api")
api_router.include_router(servos.router)
api_router.include_router(motion.router)
api_router.include_router(system.router)
api_router.include_router(snag.router)

# 카메라 스트림은 원본 호환 경로(/video_feed)도 제공하므로 prefix 없이 등록
sensors_router = sensors.router
ws_router = ws.router

__all__ = ["api_router", "sensors_router", "ws_router"]
