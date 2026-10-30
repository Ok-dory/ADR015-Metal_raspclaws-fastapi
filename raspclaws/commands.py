"""텍스트 명령 디스패처.

기존 Adeept WEBUI/APP 이 사용하던 명령 문자열(forward, DS, lookleft, SiLeft 3 ...)을
그대로 받아 처리합니다. WebSocket, 향후 TCP 앱 서버 등에서 공통으로 재사용하세요.
새 명령은 @command 데코레이터로 함수 하나만 추가하면 됩니다.
"""
from __future__ import annotations

from typing import Callable

from .robot import Robot

Handler = Callable[[Robot, list[str]], object]
_REGISTRY: dict[str, Handler] = {}


def command(*names: str):
    def deco(fn: Handler) -> Handler:
        for n in names:
            _REGISTRY[n.lower()] = fn
        return fn
    return deco


def dispatch(robot: Robot, text: str) -> dict:
    parts = text.strip().split()
    if not parts:
        return {"ok": False, "error": "빈 명령"}
    name, args = parts[0].lower(), parts[1:]
    handler = _REGISTRY.get(name)
    if handler is None:
        return {"ok": False, "error": f"알 수 없는 명령: {parts[0]}"}
    try:
        result = handler(robot, args)
    except (ValueError, KeyError, IndexError) as exc:
        return {"ok": False, "cmd": name, "error": str(exc)}
    return {"ok": True, "cmd": name, "result": result}


def available_commands() -> list[str]:
    return sorted(_REGISTRY)


# ---------------------------------------------------------------- 이동
@command("forward")
def _forward(r: Robot, _):
    r.gait.move("forward")


@command("backward")
def _backward(r: Robot, _):
    r.gait.move("backward")


@command("left")
def _left(r: Robot, _):
    r.gait.move("left")


@command("right")
def _right(r: Robot, _):
    r.gait.move("right")


@command("drive")
def _drive(r: Robot, args):
    """아날로그 주행: drive <전진량 -1~1> <회전량 -1~1, +좌회전>"""
    r.gait.drive(float(args[0]), float(args[1]))


# ---------------------------------------------------------------- 다리 걸림 감지
@command("snag")
def _snag(r: Robot, args):
    """snag on | snag off"""
    on = args[0].lower() in ("on", "1", "true")
    return {"enabled": r.snag.update_config(enabled=on).enabled}


@command("snagtest")
def _snagtest(r: Robot, _):
    """걷는 중에 회복 동작(후진 → 넘어가기 걸음)을 시험 실행."""
    return {"started": r.snag.trigger_test()}


@command("imuzero")
def _imuzero(r: Robot, _):
    roll, pitch = r.snag.calibrate()
    return {"ref_roll": round(roll, 1), "ref_pitch": round(pitch, 1)}


@command("mocksnag")
def _mocksnag(r: Robot, _):
    """(하드웨어 없는 테스트 모드 전용) 다리 걸림 상황 재현."""
    if not r.imu.is_mock:
        raise ValueError("실제 센서가 연결되어 있어 모의 걸림을 사용할 수 없습니다")
    r.imu.inject_snag()


@command("DS", "TS", "stop")
def _stop(r: Robot, _):
    r.gait.stop()


@command("stand", "home")
def _stand(r: Robot, _):
    r.gait.stand()
    r.head.center()


@command("fast")
def _fast(r: Robot, _):
    r.gait.fast = True


@command("slow")
def _slow(r: Robot, _):
    r.gait.fast = False


# ---------------------------------------------------------------- 머리
@command("up")
def _up(r: Robot, _):
    r.head.move("tilt", +1)


@command("down")
def _down(r: Robot, _):
    r.head.move("tilt", -1)


@command("UDstop")
def _udstop(r: Robot, _):
    r.head.stop("tilt")


@command("lookleft")
def _lookleft(r: Robot, _):
    r.head.move("pan", +1)


@command("lookright")
def _lookright(r: Robot, _):
    r.head.move("pan", -1)


@command("LRstop")
def _lrstop(r: Robot, _):
    r.head.stop("pan")


@command("headcenter")
def _headcenter(r: Robot, _):
    r.head.center()


@command("headvel")
def _headvel(r: Robot, args):
    """조이스틱: headvel <pan -1~1> <tilt -1~1>"""
    r.head.velocity(float(args[0]), float(args[1]))


@command("look")
def _look(r: Robot, args):
    """절대 각도: look <pan> <tilt>"""
    r.head.look(pan=float(args[0]), tilt=float(args[1]))


# ---------------------------------------------------------------- 초음파 (CH14)
@command("sonarleft")
def _sonarleft(r: Robot, _):
    r.sonar.rotate(+1)


@command("sonarright")
def _sonarright(r: Robot, _):
    r.sonar.rotate(-1)


@command("sonarstop")
def _sonarstop(r: Robot, _):
    r.sonar.stop_rotate()


@command("sonarcenter")
def _sonarcenter(r: Robot, _):
    r.sonar.point(90.0)


@command("sonar")
def _sonar(r: Robot, args):
    r.sonar.point(float(args[0]))


@command("sonarscan", "scan")
def _sonarscan(r: Robot, _):
    return {"started": r.sonar.scan()}


# ---------------------------------------------------------------- 카메라
@command("hflip")
def _hflip(r: Robot, _):
    r.camera.hflip = not r.camera.hflip
    return {"hflip": r.camera.hflip}


@command("vflip")
def _vflip(r: Robot, _):
    r.camera.vflip = not r.camera.vflip
    return {"vflip": r.camera.vflip}


# ---------------------------------------------------------------- 캘리브레이션 (PWM INIT SET)
@command("SiLeft")
def _sileft(r: Robot, args):
    return {"center": r.servos.nudge_center(int(args[0]), -1.0)}


@command("SiRight")
def _siright(r: Robot, args):
    return {"center": r.servos.nudge_center(int(args[0]), +1.0)}


@command("PWMMS", "save")
def _save(r: Robot, _):
    r.servos.save_calibration()


@command("PWMINIT", "resetcal")
def _resetcal(r: Robot, _):
    r.servos.reset_centers()


@command("release")
def _release(r: Robot, args):
    if args:
        r.servos.release(int(args[0]))
    else:
        r.gait.stop()
        r.servos.release_all()
