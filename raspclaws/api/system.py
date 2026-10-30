from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import commands
from ..robot import Robot
from .deps import get_robot

router = APIRouter(tags=["system"])


class CommandIn(BaseModel):
    command: str


@router.get("/status")
def status(robot: Robot = Depends(get_robot)):
    data = robot.full_state()
    data.pop("servos")
    return data


@router.get("/commands")
def list_commands():
    return commands.available_commands()


@router.post("/command")
def run_command(body: CommandIn, robot: Robot = Depends(get_robot)):
    """기존 문자열 명령을 HTTP 로 실행 (예: {"command": "SiLeft 12"})."""
    return commands.dispatch(robot, body.command)
