"""다리 걸림 감지 + 자동 회복 (간접 감지 2가지).

감지 원리 (서보에 위치 피드백이 없으므로 결과로 판단)
    1) 자세 센서(MPU6050): 다리가 걸려 몸통이 평소보다 크게 기울거나(tilt)
       덜컥거리면(gyro) 걸림. 순간 흔들림은 무시하도록 hold_time 이상 지속될 때만 인정.
    2) 전진 정체(초음파): 발이 미끄러져 몸이 기울지 않고 '제자리에서 허우적'대는 경우.
       전진 중인데 정면 물체까지의 거리가 stall_time 동안 stall_progress 보다 덜 줄면 정체.
       (센서가 정면을 보고 있고, 앞에 stall_range 이내의 물체가 있을 때만 판단 가능)

자동 회복 (넘어가기 걸음)
    1) 후진(backoff): 다리를 높이 들고 진행 반대 방향으로 반걸음 물러남
    2) 재시도(stepover): 다리를 높이 드는 '넘어가기 걸음'으로 원래 방향 진행
    3) 재시도 중 또는 직후에 다시 걸리면 한 번 더 반복
    4) max_retries 를 넘기면 정지하고 '막힘' 경고 (조이스틱을 놓았다가 다시 밀면 해제)
    사용자가 정지(STOP/조이스틱 놓기)하면 회복 동작보다 항상 우선합니다.

기준값은 로봇마다 다르므로 '기록 모드'로 평소 보행과 걸림 상황의 센서 값을
CSV 로 남겨 비교한 뒤 웹 화면에서 조정하도록 했습니다.
"""
from __future__ import annotations

import csv
import json
import statistics
import logging
import math
import re
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from collections import deque

from ..peripherals import ImuSensor
from .gait import GaitEngine
from .sonar import SonarController

log = logging.getLogger(__name__)


@dataclass
class SnagConfig:
    enabled: bool = False          # 실기에서 기준값을 맞춘 뒤 켜는 것을 권장
    tilt_threshold: float = 10.0   # 기준 자세 대비 기울기(도)
    gyro_threshold: float = 120.0  # roll/pitch 회전 속도(°/s)
    hold_time: float = 0.15        # 이 시간 이상 지속되어야 걸림으로 인정(s)
    min_stride: float = 0.3        # 이보다 약하게 걸을 때는 감지 안 함 (제자리 미세 조작 오탐 방지)
    backoff_time: float = 1.0      # 후진 시간(s)
    backoff_speed: float = 0.6     # 후진 세기(0~1)
    stepover_time: float = 2.0     # 넘어가기 걸음 시간(s)
    lift_scale: float = 1.7        # 넘어가기 걸음의 다리 드는 높이 배율
    max_retries: int = 2           # 연속 실패 허용 횟수 → 초과 시 정지·경고
    reset_time: float = 4.0        # 회복 후 이 시간 동안 문제없으면 실패 횟수 초기화(s)
    # 전진 정체 감지 (초음파)
    stall_enabled: bool = True     # 걸림 감지가 켜져 있을 때 함께 사용
    stall_time: float = 2.5        # 이 시간 동안의 거리 변화로 판단(s)
    stall_progress: float = 3.0    # 이보다 덜 가까워지면 정체(cm)
    stall_range: float = 150.0     # 정면 물체가 이 거리 안에 있을 때만 판단(cm)

    @classmethod
    def load(cls, path: Path) -> "SnagConfig":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            names = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in data.items() if k in names})
        except FileNotFoundError:
            return cls()
        except Exception as exc:
            log.error("걸림 감지 설정을 읽지 못했습니다: %s", exc)
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")


STATE_TEXT = {
    "off": "꺼짐",
    "idle": "대기",
    "watch": "감시 중",
    "backoff": "걸림 감지 · 후진",
    "stepover": "넘어가기 걸음",
    "blocked": "막힘 · 정지",
}


