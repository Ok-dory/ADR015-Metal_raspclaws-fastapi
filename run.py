#!/usr/bin/env python3
"""실행 진입점: python run.py  (기본 0.0.0.0:5000)"""
import uvicorn

from raspclaws.config import settings

if __name__ == "__main__":
    # 하드웨어 스레드를 쓰므로 workers=1, reload 비활성 유지
    uvicorn.run("raspclaws.app:app", host=settings.host, port=settings.port, workers=1)
