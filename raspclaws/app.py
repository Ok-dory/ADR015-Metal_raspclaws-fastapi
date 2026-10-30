"""FastAPI 애플리케이션 팩토리."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import api_router, sensors_router, ws_router
from .config import Settings, settings as default_settings
from .robot import Robot

STATIC_DIR = Path(__file__).parent / "web" / "static"


def create_app(settings: Settings | None = None, stand_on_start: bool = True) -> FastAPI:
    settings = settings or default_settings

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        robot = Robot(settings)
        robot.start(stand=stand_on_start)
        app.state.robot = robot
        try:
            yield
        finally:
            robot.shutdown()

    app = FastAPI(title="RaspClaws Control", version=__version__, lifespan=lifespan)
    app.include_router(api_router)
    app.include_router(sensors_router)
    app.include_router(ws_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(STATIC_DIR / "manifest.webmanifest",
                            media_type="application/manifest+json")

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
