from fastapi import HTTPException, Request

from ..robot import Robot
from ..robot_layout import SERVO_BY_CHANNEL


def get_robot(request: Request) -> Robot:
    return request.app.state.robot


def check_channel(channel: int) -> int:
    if channel not in SERVO_BY_CHANNEL:
        raise HTTPException(404, f"정의되지 않은 서보 채널: {channel}")
    return channel
