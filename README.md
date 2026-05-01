# agent-base

BILLI 보조자 인프라 — VPS 다목적 agent 골격 (ADR-001, 2026-05-02).

## 설계 원칙 (ADR-001 D1~D7)

- **재사용 자산**: core/ 골격은 BILLI·KTR·회사 프로젝트 모두 import 가능
- **잔재 0**: `projects/<proj>/dependencies.txt` 추적, 진입 시 추가·종료 시 회수
- **OS-agnostic**: bash·python3·git·gh·jq 외 OS-종속 도구 금지
- **가동**: systemd unit `agent@<project>.service`

## 구조 (D4)

```
agent-base/
├── core/
│   ├── poller/       orders 폴링·PR state 감지
│   ├── dispatch/     claude -p OAuth wrapper
│   ├── git_ops/      commit·push·PR open/close
│   ├── notify/       Telegram·기타 알림
│   ├── lock/         idempotency·timeout·재시도
│   ├── log/          구조화 로그
│   └── lib/          config·env 로더
├── projects/
│   └── billi/        BILLI 프로젝트 설정
│       ├── config.yml
│       ├── secrets.env  (gitignored)
│       ├── repo → /root/Klys-LAB/BILLI  (symlink, VPS 전용)
│       └── hooks/
└── bin/
    └── agent         CLI 진입점
```

## 의존성 (D7)

필수: `bash · python3 · git · gh · jq`

## 관련 repo

- [Klys-LAB/BILLI](https://github.com/Klys-LAB/BILLI) — BILLI 5주체 프로젝트
