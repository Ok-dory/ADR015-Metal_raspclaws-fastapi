"""저지연 조작용 WebSocket.

클라이언트 → 서버: 명령 문자열 ("forward", "DS", "headvel 0.5 -0.2" ...)
서버 → 클라이언트: {"type": "ack", ...} 응답, 0.5초마다 {"type": "state", ...}

안전장치: 연결이 끊기면 보행과 머리 이동을 자동 정지합니다.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import commands

log = logging.getLogger(__name__)
router = APIRouter()

# 조이스틱처럼 초당 수십 번 오는 명령은 ack 를 생략해 트래픽을 줄임
SILENT = {"headvel", "look", "sonar"}


@router.websocket("/ws")
async def control_socket(ws: WebSocket):
    await ws.accept()
    robot = ws.app.state.robot

    async def push_state():
        while True:
            await ws.send_json({"type": "state", **robot.full_state()})
            await asyncio.sleep(0.5)

    pusher = asyncio.create_task(push_state())
    try:
        while True:
            text = await ws.receive_text()
            result = commands.dispatch(robot, text)
            if result.get("ok") and result.get("cmd") in SILENT:
                continue
            await ws.send_json({"type": "ack", **result})
    except WebSocketDisconnect:
        pass
    finally:
        pusher.cancel()
        robot.gait.stop()           # 연결 끊김 시 폭주 방지
        robot.head.velocity(0, 0)
        robot.sonar.stop_rotate()
        log.info("WebSocket 연결 종료 → 이동 정지")
