# RaspClaws FastAPI Control

Adeept RaspClaws-Metal(Raspberry Pi 5 + Robot HAT V3.3)용 커스텀 제어 서버입니다.
기존 `WebServer.py`(Port 5000)를 대체하며, 서보 제어 / 보행 / 머리 / 웹 서버를 모듈로 분리했습니다.

## 구조

```
raspclaws-fastapi/
├─ run.py                     # 실행 진입점 (uvicorn, 0.0.0.0:5000)
├─ requirements.txt
├─ raspclaws.service          # systemd 자동 실행용
├─ data/servos_init.json      # 영점 캘리브레이션 (SAVE 시 생성)
└─ raspclaws/
   ├─ config.py               # 설정 (환경변수 RASPCLAWS_* 로 덮어쓰기)
   ├─ robot_layout.py         # ★ 서보 채널·다리 배치·반전·안전 한계
   ├─ hardware/pwm.py         # PCA9685(0x5F) / Mock 백엔드
   ├─ servo/controller.py     # 스무딩·데드밴드·유휴 해제 제어 루프 (전용 스레드)
   ├─ servo/calibration.py    # 영점 저장/불러오기
   ├─ motion/gait.py          # 트라이포드 보행
   ├─ motion/head.py          # 머리 팬/틸트
   ├─ robot.py                # 위 모듈을 묶는 Robot 퍼사드
   ├─ commands.py             # 기존 명령 문자열 호환 디스패처
   ├─ system_info.py          # CPU 온도/사용률, RAM
   ├─ api/                    # FastAPI 라우터 (REST + /ws)
   └─ web/static/             # 웹 UI
```

계층은 `API → Robot → (Gait/Head) → ServoController → PWMBackend` 한 방향으로만 의존합니다.
나중에 앱 서버(8888), PC GUI, 비전 모듈을 붙일 때도 `Robot` 객체만 넘겨 주시면 됩니다.

## 설치 (Raspberry Pi)

```bash
# 1) 기존 Adeept 서버가 I2C·포트를 점유하지 않도록 중지
sudo killall python3          # 자동 실행 설정(crontab/rc.local/systemd)도 확인해 주세요

# 2) 가상환경 (Bookworm 은 시스템 pip 설치가 막혀 있음)
cd ~/raspclaws-fastapi
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt

# 3) 실행
.venv/bin/python run.py
# 브라우저: http://192.168.1.48:5000   API 문서: http://192.168.1.48:5000/docs
```

PC에서 하드웨어 없이 개발할 때는 `RASPCLAWS_BACKEND=mock python run.py` 로 실행하시면 됩니다
(`auto` 기본값은 PCA9685 초기화 실패 시 자동으로 mock 으로 전환).

자동 실행: `raspclaws.service` 의 `User`/경로를 수정한 뒤
`sudo cp raspclaws.service /etc/systemd/system/ && sudo systemctl enable --now raspclaws`

## 첫 실행 시 꼭 해 주실 일

1. **채널 확인** – 채널 맵은 프로젝트 지침(왼쪽 CH0~5, 오른쪽 CH6~11, CH12 팬, CH13 틸트, CH14 초음파)
   기준이며, 앞/뒤 순서와 회전 부호는 원본 `Move.py` 에서 가져왔습니다.
   웹 UI의 *식별(흔들기)* 버튼으로 한 번 확인해 주세요.
2. **방향 확인** – 전진 시 다리가 반대로 움직이면 해당 서보의 `inverted`,
   다리가 위가 아닌 아래로 눌리면 `GaitParams.lift_sign` 을 바꿉니다.
3. **영점** – 채널 선택 → `−1°/+1°` → 자세 확인 → **SAVE**.
   기존 `~/Adeept_RaspClaws-Metal/Server/Servos_Init.json` 을 `data/servos_init.json` 으로
   복사해 두시면 원본에서 맞춰 둔 영점을 그대로 불러옵니다.

## 머리 떨림(헌팅) 대응

머리 서보(12·13·14)에는 다음이 기본 적용되어 있습니다 (`robot_layout.py`).

