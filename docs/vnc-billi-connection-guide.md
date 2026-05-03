# VNC Connection Guide — BILLI MT5 GUI 1회 로그인

**대상**: BILLI 사용자 (Phh) — Bybit-Live MT5 1회 GUI 로그인
**근거**: BILLI ORDER msg 455 P2-003-R2 Phase 2
**보안**: localhost only + SSH 터널 강제, 외부 노출 0

---

## 0. 사전 조건

VPS 측 (보조자 또는 root):
1. `bash systemd/setup-vnc.sh install` 1회 완료
2. Xvfb :98 동작 중 (`pgrep -af "Xvfb :98"`)
3. VNC password 발급됨 (setup 출력 또는 `setup-vnc.sh password` 재발급)

사용자 측:
- VPS SSH 접근 가능 (root 또는 root 위탁 계정)
- VNC 클라이언트
  - **Mac**: 내장 Screen Sharing (Finder · Cmd+K)
  - **Windows**: TigerVNC Viewer / RealVNC Viewer
  - **Linux**: Remmina / vinagre

---

## 1. SSH 터널 (외부 노출 방지)

x11vnc 는 127.0.0.1:5900 에만 바인딩되어 있어 SSH 터널 없이는 접속 불가.

```
ssh -L 5900:127.0.0.1:5900 root@<VPS_IP>
```

- `<VPS_IP>` — Hostinger VPS 의 IPv4 (예: 76.13.214.245)
- 본 SSH 세션을 열어둔 동안만 VNC 접속 가능
- 터널 종료 = SSH 세션 닫기

검증 (별도 로컬 터미널에서):

```
nc -z localhost 5900 && echo "tunnel OK"
```

---

## 2. VNC 클라이언트 접속

### Mac (내장 Screen Sharing)

1. Finder → Cmd+K (서버에 연결)
2. 주소: `vnc://localhost:5900`
3. password 입력 (setup-vnc.sh 출력값)
4. 연결 → 검은 데스크탑 (또는 MT5 창) 표시

### TigerVNC / RealVNC Viewer

1. Connect to: `localhost:5900`
2. Authentication: VNC password
3. 연결 완료

---

## 3. MT5 GUI 작업 단계

### 3.1 MT5 창 활성화

VNC 접속 후 화면이 검은 색이고 MT5 창이 안 보이면, VPS 터미널에서:

```
DISPLAY=:98 wine "/root/Klys-LAB/BILLI/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe" &
```

(보조자 측에서 실행. MT5 창이 :98 디스플레이에 띄워져 VNC 로 보임.)

### 3.2 Bybit-Live 계정 로그인

1. MT5 메뉴: **File → Login to Trade Account** (단축키 Ctrl+L 가능)
2. **Server**: `Bybit-Live`
3. **Login**: <Bybit MT5 account number>
4. **Password**: <비밀번호>
5. **Save Account Information**: ✅ 체크 (자격증명 보존)
6. **Login** 클릭

기대 — 우하단 "Connection X kbps Y ms" 표시. 좌측 Navigator 에 계정 표시.

### 3.3 XAUUSD+ 심볼 추가

1. **View → Symbols** (또는 Ctrl+U)
2. 좌측 트리에서 `Bybit Forex (CFD) → Metals → XAUUSD+` 찾기
3. **Show** 버튼 → 우측 Market Watch 에 등록
4. **OK** 닫기

### 3.4 Tick history 다운로드

1. Market Watch 에서 XAUUSD+ 우클릭 → **Specification**
2. 또는 직접: **Tools → History Center** (또는 F2)
3. XAUUSD+ M1 (또는 Tick) 선택 → **Download** 버튼
4. 다운로드 진행 표시줄 → 완료까지 대기 (수십 초 ~ 몇 분)

### 3.5 로그아웃 (자격증명 보존)

자격증명 (Login·Password) 은 MT5 가 암호화하여 저장. 별도 "로그아웃" 없이 MT5 창 닫기만 해도 됨.

```
File → Exit (또는 창 X)
```

다음 MT5 기동 시 자동 재로그인 (Save Account Information ✅ 효과).

---

## 4. VNC 세션 종료

1. VNC 클라이언트 창 닫기
2. SSH 터널 종료 (SSH 세션 종료)
3. VPS 측 x11vnc 는 systemd 가 살려둠 (다음 사용자 접속 시 즉시 재사용 가능)

---

## 5. 정리·재사용

### 자주 쓰는 명령

```
# VNC password 재발급
bash /root/Klys-LAB/agent-base/systemd/setup-vnc.sh password

# VNC 상태 확인
systemctl status vnc-billi.service
journalctl -u vnc-billi.service -n 20

# VNC 일시 중단 (필요 시)
systemctl stop vnc-billi.service

# VNC 재시작
systemctl start vnc-billi.service

# VNC 완전 제거 (apt 패키지·password 보존)
bash /root/Klys-LAB/agent-base/systemd/setup-vnc.sh remove
```

### 보안 점검 (정기)

```
ss -ltn | grep 5900
# 기대: 127.0.0.1:5900 또는 [::1]:5900 만, 0.0.0.0:5900 절대 금지
```

---

## 6. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `nc -z localhost 5900` 실패 | SSH 터널 끊김 | SSH 재연결 |
| VNC 검은 화면 | Xvfb :98 동작 + 창 없음 | MT5 startup 명령 (§3.1) |
| MT5 로그인 거부 | 잘못된 server·credentials | Bybit MT5 계정 정보 재확인 |
| XAUUSD+ Symbols 에 없음 | Bybit account type 또는 트리 위치 차이 | Symbols 검색창 "XAU" 검색 |
| tick 다운로드 멈춤 | 네트워크·broker 측 rate limit | 잠시 후 재시도 |
| `0.0.0.0:5900` 바인딩 발견 | systemd unit 변조 | 즉시 stop + setup-vnc.sh 재실행 + 감사 |

---

## 7. 다음 단계 (Phase 3)

1. 사용자 GUI 로그인 + XAUUSD+ + tick 다운로드 완료 보고 (Telegram)
2. 설계자 → orders/P2-003-R2-st-execution.md 발행
3. 보조자 (또는 수동 트리거) Strategy Tester 실행
4. mt5-results/P2-003/ + reports/P2-003-R2-impl.md 산출

---

**보안 원칙 재확인**

- VNC password 는 1회 발급 후 재발급 가능. Telegram 등 secure-not 채널에 paste 시 위험.
- SSH 터널 없이 VNC 접속 절대 금지 (localhost 바인딩이 강제하나 unit 변조 시 위험).
- 자격증명 (Bybit 계정·password·MFA) 은 절대 commit·log·script 노출 금지.
