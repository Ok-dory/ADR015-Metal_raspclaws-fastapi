"""카메라 MJPEG 스트리밍 (Picamera2, 원본 camera_opencv.py 기준 640x480).

- 캡처 스레드 하나가 최신 JPEG 프레임을 만들고, 접속한 모든 브라우저가 공유
- 보는 사람이 없으면 몇 초 뒤 캡처를 멈춰 CPU 를 아낌
- 좌우/상하 반전, JPEG 품질은 실행 중 변경 가능
- 비전 알고리즘은 add_processor() 로 프레임 처리 함수를 끼워 넣어 확장
"""
from __future__ import annotations

import io
import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

FrameProcessor = Callable[[object], object]  # numpy BGR 이미지 → 이미지


class _PicamSource:
    name = "picamera2"

    def __init__(self, width: int, height: int) -> None:
        import cv2
        from picamera2 import Picamera2

        self._cv2 = cv2
        self._cam = Picamera2()
        cfg = self._cam.create_video_configuration(
            main={"size": (width, height), "format": "RGB888"}, buffer_count=4)
        self._cam.configure(cfg)
        self._cam.start()

    def capture(self, hflip: bool, vflip: bool, quality: int, processors) -> bytes | None:
        img = self._cam.capture_array()  # RGB888 = OpenCV 와 같은 BGR 순서
        if img is None:
            return None
        if hflip and vflip:
            img = self._cv2.flip(img, -1)
        elif hflip:
            img = self._cv2.flip(img, 1)
        elif vflip:
            img = self._cv2.flip(img, 0)
        for proc in processors:
            img = proc(img)
        ok, buf = self._cv2.imencode(".jpg", img, [self._cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes() if ok else None

    def close(self) -> None:
        self._cam.stop()
        self._cam.close()


class _MockSource:
    """카메라가 없을 때 시간이 표시된 테스트 화면을 생성 (Pillow 필요)."""

    name = "mock"

    def __init__(self, width: int, height: int) -> None:
        from PIL import Image, ImageDraw  # noqa: F401

        self.size = (width, height)
        self._n = 0

    def capture(self, hflip: bool, vflip: bool, quality: int, processors) -> bytes | None:
        from PIL import Image, ImageDraw, ImageOps

        self._n += 1
        w, h = self.size
        img = Image.new("RGB", self.size, (28, 32, 40))
        d = ImageDraw.Draw(img)
        for x in range(0, w, 40):
            d.line([(x, 0), (x, h)], fill=(45, 52, 64))
        for y in range(0, h, 40):
            d.line([(0, y), (w, y)], fill=(45, 52, 64))
        x = int((self._n * 6) % w)
        d.ellipse([x - 20, h // 2 - 20, x + 20, h // 2 + 20], fill=(37, 99, 235))
        d.text((12, 12), "MOCK CAMERA", fill=(230, 232, 236))
        d.text((12, 30), time.strftime("%H:%M:%S"), fill=(160, 168, 180))
        d.text((12, h - 24), "R", fill=(220, 38, 38))  # 반전 확인용 표식 (왼쪽 아래)
        if hflip:
            img = ImageOps.mirror(img)
        if vflip:
            img = ImageOps.flip(img)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        time.sleep(1 / 15)
        return buf.getvalue()

    def close(self) -> None:
        pass


class CameraService:
    def __init__(self, enabled: bool = True, width: int = 640, height: int = 480,
                 idle_timeout: float = 5.0) -> None:
        self.enabled = enabled
        self.width, self.height = width, height
        self.idle_timeout = idle_timeout
        self.hflip = False
        self.vflip = False
        self.quality = 70
        self._processors: list[FrameProcessor] = []
        self._source = None
        self.source_name = "none"
        self._frame: bytes | None = None
        self._frame_id = 0
        self._last_request = 0.0
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.error: str | None = None

    # ------------------------------------------------------------ 확장 포인트
    def add_processor(self, fn: FrameProcessor) -> None:
        """프레임 처리 함수 등록 (실제 카메라에서만 호출, numpy BGR 이미지 입출력)."""
        self._processors.append(fn)

    # ------------------------------------------------------------ 소스 관리
    def _open_source(self):
        try:
            src = _PicamSource(self.width, self.height)
            log.info("카메라(Picamera2) 시작 %dx%d", self.width, self.height)
            return src
        except Exception as exc:
            log.warning("Picamera2 사용 불가: %s", exc)
            self.error = str(exc)
        try:
            return _MockSource(self.width, self.height)
        except Exception:
            return None

    def _ensure_running(self) -> bool:
        if not self.enabled:
            return False
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
            self._thread.start()
            return True

    def _loop(self) -> None:
        self._source = self._open_source()
        if self._source is None:
            self.source_name = "none"
            return
        self.source_name = self._source.name
        try:
            while time.monotonic() - self._last_request < self.idle_timeout:
                try:
                    jpg = self._source.capture(self.hflip, self.vflip, self.quality,
                                               list(self._processors))
                except Exception as exc:
                    log.error("카메라 캡처 오류: %s", exc)
                    time.sleep(0.5)
                    continue
                if jpg:
                    with self._cond:
                        self._frame = jpg
                        self._frame_id += 1
                        self._cond.notify_all()
        finally:
            self._source.close()
            self._source = None
            log.info("카메라 정지 (시청자 없음)")

    # ------------------------------------------------------------ 소비자 API
    def wait_frame(self, last_id: int, timeout: float = 2.0) -> tuple[int, bytes | None]:
        self._last_request = time.monotonic()
        if not self._ensure_running():
            return last_id, None
        with self._cond:
            self._cond.wait_for(
                lambda: self._frame is not None and self._frame_id != last_id, timeout=timeout)
            return self._frame_id, self._frame

    def snapshot(self, timeout: float = 4.0) -> bytes | None:
        """새로 찍힌 프레임 한 장 (카메라가 꺼져 있었다면 켜서 기다림)."""
        _, frame = self.wait_frame(self._frame_id, timeout)
        return frame

    @property
    def streaming(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def snapshot_info(self) -> dict:
        return {
            "enabled": self.enabled,
            "source": self.source_name,
            "streaming": self.streaming,
            "hflip": self.hflip,
            "vflip": self.vflip,
            "quality": self.quality,
            "error": self.error,
        }

    def close(self) -> None:
        self._last_request = 0.0
        if self._thread:
            self._thread.join(timeout=2)
