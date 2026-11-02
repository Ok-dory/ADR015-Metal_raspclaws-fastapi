"""하드웨어 없는 테스트 모드용 가상 주행 (초음파 거리 시뮬레이션).

전진하면 앞쪽 벽까지 거리가 줄어들고, 벽에 가까워지면 새 벽이 나타나는 단순한 세계.
stall() 을 호출하면 몇 초간 '발이 미끄러져 제자리에서 허우적대는' 상황을 재현합니다.
"""
from __future__ import annotations

import threading
import time

from .motion.gait import GaitEngine

CM_PER_CYCLE = 6.0   # 한 보행 주기(최대 보폭)에 나아가는 거리(cm, 대략값)


class SimWorld:
    def __init__(self, gait: GaitEngine) -> None:
        self.gait = gait
        self.traveled = 0.0
        self._stall_until = 0.0
        self._running = threading.Event()

    def start(self) -> None:
        self._running.set()
        threading.Thread(target=self._loop, name="sim-world", daemon=True).start()

    def stop(self) -> None:
        self._running.clear()

    def stall(self, seconds: float = 6.0) -> None:
        self._stall_until = time.monotonic() + seconds

    @property
    def stalled(self) -> bool:
        return time.monotonic() < self._stall_until

    def _loop(self) -> None:
        last = time.monotonic()
        while self._running.is_set():
            now = time.monotonic()
            dt, last = now - last, now
            vx, _ = self.gait.effective_target
            _, stride = self.gait.motion_info()
            if not self.stalled and vx:
                speed = CM_PER_CYCLE * self.gait.stride_scale * stride / self.gait.period
                self.traveled += (1 if vx > 0 else -1) * speed * dt
            time.sleep(0.05)

    def front_distance(self) -> float:
        """정면 벽까지 거리: 140cm 에서 줄어들다 30cm 가 되면 다시 140cm."""
        return 140.0 - (self.traveled % 110.0)
