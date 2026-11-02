"""서보 출력 포트 바꾸기 (채널 재배치).

특정 포트(예: CH2)나 그 케이블 접촉이 불량할 때, 서보를 비어 있는 포트(CH15)에
꽂고 소프트웨어에서 두 채널을 맞바꿔 그대로 사용하기 위한 기능입니다.
서보 문제인지 포트 문제인지 구분하는 진단에도 씁니다.

설정은 data/channel_map.json 에 {"swaps": [[2, 15]]} 형태로 저장되며,
나머지 코드는 항상 원래 채널 번호(논리 채널)를 그대로 사용합니다.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class ChannelRemap:
    def __init__(self, backend, path: Path) -> None:
        self._dev = backend
        self.path = path
        self._lock = threading.Lock()
        self._map: dict[int, int] = {}
        self._swaps: list[tuple[int, int]] = []
        self._gen = 0
        self._load()

    # ------------------------------------------------------------ 백엔드 인터페이스 위임
    @property
    def name(self) -> str:
        return self._dev.name

    @property
    def connected(self) -> bool:
        return getattr(self._dev, "connected", True)

    @property
    def error(self):
        return getattr(self._dev, "error", None)

    @property
    def generation(self) -> int:
        # 포트를 바꾸면 컨트롤러가 모든 서보 위치를 새 포트로 다시 보내도록
        return getattr(self._dev, "generation", 0) + self._gen

    @property
    def inner(self):
        return self._dev

    def write_pulse(self, channel: int, pulse_us: float | None) -> None:
        self._dev.write_pulse(self._map.get(channel, channel), pulse_us)

    def close(self) -> None:
        self._dev.close()

    # ------------------------------------------------------------ 포트 바꾸기
    @property
    def swaps(self) -> list[tuple[int, int]]:
        return list(self._swaps)

    def physical(self, channel: int) -> int:
        return self._map.get(channel, channel)

    def _rebuild(self) -> None:
        m: dict[int, int] = {}
        for a, b in self._swaps:
            m[a], m[b] = b, a
        self._map = m

    def set_swap(self, a: int, b: int) -> None:
        if a == b or not (0 <= a <= 15 and 0 <= b <= 15):
            raise ValueError("0~15 사이의 서로 다른 두 채널을 지정해 주세요")
        with self._lock:
            touched = {a, b}
            old = [s for s in self._swaps if touched & set(s)]
            for s in old:
                touched |= set(s)
            self._swaps = [s for s in self._swaps if s not in old] + [(a, b)]
            self._apply(touched)

    def clear(self) -> None:
        with self._lock:
            touched = {c for s in self._swaps for c in s}
            self._swaps = []
            self._apply(touched)

    def _apply(self, touched: set[int]) -> None:
        # 관련 물리 포트를 먼저 모두 끄고 → 새 배치로 다시 보내게 함
        for ch in touched:
            try:
                self._dev.write_pulse(ch, None)
            except Exception:
                pass
        self._rebuild()
        self._gen += 1
        self._save()
        log.info("서보 포트 바꾸기: %s", self._swaps or "없음")

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._swaps = [(int(a), int(b)) for a, b in data.get("swaps", [])]
            self._rebuild()
            if self._swaps:
                log.info("서보 포트 바꾸기 적용: %s", self._swaps)
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.error("channel_map.json 을 읽지 못했습니다: %s", exc)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"swaps": self._swaps}, indent=2), encoding="utf-8")
