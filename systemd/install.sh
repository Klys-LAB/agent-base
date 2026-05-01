#!/usr/bin/env bash
# systemd unit 설치 스크립트 (VPS root 에서 실행)
# 사용: bash systemd/install.sh billi

set -euo pipefail

PROJECT="${1:-billi}"
AGENT_BASE="/root/Klys-LAB/agent-base"
SERVICE="agent@${PROJECT}.service"
UNIT_SRC="${AGENT_BASE}/systemd/agent@.service"
UNIT_DST="/etc/systemd/system/agent@.service"

echo "=== agent-base systemd 설치: ${PROJECT} ==="

# 1. unit 파일 복사
cp "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload

# 2. 활성화 + 시작
systemctl enable "$SERVICE"
systemctl start "$SERVICE"

# 3. 상태 확인
sleep 2
systemctl status "$SERVICE" --no-pager

echo ""
echo "=== 설치 완료 ==="
echo "로그: journalctl -u ${SERVICE} -f"
