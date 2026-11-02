#!/usr/bin/env python3
"""실행 진입점: python run.py  (기본 0.0.0.0:5000)"""
import socket
import subprocess
import sys

import uvicorn

from raspclaws.config import settings


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def service_active() -> bool:
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", "raspclaws"],
                              timeout=3, stderr=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


if __name__ == "__main__":
    # 하드웨어(서보·GPIO)를 건드리기 전에 확인: 이미 서버가 떠 있으면 두 번째 실행이
    # 종료되면서 서보 출력을 꺼 버리는 문제가 생기므로 여기서 바로 멈춘다.
    if port_in_use(settings.host, settings.port):
        print(f"\n포트 {settings.port} 를 이미 사용 중이라 실행하지 않습니다.")
        if service_active():
            print("  → 자동 실행 서비스(raspclaws)로 서버가 이미 동작 중입니다.")
            print(f"     브라우저로 바로 접속하세요: http://<로봇IP>:{settings.port}")
            print("     로그 보기:   journalctl -u raspclaws -f")
            print("     직접 실행하려면 먼저:  sudo systemctl stop raspclaws")
        else:
            print("  → 다른 터미널에서 실행 중인 서버를 Ctrl+C 로 종료한 뒤 다시 실행해 주세요.")
        sys.exit(1)

    # 하드웨어 스레드를 쓰므로 workers=1, reload 비활성 유지
    uvicorn.run("raspclaws.app:app", host=settings.host, port=settings.port, workers=1)
