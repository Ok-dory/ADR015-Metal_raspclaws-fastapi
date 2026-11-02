#!/usr/bin/env bash
# 부팅 시 서버가 시작되기 직전에 GitHub 최신 코드를 확인해 받아옵니다.
# systemd 서비스의 ExecStartPre 로 실행되며, 어떤 경우에도 서버 시작을 막지 않습니다(항상 exit 0).
#
#   - 네트워크가 없으면 최대 BOOT_UPDATE_WAIT 초(기본 20)만 기다리고 기존 코드로 시작
#   - 로봇에서 직접 수정한 파일이 있으면 덮어쓰지 않음
#   - requirements.txt 가 바뀐 경우에만 패키지 설치
#   - 새 코드가 시작 전 점검(문법·import)을 통과하지 못하면 직전 버전으로 자동 복구
#   - 결과는 data/update_status.json 에 기록 → OLED·웹 화면에 표시
#   - 끄려면: touch data/no-auto-update   (다시 켜려면 그 파일 삭제)
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")/.." || exit 0

main() {
  local STATUS=data/update_status.json WAIT="${BOOT_UPDATE_WAIT:-20}"
  mkdir -p data

  status() {  # 결과 메시지 이전버전 새버전
    local msg=${2//\"/\'}
    printf '{"result": "%s", "message": "%s", "from": "%s", "to": "%s", "time": "%s"}\n' \
      "$1" "$msg" "$3" "$4" "$(date -Iseconds)" > "$STATUS"
    echo "[boot-update] $1: $2 ($3 -> $4)"
  }

  local old old_short
  old=$(git rev-parse HEAD 2>/dev/null) || { echo "[boot-update] git 저장소가 아닙니다"; return; }
  old_short=$(git rev-parse --short HEAD)

  if [ -f data/no-auto-update ]; then
    status disabled "자동 업데이트 꺼짐" "$old_short" "$old_short"; return
  fi
  if ! git diff --quiet || ! git diff --cached --quiet; then
    status skipped "로봇에서 수정된 파일이 있어 업데이트 안 함" "$old_short" "$old_short"; return
  fi

  # 네트워크 대기 (Wi-Fi 연결이 늦는 경우 대비)
  local deadline=$((SECONDS + WAIT)) fetched=0
  while [ $SECONDS -lt $deadline ]; do
    if GIT_TERMINAL_PROMPT=0 timeout 10 git fetch -q origin main 2>/dev/null; then
      fetched=1; break
    fi
    sleep 2
  done
  if [ $fetched = 0 ]; then
    status offline "네트워크 연결 없음 — 기존 버전으로 시작" "$old_short" "$old_short"; return
  fi

  local new new_short
  new=$(git rev-parse origin/main)
  new_short=$(git rev-parse --short origin/main)
  if [ "$old" = "$new" ]; then
    status latest "최신 버전" "$old_short" "$new_short"; return
  fi
  if ! git merge-base --is-ancestor HEAD origin/main; then
    status skipped "로봇의 커밋이 GitHub 와 달라 자동 병합 안 함" "$old_short" "$new_short"; return
  fi

  local old_req new_req
  old_req=$(git rev-parse HEAD:requirements.txt 2>/dev/null || echo none)
  git merge -q --ff-only origin/main || {
    status skipped "업데이트 적용 실패" "$old_short" "$new_short"; return; }
  new_req=$(git rev-parse HEAD:requirements.txt 2>/dev/null || echo none)

  rollback() {
    git reset -q --hard "$old"
    status rolledback "$1 — 이전 버전으로 복구" "$old_short" "$new_short"
  }

  if [ "$old_req" != "$new_req" ] && [ -x .venv/bin/pip ]; then
    if ! timeout 240 .venv/bin/pip install -q -r requirements.txt; then
      rollback "패키지 설치 실패"; return
    fi
  fi

  # 시작 전 점검: 하드웨어를 건드리지 않고 문법·import 만 확인
  local py=.venv/bin/python
  [ -x "$py" ] || py=python3
  if ! timeout 90 "$py" -m compileall -q raspclaws >/dev/null \
     || ! RASPCLAWS_BACKEND=mock timeout 90 "$py" -c "import raspclaws.app" >/dev/null 2>&1; then
    rollback "새 버전 점검 실패"; return
  fi

  status updated "$(git log -1 --format=%s | cut -c1-60)" "$old_short" "$new_short"
}

main "$@"
exit 0
