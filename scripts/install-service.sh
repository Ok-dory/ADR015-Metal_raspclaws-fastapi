#!/usr/bin/env bash
# 부팅 시 서버가 자동 실행되도록 systemd 서비스를 등록합니다.
# 현재 사용자와 폴더 위치를 자동으로 반영하므로 파일을 직접 고칠 필요가 없습니다.
#   사용법: ./scripts/install-service.sh          (등록 + 시작)
#           ./scripts/install-service.sh remove   (해제)
set -euo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
USER_NAME="$(id -un)"
UNIT=/etc/systemd/system/raspclaws.service

if [ "${1:-}" = "remove" ]; then
  sudo systemctl disable --now raspclaws 2>/dev/null || true
  sudo rm -f "$UNIT"
  sudo systemctl daemon-reload
  echo "raspclaws 서비스를 해제했습니다."
  exit 0
fi

if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "가상환경이 없습니다. 먼저 ./update.sh 를 실행해 주세요." >&2
  exit 1
fi

# 원본 Adeept 서버가 켜져 있으면 서보/포트가 충돌하므로 끔
if systemctl is-enabled --quiet Adeept_Robot.service 2>/dev/null; then
  echo "원본 Adeept_Robot.service 를 비활성화합니다."
  sudo systemctl disable --now Adeept_Robot.service
fi

sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=RaspClaws FastAPI control server
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python run.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now raspclaws
echo "등록 완료 (사용자: $USER_NAME, 경로: $DIR)"
echo "상태: systemctl status raspclaws   로그: journalctl -u raspclaws -f"