class SnagGuard:
    def __init__(self, gait: GaitEngine, imu: ImuSensor, data_dir: Path,
                 sonar: SonarController | None = None, simulated: bool = False) -> None:
        self.gait = gait
        self.imu = imu
        self.sonar = sonar
        self.simulated = simulated        # 테스트 모드: 가상 주행 거리 사용 허용
        self._stall_win: deque[tuple[float, float]] = deque()
        self.stall_info: dict = {"active": False, "reason": "대기"}
        self.config_path = data_dir / "snag_config.json"
        self.log_dir = data_dir / "imu_logs"
        self.config = SnagConfig.load(self.config_path)
        self.state = "off" if not self.config.enabled else "idle"
        self.retries = 0
        self.detections = 0
        self.last_event: dict | None = None
        self._event_id = 0
        self._over_since: float | None = None
        self._state_since = time.monotonic()
        self._last_recovery_end = 0.0
        self._manual_test = False
        self._lock = threading.RLock()
        self._running = threading.Event()
        # 기록 모드
        self._log_file = None
        self._log_writer = None
        self._log_name: str | None = None
        self._log_started = 0.0
        self.max_log_seconds = 300.0

    # ------------------------------------------------------------ 설정
    def update_config(self, **changes) -> SnagConfig:
        with self._lock:
            for k, v in changes.items():
                if v is not None and hasattr(self.config, k):
                    setattr(self.config, k, type(getattr(self.config, k))(v))
            self.config.save(self.config_path)
            if not self.config.enabled:
                self._abort("off")
            elif self.state == "off":
                self._set_state("idle")
            return self.config

    # ------------------------------------------------------------ 수명주기
    def start(self) -> None:
        self._running.set()
        threading.Thread(target=self._loop, name="snag-guard", daemon=True).start()

    def stop(self) -> None:
        self._running.clear()
        self.stop_recording()

    # ------------------------------------------------------------ 외부 동작
    def trigger_test(self) -> bool:
        """걸림이 감지된 것처럼 회복 동작을 실행 (걷는 중일 때만)."""
        with self._lock:
            if self.gait.target == (0.0, 0.0):
                return False
            self._manual_test = True
            return True

    def calibrate(self) -> tuple[float, float]:
        """현재 서 있는 자세를 기준 자세로 저장."""
        return self.imu.set_reference()

    # ------------------------------------------------------------ 내부 상태
    def _set_state(self, state: str) -> None:
        self.state = state
        self._state_since = time.monotonic()

    def _event(self, kind: str, message: str) -> None:
        self._event_id += 1
        self.last_event = {"id": self._event_id, "type": kind, "message": message, "time": time.time()}
        log.info("[걸림] %s", message)

    def _abort(self, new_state: str) -> None:
        self.gait.clear_override()
        self._over_since = None
        self._set_state(new_state)

    def _user_drive(self) -> tuple[float, float]:
        return self.gait.target

    def _detected(self, now: float) -> bool:
        c = self.config
        over = self.imu.tilt > c.tilt_threshold or self.imu.gyro_rate > c.gyro_threshold
        if not over:
            self._over_since = None
            return False
        if self._over_since is None:
            self._over_since = now
        return now - self._over_since >= c.hold_time

    # ------------------------------------------------------------ 전진 정체 (초음파)
    def _stall_check(self, now: float, user: tuple[float, float], stride: float) -> str | None:
        """정체로 판단되면 이유 문자열, 아니면 None. stall_info 에 진행 상황 기록."""
        c = self.config
        son = self.sonar
        win = self._stall_win

        def idle(reason: str) -> None:
            win.clear()
            self.stall_info = {"active": False, "reason": reason}

        if not c.stall_enabled:
            return idle("꺼짐")
        if son is None or (son.sensor.is_mock and not self.simulated):
            return idle("초음파 센서 없음")
        vx, wz = user
        # 아주 약하게 걸을 때는 원래 거의 안 나아가므로 판단하지 않음 (오탐 방지)
        if vx < 0.3 or abs(wz) > max(0.3, vx * 0.6) or stride < max(c.min_stride, 0.5):
            return idle("직진 중에만 판단")
        if son.scanning or abs(son.angle - 90.0) > 15:
            return idle("센서가 정면이 아님")
        d = son.distance
        if d is None or d > c.stall_range:
            return idle(f"앞 {c.stall_range:.0f}cm 안에 물체 없음")

        win.append((now, d))
        while win and now - win[0][0] > c.stall_time + 0.5:
            win.popleft()
        span = win[-1][0] - win[0][0]
        if span < c.stall_time:
            self.stall_info = {"active": True, "reason": "측정 중", "progress": None,
                               "span": round(span, 1)}
            return None
        edge = 0.6
        early = [x for t, x in win if t - win[0][0] <= edge]
        late = [x for t, x in win if win[-1][0] - t <= edge]
        progress = statistics.median(early) - statistics.median(late)
        self.stall_info = {"active": True, "reason": "측정 중", "progress": round(progress, 1),
                           "span": round(span, 1)}
        # 창을 앞으로 밀어 다음 판단 준비
        while win and now - win[0][0] > c.stall_time:
            win.popleft()
        if progress < -10:
            # 앞 물체가 치워지거나 방향이 바뀌어 거리가 크게 늘어난 경우 → 새로 측정
            win.clear()
            return None
        if progress < c.stall_progress:
            win.clear()
            return f"전진 정체 · {c.stall_time:.1f}초간 {max(progress, 0):.1f}cm"
        return None

    def _begin_recovery(self, now: float, reason: str) -> None:
        c = self.config
        self.retries += 1
        self.detections += 1
        self._over_since = None
        self._stall_win.clear()
        if self.retries > c.max_retries:
            self.gait.clear_override()
            self.gait.stop()
            self._set_state("blocked")
            self._event("blocked", f"걸림이 {self.retries - 1}번 회복되지 않아 정지했습니다")
            return
        vx, wz = self._user_drive()
        mag = math.hypot(vx, wz) or 1.0
        self.gait.set_override(-vx / mag * c.backoff_speed, -wz / mag * c.backoff_speed,
                               lift_scale=c.lift_scale)
        self._set_state("backoff")
        self._event("snag", f"걸림 감지({reason}) → 후진 후 넘어가기 걸음 ({self.retries}/{c.max_retries})")

    # ------------------------------------------------------------ 메인 루프 (50Hz)
    def _loop(self) -> None:
        while self._running.is_set():
            t0 = time.monotonic()
            try:
                with self._lock:
                    self._tick(t0)
                self._write_log_row()
            except Exception:
                log.exception("걸림 감지 루프 오류")
            time.sleep(max(0.0, 0.02 - (time.monotonic() - t0)))

    def _tick(self, now: float) -> None:
        c = self.config
        if not c.enabled:
            if self.state != "off":
                self._abort("off")
            self._manual_test = False
            return

        user = self._user_drive()
        user_moving = user != (0.0, 0.0)

        # 사용자 정지는 항상 최우선
        if not user_moving:
            if self.state in ("backoff", "stepover"):
                self._event("info", "사용자 정지로 회복 동작을 중단했습니다")
                self._abort("idle")
            elif self.state == "blocked":
                pass  # 막힘 상태 유지 → 다시 움직이면 해제
            elif self.state != "idle":
                self._set_state("idle")
            self._manual_test = False
            self._stall_win.clear()
            self.stall_info = {"active": False, "reason": "정지"}
            if now - self._last_recovery_end > c.reset_time:
                self.retries = 0
            return

        if self.state == "blocked":
            # 정지 후 사용자가 다시 움직이기 시작 → 해제
            if now - self._state_since > 0.3:
                self.retries = 0
                self._set_state("watch")
                self._event("info", "막힘 해제 — 다시 감시합니다")
            return

        if self.state in ("idle", "off"):
            self._set_state("watch")
        if self.state != "watch":
            self._stall_win.clear()

        _, stride = self.gait.motion_info()

        if self.state == "watch":
            if now - self._last_recovery_end > c.reset_time:
                self.retries = 0
            if self._manual_test:
                self._manual_test = False
                self._begin_recovery(now, "테스트")
            elif stride >= c.min_stride and self._detected(now):
                self._begin_recovery(now, self._reason())
            else:
                stall = self._stall_check(now, user, stride)
                if stall:
                    self._begin_recovery(now, stall)
        elif self.state == "backoff":
            if now - self._state_since >= c.backoff_time:
                vx, wz = user
                self.gait.set_override(vx, wz, lift_scale=c.lift_scale)
                self._over_since = None
                self._set_state("stepover")
        elif self.state == "stepover":
            # 사용자가 방향을 바꾸면 넘어가기 걸음도 그 방향으로
            self.gait.set_override(*user, lift_scale=c.lift_scale)
            if self._detected(now):
                self._begin_recovery(now, self._reason())
            elif now - self._state_since >= c.stepover_time:
                self.gait.clear_override()
                self._last_recovery_end = now
                self._set_state("watch")
                self._event("recovered", "넘어가기 걸음 완료 — 정상 보행으로 복귀")

    def _reason(self) -> str:
        return f"기울기 {self.imu.tilt:.0f}° · 흔들림 {self.imu.gyro_rate:.0f}°/s"

    # ------------------------------------------------------------ 기록 모드
    @property
    def recording(self) -> bool:
        return self._log_writer is not None

    def start_recording(self, label: str = "") -> str:
        with self._lock:
            self.stop_recording()
            self.log_dir.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", label).strip("_")[:30]
            name = time.strftime("%Y%m%d_%H%M%S") + (f"_{safe}" if safe else "") + ".csv"
            self._log_file = open(self.log_dir / name, "w", newline="", encoding="utf-8")
            self._log_writer = csv.writer(self._log_file)
            self._log_writer.writerow(["t", "roll", "pitch", "tilt", "gyro", "ax", "ay", "az",
                                       "vx", "wz", "stride", "phase", "sonar", "state", "event"])
            self._log_name = name
            self._log_started = time.monotonic()
            self._logged_event = self._event_id
            return name

    def stop_recording(self) -> str | None:
        with self._lock:
            name = self._log_name
            if self._log_file:
                self._log_file.close()
            self._log_file = self._log_writer = self._log_name = None
            return name

    def _write_log_row(self) -> None:
        with self._lock:
            if not self._log_writer:
                return
            t = time.monotonic() - self._log_started
            if t > self.max_log_seconds:
                self.stop_recording()
                return
            phase, stride = self.gait.motion_info()
            vx, wz = self.gait.target
            ax, ay, az = self.imu.accel
            ev = ""
            if self.last_event and self.last_event["id"] != self._logged_event:
                ev = self.last_event["type"]
                self._logged_event = self.last_event["id"]
            self._log_writer.writerow([
                f"{t:.3f}", f"{self.imu.roll - self.imu.ref_roll:.2f}",
                f"{self.imu.pitch - self.imu.ref_pitch:.2f}", f"{self.imu.tilt:.2f}",
                f"{self.imu.gyro_rate:.1f}", f"{ax:.3f}", f"{ay:.3f}", f"{az:.3f}",
                f"{vx:.2f}", f"{wz:.2f}", f"{stride:.2f}", f"{phase:.3f}",
                "" if not self.sonar or self.sonar.distance is None else f"{self.sonar.distance:.1f}",
                self.state, ev])

    def list_logs(self) -> list[dict]:
        if not self.log_dir.exists():
            return []
        files = sorted(self.log_dir.glob("*.csv"), reverse=True)
        return [{"name": f.name, "size": f.stat().st_size} for f in files[:30]]

    def log_path(self, name: str) -> Path | None:
        if not re.fullmatch(r"[0-9A-Za-z가-힣_-]+\.csv", name):
            return None
        path = self.log_dir / name
        return path if path.is_file() else None

    # ------------------------------------------------------------ 상태
    def snapshot(self) -> dict:
        elapsed = time.monotonic() - self._log_started if self.recording else 0
        return {
            "state": self.state,
            "state_text": STATE_TEXT.get(self.state, self.state),
            "retries": self.retries,
            "detections": self.detections,
            "event": self.last_event,
            "config": asdict(self.config),
            "imu": self.imu.snapshot(),
            "stall": self.stall_info,
            "simulated": self.simulated,
            "recording": {"active": self.recording, "name": self._log_name,
                          "seconds": round(elapsed, 1)},
        }