- `release_when_idle=True` – 정지 후 0.8초가 지나면 PWM 을 끊어 토크를 해제 → 정지 중 헌팅이 원천적으로 사라집니다.
  다만 무게 때문에 고개가 처진다면 해당 서보만 `False` 로 바꾸고 물리 패딩으로 보완해 주세요.
- 속도 제한 이동(`default_speed`) – 급가속에 의한 오버슈트 감소
- 쓰기 데드밴드(`RASPCLAWS_DEADBAND_US`, 기본 4µs) – 의미 없는 미세 펄스 변화 무시
- 안전 각도 한계(`min_angle`/`max_angle`) – 기구 끝단에 부딪혀 버티는 상황 방지

## 주변장치 (v4)

| 장치 | 연결 | 비고 |
|---|---|---|
| 카메라 | Picamera2 (640×480 MJPEG) | `/video_feed`, 스냅샷 `/api/camera/snapshot`, 보는 사람이 없으면 5초 뒤 자동 정지 |
| 초음파 | GPIO23(TRIG)/24(ECHO) + CH14 회전 | 부채꼴 스캔 `/api/sonar/scan`, 웹 레이더 표시 |
| OLED | SSD1306 I2C 0x3C | 시각·IP·서버 상태·보행 상태·배터리/CPU 온도 2초마다 갱신 |
| 배터리 | ADS7830 I2C 0x48 | 6.0V 미만이면 웹/OLED 에 LOW 표시 |

비전 알고리즘은 `robot.camera.add_processor(함수)` 로 프레임 처리 함수를 끼워 넣어 확장합니다.
특정 장치를 끄려면 `RASPCLAWS_CAMERA=0`, `RASPCLAWS_OLED=0` 등 환경변수를 사용하세요.

## 웹 조작

- **PC**: W A S D 이동, I J K L 카메라, Q / E 초음파 회전, Space 전체 정지
- **스마트폰**: 왼쪽 조이스틱 이동, 오른쪽 조이스틱 카메라(기울인 만큼 빠르게), 영상 탭 → 그 지점 조준
- 가로로 눕히면 조종석 모드(조이스틱 | 영상 | 조이스틱)로 바뀌고, ⛶ 버튼으로 전체화면
- 크롬 메뉴의 "홈 화면에 추가"로 앱처럼 실행 가능, 조작 중에는 화면 꺼짐 방지
- 서보 영점 설정은 기본으로 접혀 있으며 펼침 상태를 기억합니다

## 주요 API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/servos` | 전체 서보 상태 |
| PUT | `/api/servos/{ch}` | `{"angle": 0~180, "speed": deg/s}` |
| POST | `/api/servos/{ch}/identify` · `/release` | 흔들어 식별 · 토크 해제 |
| POST | `/api/calibration/{ch}/nudge` | `{"delta": ±n}` 영점 미세조정 |
| POST | `/api/calibration/save` · `/reset` | 영점 저장 · 초기화 |
| POST | `/api/motion/{forward\|backward\|left\|right\|stop}` | 보행 |
| PUT | `/api/motion/speed` | `{"mode": "fast"\|"slow"}` |
| PUT | `/api/head` | `{"pan": .., "tilt": ..}` |
| GET | `/api/status` | 보행 상태 + CPU/RAM |
| POST | `/api/command` | 기존 문자열 명령 실행 |
| GET | `/video_feed` · `/api/camera/snapshot` | 카메라 영상 · 사진 |
| PUT | `/api/camera` | `{"hflip", "vflip", "quality"}` |
| GET/PUT | `/api/sonar` | 거리·스캔 결과 / `{"angle"}` 센서 방향 |
| WS | `/ws` | 명령 문자열 송신, 0.5초마다 상태 수신 |

기존 명령(`forward`, `DS`, `TS`, `up`, `UDstop`, `lookleft`, `LRstop`, `fast`, `slow`,
`SiLeft N`, `SiRight N`, `PWMMS` 등)은 그대로 동작합니다. 새 명령은 `commands.py` 에
`@command("이름")` 함수를 하나 추가하면 WS·REST 양쪽에서 바로 쓸 수 있습니다.

## 안전 장치

- WebSocket 연결이 끊기면 보행 자동 정지
- 브라우저 창 포커스를 잃으면 누르고 있던 버튼 모두 해제
- 서버 종료 시 PCA9685 출력 전체 OFF
