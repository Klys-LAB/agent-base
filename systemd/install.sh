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

# 0. Python 의존성 설치 (Ubuntu 24.04 PEP 668 — --break-system-packages)
#    ExecStart=/usr/bin/python3 와 동일 환경 보장.
REQ_FILE="${AGENT_BASE}/requirements.txt"
if [ -f "$REQ_FILE" ]; then
    echo "--- pip install (system python3, --break-system-packages) ---"
    /usr/bin/python3 -m pip install --break-system-packages --upgrade -r "$REQ_FILE"
    echo "--- import 검증 ---"
    /usr/bin/python3 -c "import yaml; print(f'pyyaml {yaml.__version__} OK')"
else
    echo "WARN: requirements.txt 없음 — 의존성 설치 건너뜀"
fi

# 1. unit 파일 복사
cp "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload

# 2. 활성화 + (재)시작
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

# 3. 상태 확인
sleep 2
systemctl status "$SERVICE" --no-pager

echo ""
echo "=== 설치 완료 ==="
echo "로그: journalctl -u ${SERVICE} -f"
