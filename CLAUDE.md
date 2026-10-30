# RaspClaws FastAPI — 작업 안내 (Claude 용)

Adeept RaspClaws-Metal 헥사포드(Raspberry Pi 5 + Robot HAT V3.3) 커스텀 제어 서버.
사용자는 한국어로, 공손한 말투로 응대한다.

## 작업 흐름
1. Claude 가 이 저장소에서 수정 → mock 모드로 검증 → `main` 에 커밋·푸시
2. 라즈베리파이(`~/raspclaws-fastapi`, 사용자 `okdory`, IP 192.168.1.48)에서 `./update.sh` 로 반영
3. 로봇에서 직접 코드를 고치지 않는 것이 원칙. 작업 시작 전 `git pull` 로 최신 상태 확인

## 검증 방법 (하드웨어 없이)
```bash
pip install -r requirements.txt
RASPCLAWS_BACKEND=mock RASPCLAWS_DATA_DIR=/tmp/rc python run.py   # http://localhost:5000
```
- 서보는 MockBackend, 초음파는 각도 기반 가상 거리, 카메라는 Pillow 테스트 화면
- API 는 `fastapi.testclient.TestClient(create_app())` 로 테스트 (MJPEG 스트림은 실제 서버 + curl 로)
- 프론트엔드는 `node --check raspclaws/web/static/app.js` + Playwright 스크린샷(데스크톱 / 390x844 / 844x390)

## 하드웨어 확정 사항 (바꾸지 말 것)
- PCA9685 I2C 0x5F, 50Hz, 500–2400µs
- 왼쪽 다리 hip CH0,2,4 / lift CH1,3,5 · 오른쪽 다리 hip CH6,8,10 / lift CH7,9,11
- 앞다리 CH0/1·CH10/11, 중간 CH2/3·CH8/9, 뒷다리 CH4/5·CH6/7, 오른쪽(CH6–11)은 부호 반전
- CH12 카메라 팬, CH13 카메라 틸트(반전), CH14 초음파 회전
- 초음파 GPIO23/24, OLED SSD1306 0x3C, 배터리 ADS7830 0x48
- 머리 서보(12·13·14)는 헌팅 방지를 위해 release_when_idle 사용

## 원칙
- 웹 UI(포트 5000 단일) 전용. 원본 APP(8888)/PC GUI 는 대상 아님
- 스마트폰·PC 모두 같은 페이지로 조작 (반응형, 가로 화면 조종석 모드)
- 새 명령은 `raspclaws/commands.py` 의 `@command`, 새 장치는 `raspclaws/peripherals/` + `Robot` 에 연결
- `data/servos_init.json`(로봇별 영점)은 git 에 올리지 않음
