#!/usr/bin/env bash
# GitHub 에서 최신 코드를 받아오고 서버를 재시작합니다.
#   사용법: cd ~/raspclaws-fastapi && ./update.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

# 이 폴더에서 수동 실행 중인 run.py 가 있는지 (작업 폴더로 판별)
manual_running() {
  local pid
  for pid in $(pgrep -f 'run\.py' || true); do
    if [ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" = "$PWD" ] \
       && tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q '^[^ ]*python[0-9.]* run\.py'; then
      return 0
    fi
  done
  return 1
}

say() { printf '\033[1;34m▶ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }

# 1) 라즈베리파이에서 직접 고친 내용이 있으면 덮어쓰지 않도록 중단
if ! git diff --quiet || ! git diff --cached --quiet; then
  warn "이 라즈베리파이에서 수정된 파일이 있어 업데이트를 중단합니다:"
  git status --short
  echo "  - 버리려면:   git checkout -- . && ./update.sh"
  echo "  - 올리려면:   git add . && git commit -m \"메시지\" && git push && ./update.sh"
  exit 1
fi

old=$(git rev-parse HEAD)
old_req=$(git rev-parse HEAD:requirements.txt 2>/dev/null || echo none)

say "GitHub 에서 최신 코드 받아오는 중..."
git pull --ff-only

new=$(git rev-parse HEAD)
new_req=$(git rev-parse HEAD:requirements.txt 2>/dev/null || echo none)

if [ "$old" = "$new" ]; then
  say "이미 최신 버전입니다 ($(git log -1 --format='%h %s'))"
else
  say "새로 반영된 변경:"
  git log --format='   %h %s' "$old..$new"
fi

# 2) 가상환경 / 패키지 (requirements.txt 가 바뀐 경우에만 설치)
if [ ! -x .venv/bin/python ]; then
  say "가상환경 생성 중..."
  python3 -m venv --system-site-packages .venv
  old_req="(new venv)"
fi
if [ "$old_req" != "$new_req" ]; then
  say "패키지 설치 중 (requirements.txt 변경됨)..."
  .venv/bin/pip install -r requirements.txt
fi

# 3) 서버 재시작
if systemctl is-active --quiet raspclaws 2>/dev/null; then
  say "서버 재시작 중..."
  sudo systemctl restart raspclaws
  sleep 2
  if systemctl is-active --quiet raspclaws; then
    say "완료! http://$(hostname -I | awk '{print $1}'):5000"
  else
    warn "서버가 시작되지 않았습니다. 로그: journalctl -u raspclaws -n 50"
    exit 1
  fi
elif manual_running; then
  warn "수동으로 실행 중인 서버가 있습니다. 그 터미널에서 Ctrl+C 후 다시 실행해 주세요:"
  echo "   .venv/bin/python run.py"
else
  say "업데이트 완료. 서버 실행:  .venv/bin/python run.py"
  echo "   (부팅 시 자동 실행: ./scripts/install-service.sh)"
fi
