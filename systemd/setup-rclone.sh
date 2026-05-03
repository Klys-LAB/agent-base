#!/usr/bin/env bash
# rclone Google Drive handoff 마운트 셋업 (BILLI msg 447, ADR-001 D7 정합)
#
# 사용 시나리오:
#   1. 본 스크립트 실행 → apt 설치 + 마운트 포인트 생성 + rclone config 가이드 출력
#   2. 사용자: rclone config 수동 1회 (OAuth 토큰 발급)
#   3. 본 스크립트 재실행 → systemd unit 설치·활성화·검증
#
# 권한: root 만 (다른 사용자 접근 차단, 마운트 700)

set -euo pipefail

MOUNT_POINT="/root/Klys-LAB/handoff"
SERVICE="rclone-handoff.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_SRC="${SCRIPT_DIR}/${SERVICE}"
UNIT_DST="/etc/systemd/system/${SERVICE}"
RCLONE_CONFIG="/root/.config/rclone/rclone.conf"

[ "$(id -u)" -eq 0 ] || { echo "ERROR: root 권한 필요"; exit 1; }

echo "=== 1. apt 의존성 (rclone + fuse3) ==="
apt-get update -qq
apt-get install -y rclone fuse3
echo "  rclone: $(rclone --version | head -1)"
echo "  fuse3:  $(fusermount3 --version 2>&1 | head -1)"

echo ""
echo "=== 2. 마운트 포인트 ==="
mkdir -p "$MOUNT_POINT"
chmod 700 "$MOUNT_POINT"
echo "  $MOUNT_POINT (700)"

echo ""
echo "=== 3. rclone config 확인 ==="
if [ -f "$RCLONE_CONFIG" ] && rclone listremotes --config "$RCLONE_CONFIG" 2>/dev/null | grep -q "^gdrive:$"; then
    echo "  OK: gdrive remote 설정됨"
    echo "  test: rclone lsd gdrive:Klys-LAB/BILLI/handoff/ --config $RCLONE_CONFIG --max-depth 1 | head -5"
    rclone lsd "gdrive:Klys-LAB/BILLI/handoff/" --config "$RCLONE_CONFIG" --max-depth 1 2>&1 | head -10 || {
        echo "  WARN: gdrive 접근 실패 — OAuth 토큰 만료 또는 권한 부족"
    }
else
    cat <<'EOF'

  rclone config 미설정 — 다음 명령 수동 1회 실행 후 본 스크립트 재실행:

      rclone config

    가이드:
      1) n              (new remote)
      2) name: gdrive
      3) Storage: drive (Google Drive 검색)
      4) client_id:     (빈 값, Enter)
      5) client_secret: (빈 값, Enter)
      6) scope: 1       (drive — full access)
      7) service_account_file: (빈 값, Enter)
      8) Edit advanced config: n
      9) Use auto config: n      (헤드리스 VPS — 로컬 머신에서 인증)
     10) → 출력된 URL 을 로컬 브라우저에서 열기
         → Google 계정 로그인 후 동의
         → 결과 토큰 (긴 JSON) 을 SSH 세션에 paste
     11) Configure as team drive: n
         (Klys-LAB 가 공유 드라이브이면 y → 드라이브 ID 선택)
     12) y/n: y         (저장)
     13) q              (종료)

  헤드리스 OAuth 보조 (로컬 Mac 에서 1회):
      Mac:  rclone authorize "drive"
      → 로컬 브라우저 인증 → access_token paste 받기
      VPS:  rclone config 단계 10 에서 그 토큰 paste

EOF
    exit 1
fi

echo ""
echo "=== 4. systemd unit 설치 ==="
cp "$UNIT_SRC" "$UNIT_DST"
chmod 644 "$UNIT_DST"
systemctl daemon-reload
systemctl enable "$SERVICE"
echo "  $UNIT_DST 등록"

echo ""
echo "=== 5. (재)시작 ==="
systemctl restart "$SERVICE"
sleep 4

echo ""
echo "=== 6. 상태 ==="
systemctl status "$SERVICE" --no-pager | head -15

echo ""
echo "=== 7. 마운트 검증 ==="
if mountpoint -q "$MOUNT_POINT"; then
    echo "  OK: mountpoint 활성"
    echo "  test ls:"
    ls "$MOUNT_POINT" 2>&1 | head -10
    today="$(date -u +%Y-%m-%d)"
    if [ -d "$MOUNT_POINT/$today" ]; then
        echo "  ✓ $MOUNT_POINT/$today 접근 가능"
    else
        echo "  (today 디렉터리 $today 없음 — 정상, 사용 시 생성)"
    fi
else
    echo "  FAIL: mount 실패"
    echo "  로그: tail -20 /var/log/rclone-handoff.log"
    tail -20 /var/log/rclone-handoff.log 2>&1
    exit 1
fi

echo ""
echo "=== 완료 ==="
echo "  사용 예: ls $MOUNT_POINT/$(date -u +%Y-%m-%d)/"
echo "  로그:    journalctl -u $SERVICE -f"
echo "          tail -f /var/log/rclone-handoff.log"
echo "  재부팅 후 자동 마운트: systemctl is-enabled $SERVICE = enabled"
