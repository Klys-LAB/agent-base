#!/usr/bin/env bash
# x11vnc 셋업 — BILLI MT5 GUI 1회 로그인 (BILLI msg 455, P2-003-R2 Phase 1)
#
# 사용:
#   bash systemd/setup-vnc.sh           # 첫 설치 (apt + password 생성 + unit + 활성화)
#   bash systemd/setup-vnc.sh password  # password 만 재발급
#   bash systemd/setup-vnc.sh remove    # 제거 (unit 비활성화 + apt 삭제는 안 함)
#
# 보안 정책:
#   - localhost 바인딩 (127.0.0.1:5900) — 외부 직접 접속 차단
#   - SSH 터널 강제 (사용자 측 ssh -L 5900:localhost:5900 root@<vps_ip>)
#   - VNC password 1회 발급 후 /root/.x11vnc/passwd 보존 (mode 600)
#   - KTR Xvfb :99 영역 침범 안 함 — :98 만 attach
#
# 의존성: Xvfb :98 가 동작 중이어야 함 (보조자 측 인프라). 미실행 시 본 스크립트 안내 출력.

set -euo pipefail

MODE="${1:-install}"
SERVICE="vnc-billi.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_SRC="${SCRIPT_DIR}/${SERVICE}"
UNIT_DST="/etc/systemd/system/${SERVICE}"
PASSWD_DIR="/root/.x11vnc"
PASSWD_FILE="${PASSWD_DIR}/passwd"

[ "$(id -u)" -eq 0 ] || { echo "ERROR: root 권한 필요"; exit 1; }

case "$MODE" in
  remove)
    echo "=== VNC unit 제거 ==="
    systemctl disable --now "$SERVICE" 2>&1 || true
    rm -f "$UNIT_DST"
    systemctl daemon-reload
    echo "  unit 비활성화 완료. apt 패키지·password 파일은 그대로 둠 (수동 제거)."
    exit 0
    ;;
  password)
    if ! command -v x11vnc >/dev/null 2>&1; then
      echo "ERROR: x11vnc 미설치 — install 모드 먼저 실행"
      exit 1
    fi
    mkdir -p "$PASSWD_DIR"
    chmod 700 "$PASSWD_DIR"
    NEW_PASSWORD="$(openssl rand -base64 12 | tr -d '=+/' | cut -c1-12)"
    x11vnc -storepasswd "$NEW_PASSWORD" "$PASSWD_FILE"
    chmod 600 "$PASSWD_FILE"
    systemctl restart "$SERVICE" 2>&1 || true
    echo "==============================================="
    echo "  VNC 새 password (1회 표시 — 안전한 곳에 보관):"
    echo "      $NEW_PASSWORD"
    echo "==============================================="
    exit 0
    ;;
  install)
    : # fallthrough
    ;;
  *)
    echo "Usage: $0 [install|password|remove]"
    exit 1
    ;;
esac

echo "=== 1. apt 의존성 (x11vnc) ==="
apt-get update -qq
apt-get install -y x11vnc openssl
echo "  x11vnc: $(x11vnc -version 2>&1 | head -1)"

echo ""
echo "=== 2. Xvfb :98 동작 확인 ==="
if pgrep -af "Xvfb :98" >/dev/null 2>&1; then
  echo "  OK: Xvfb :98 실행 중"
  pgrep -af "Xvfb :98" | head -2
else
  cat <<'EOF'
  WARN: Xvfb :98 미실행 — VNC 가 attach 할 디스플레이 없음.

  보조자 측 (또는 root) 다음 명령으로 Xvfb 기동 후 본 스크립트 재실행:

      Xvfb :98 -screen 0 1024x768x24 -ac &

  (KTR :99 영역 침범 안 됨. :100 등 다른 디스플레이는 사용자 정책에 따름.)

EOF
  exit 1
fi

