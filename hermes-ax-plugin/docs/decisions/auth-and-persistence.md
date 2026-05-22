# AX 인증 및 런타임 지식 저장 방식 결정

상태: Accepted working decision
작성일: 2026-05-22

## 배경

현재 AX Dashboard는 자체 로그인 UI/세션을 기본 인증 경로로 사용하지 않는다. AX 프론트엔드는 상위 Hermes Dashboard가 주입하는 `window.__HERMES_SESSION_TOKEN__`을 읽어 `/api/plugins/hermes-ax/*` 요청에 `X-Hermes-Session-Token`으로 전달하고, AX 백엔드는 이 parent token이 있으면 parent dashboard 인증을 통과한 요청으로 취급한다.

기존 README에는 공개 배포 인증 후보로 Supabase Auth, Railway/외부 auth, parent Dashboard 앞단 보호 계층이 열려 있었지만, 제품 인증과 Railway 호스팅/볼륨 책임을 분리해 명확히 정한다.

## 결정

### 1. 공개 배포 사용자 인증은 Supabase Auth를 1차 선택한다

- Supabase Auth를 사용자 가입/로그인, 세션, JWT 검증, 사용자 식별의 기본 인증 계층으로 둔다.
- Railway는 애플리케이션 호스팅, 환경변수, 볼륨, 네트워킹을 담당하는 배포 플랫폼으로 본다.
- Railway의 가이드가 제시하는 "session-based auth with Postgres" 방식은 커스텀 구현 대안이지, AX의 1차 인증 Provider로 두지 않는다.
- 초기 내부 테스트에서 임시 보호가 필요하면 Railway/프록시/앞단 보호 계층을 보조적으로 붙일 수 있지만, 앱 내부 사용자/역할/감사 로그의 기준 ID는 Supabase Auth 사용자로 통일한다.

### 2. AX API는 parent token 계약을 유지하되, public auth는 parent 앞단에서 해결한다

- AX 플러그인은 계속 `X-Hermes-Session-Token` 기반 parent Dashboard 인증 계약을 유지한다.
- 공개 배포에서는 상위 Dashboard 또는 앞단 미들웨어가 Supabase 세션/JWT를 검증하고, AX 요청이 parent gate를 통과하도록 한다.
- 현재 `parent-dashboard` pseudo user는 임시 호환 사용자로 유지하되, Supabase Auth 도입 후에는 Supabase user id/email/role을 AX `users` 및 `activity_logs`에 매핑하는 방향으로 확장한다.
- AX 자체 `/auth/login`은 기본 경로로 되살리지 않는다. 필요하면 legacy 호환/로컬 디버깅 용도에 한정한다.

### 3. Hermes native memory/skills는 기본적으로 파일 기반이며 Railway Volume에 둔다

Railway 배포에서는 다음을 표준으로 한다.

```text
Railway Volume mount: /data
HERMES_HOME: /data/.hermes
```

- Hermes native memory는 `$HERMES_HOME/memories/MEMORY.md`, `$HERMES_HOME/memories/USER.md` 같은 파일로 저장된다.
  - 기본 내장 memory는 DB upsert가 아니라 파일 기반 persist이다.
  - 세션 시작 시 system prompt에 스냅샷으로 주입되며, 세션 중 변경은 다음 세션부터 prompt에 반영된다.
- Hermes native skills는 `$HERMES_HOME/skills/<skill>/SKILL.md` 및 `references/`, `templates/`, `scripts/`, `assets/` 파일 트리로 저장된다.
  - agent-created/agent-patched skill도 기본적으로 파일 변경이다.
  - Curator 사용 정보 같은 부가 상태는 skills 디렉터리 아래 sidecar 파일로 관리된다.
- 따라서 서버에서 에이전트가 자가 개선한 memory/skills는 같은 Railway Volume을 유지하는 한 서버 런타임에 남는다.
- 단, 이 변경은 자동으로 Git source of truth에 반영되지 않는다. 조직 표준으로 승격할 항목은 별도 review 후 repo에 PR로 반영한다.

### 4. AX Dashboard의 워크플로우/스킬 카탈로그/활동 로그는 SQLite DB에 저장한다

AX 플러그인 제품 데이터는 Hermes native memory/skills와 분리한다.

- DB 경로: `$HERMES_HOME/plugins/hermes-ax-plugin/ax.db`
- WAL 모드 사용: 확인 시 `ax.db`, `ax.db-wal`, `ax.db-shm`을 함께 봐야 한다.
- AX DB에는 workflow templates/instances/stages/artifacts/comments/approvals/users/activity logs 및 AX UI의 `skills` 테이블이 들어간다.
- AX UI의 `skills` 테이블은 워크플로우 실행/표준화를 위한 제품 데이터이며, Hermes native `$HERMES_HOME/skills` 파일 트리와 동일한 저장소로 취급하지 않는다.
- 부트스트랩 관리자나 parent-dashboard user 같은 호환 레코드는 필요 시 upsert될 수 있지만, 이는 AX DB 내부 상태에 한정한다.

### 5. 자가 진화는 learner 경로 + 관리자 승인 후 적용한다

공유 회사 배포에서 모든 일반 대화가 곧바로 조직 표준 skill/memory/prompt를 바꾸면 팀별 스타일 드리프트와 감사 추적 문제가 생긴다. 따라서 다음 경계를 둔다.

- 일반 사용자 대화: 현재 작업 산출물/워크플로우 데이터만 수정한다.
- learner 전용 경로: 승인된 대화/산출물에서 skill, prompt, playbook, template 개선 후보를 만든다.
- 관리자 리뷰: 후보를 검토해 승인하면 적용한다.
- 적용 위치:
  - 런타임 즉시 반영이 필요한 것은 Railway Volume의 `$HERMES_HOME`에 적용한다.
  - 장기 표준/재배포/새 환경에 필요한 것은 repo에 PR로 반영한다.

## 운영 원칙

1. Railway Volume은 운영 중인 Hermes/AX 런타임 상태의 지속 저장소다.
2. Git repo는 배포 코드, seed, 표준 skill/playbook/template의 장기 source of truth다.
3. Supabase Auth는 공개 사용자 인증의 source of truth다.
4. AX SQLite DB는 AX 제품 데이터와 감사 로그의 source of truth다.
5. Hermes native memory/skills는 파일 기반 런타임 지식이며, 조직 표준으로 승격하려면 review/PR 경로를 거친다.