echo ""
echo "=== 2.5 x11vnc 옵션 사전 검증 (BILLI msg 459 정합) ==="
# unit ExecStart 가 사용하는 옵션을 x11vnc -opts 출력과 대조
# 미지원 옵션 발견 시 즉시 stop — 197-restart 루프 방지
REQUIRED_OPTS="display localhost rfbauth noxdamage forever shared rfbport"
opts_help="$(x11vnc -opts 2>&1)"
missing=""
for opt in $REQUIRED_OPTS; do
  if ! echo "$opts_help" | grep -E "^\s*-${opt}\b" >/dev/null; then
    missing="$missing $opt"
  fi
done
if [ -n "$missing" ]; then
  echo "  FAIL: 미지원 옵션 발견 —$missing"
  echo "  x11vnc 버전: $(x11vnc -version 2>&1 | head -1)"
  echo "  해결: vnc-billi.service ExecStart 옵션 정정 PR 발행 필요"
  exit 1
fi
echo "  OK: 모든 ExecStart 옵션 지원 ($REQUIRED_OPTS)"

echo ""
echo "=== 3. VNC password 발급 ==="
mkdir -p "$PASSWD_DIR"
chmod 700 "$PASSWD_DIR"
if [ -f "$PASSWD_FILE" ]; then
  echo "  기존 password 보존 (재발급 필요 시: $0 password)"
  GENERATED_PASSWORD=""
else
  GENERATED_PASSWORD="$(openssl rand -base64 12 | tr -d '=+/' | cut -c1-12)"
  x11vnc -storepasswd "$GENERATED_PASSWORD" "$PASSWD_FILE"
  chmod 600 "$PASSWD_FILE"
  echo "  새 password 발급 — 본 출력 끝부분에 표시"
fi

echo ""
echo "=== 4. systemd unit 설치 ==="
cp "$UNIT_SRC" "$UNIT_DST"
chmod 644 "$UNIT_DST"
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"
sleep 3

echo ""
echo "=== 5. 상태 ==="
systemctl status "$SERVICE" --no-pager | head -12

echo ""
echo "=== 6. 포트 바인딩 검증 ==="
if ss -ltn 2>/dev/null | grep -E "127\.0\.0\.1:5900|::1:5900" >/dev/null; then
  echo "  OK: 5900 localhost 바인딩 확인"
  ss -ltn 2>/dev/null | grep 5900
else
  echo "  WARN: 5900 바인딩 미감지"
  ss -ltn 2>/dev/null | grep -E ":5900|x11vnc" || true
fi

echo ""
echo "=== 7. 외부 노출 점검 ==="
ext_listen=$(ss -ltn 2>/dev/null | awk '$4 ~ /^0\.0\.0\.0:5900|^\*:5900/ {print}')
if [ -n "$ext_listen" ]; then
  echo "  ⚠️ FAIL: 5900 외부 바인딩 감지 — 즉시 systemctl stop $SERVICE 후 unit 검토"
  echo "    $ext_listen"
  exit 1
else
  echo "  OK: 외부 바인딩 없음 (localhost only)"
fi

echo ""
echo "============================================================"
echo "  VNC 셋업 완료"
echo "============================================================"
if [ -n "$GENERATED_PASSWORD" ]; then
  echo ""
  echo "  VNC password (1회 표시 — 안전한 곳에 보관):"
  echo "      $GENERATED_PASSWORD"
  echo ""
fi
echo "  사용자 측 SSH 터널 + VNC 접속:"
echo ""
echo "      # Mac/Linux 터미널에서:"
echo "      ssh -L 5900:127.0.0.1:5900 root@<VPS_IP>"
echo ""
echo "      # Mac VNC (Screen Sharing): Finder Cmd+K → vnc://localhost:5900"
echo "      # 또는 RealVNC Viewer / TigerVNC: localhost:5900"
echo "      # password: 위 표시값"
echo ""
echo "  단절 시 자동 재시작 (systemd Restart=on-failure)."
echo "  로그: journalctl -u $SERVICE -f / tail -f /var/log/x11vnc.log"
echo "  password 재발급: $0 password"
echo "  제거:           $0 remove"
