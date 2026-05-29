# Hermes AX Plugin

Agent eXecution Dashboard -- Hermes 에이전트의 워크플로우 실행을 시각화하고, 산출물을 관리하며, 사람과 에이전트가 협업하는 대시보드 플러그인.

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Hermes Dashboard (:9119)                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              AX Dashboard Plugin (/ax)                 │  │
│  │                                                        │  │
│  │   Kanban Board ─── Pipeline View ─── Artifact Viewer   │  │
│  │        │                │                   │          │  │
│  │        ▼                ▼                   ▼          │  │
│  │   워크플로우 관리   단계별 진행현황    산출물/코멘트 협업  │  │
│  └───────────────────────────────────────────────────────┘  │
│                            │                                 │
│                      FastAPI routers                          │
│        (plugin_api.py + dashboard/*_api.py modules)           │
│                            │                                 │
│                        SQLite DB                             │
│                            │                                 │
│             ┌──────────────┼──────────────┐                  │
│             ▼              ▼              ▼                  │
│        MCP Server      Skills       Plugin Hooks             │
│       (15 tools)    (ax-workflow)  (auto-trigger)            │
│             │              │              │                  │
│             └──────────────┼──────────────┘                  │
│                            ▼                                 │
│                     Hermes Agent                             │
└─────────────────────────────────────────────────────────────┘
```

### 3가지 통합 레이어

| 레이어 | 역할 | 파일 |
|--------|------|------|
| **MCP Server** | 에이전트가 AX 데이터를 도구로 읽기/쓰기 | `mcp_server.py` |
| **Skills** | 워크플로우 단계별 작업 지침 + 산출물 샘플 | `skills/ax-workflow/` |
| **Plugin Hooks** | 승인 이벤트 → Kanban 태스크 자동 생성 | `__init__.py` |

## Tech Stack

| 영역 | 기술 |
|------|------|
| Frontend | React 18, TypeScript 5, Vite 6 (IIFE 번들) |
| Backend | FastAPI, SQLite (WAL mode) |
| MCP | FastMCP SDK (stdio transport) |
| Plugin System | Hermes Dashboard Plugin API |

## Project Structure

```
hermes-ax-plugin/
├── dashboard/                      # AX 백엔드, public API allowlist 패치, 배포 번들
│   ├── manifest.json               # 플러그인 매니페스트
│   ├── plugin_api.py               # FastAPI 라우터 조립/등록 entrypoint
│   ├── common.py                   # 공통 응답/예외/SQLite helper
│   ├── db.py                       # DB 연결/WAL 설정
│   ├── db_schema.py                # SQLite schema migration/초기화
│   ├── seed.py                     # 기본 workflow/template/skill seed
│   ├── schemas.py, rows.py         # API schema/row serializer
│   ├── auth*.py                    # parent Dashboard token/legacy session 호환
│   ├── bootstrap.py                # 레거시 부트스트랩 관리자 upsert 호환
│   ├── workflows_api.py            # workflow instance/stage 전환 API
│   ├── artifacts_api.py            # 산출물 CRUD API
│   ├── artifact_storage.py         # 산출물 메타데이터/본문 저장
│   ├── artifact_files.py           # 산출물 파일 다운로드/저장
│   ├── approvals_api.py            # 승인 요청 API
│   ├── comments_api.py             # 산출물 코멘트 API
│   ├── definitions_api.py          # workflow/template 정의 API
│   ├── catalog_api.py              # 카탈로그/목록 API
│   ├── skills_api.py               # AX skill 관리 API
│   ├── stage_settings_api.py       # 단계별 설정 API
│   ├── stats_api.py                # 대시보드 통계 API
│   ├── activity.py                 # activity log 기록 helper
│   ├── events.py, events_api.py    # AX 이벤트 기록/조회 API
│   ├── slack_onboarding_api.py     # Slack Events 온보딩/자료 수집 webhook
│   ├── research_worker.py          # 자료조사 worker 실행 orchestration
│   ├── research_adapters.py        # mock/notebooklm/gemini adapter
│   ├── worker_api.py               # worker 실행/상태 API
│   └── dist/                       # 빌드 산출물
│       ├── index.js
│       └── style.css
├── src/                            # 프론트엔드 소스
│   ├── main.tsx                    # 진입점
│   ├── api/client.ts               # API 클라이언트
│   ├── context/AppContext.tsx      # 전역 상태
│   ├── components/
│   │   ├── App.tsx                 # AX plugin root component
│   │   ├── kanban/                 # 칸반 보드
│   │   ├── pipeline/               # 파이프라인 뷰 + 승인 패널 + activity timeline
│   │   ├── artifacts/              # 산출물 뷰어
│   │   ├── comments/               # 코멘트 시스템
│   │   ├── definition/             # 워크플로우 정의 에디터
│   │   ├── planning/               # 기획 자료조사 프로젝트 보드
│   │   ├── skills/                 # 스킬 관리 UI
│   │   ├── layout/                 # Header, UserPanel
│   │   └── shared/                 # 공통 dialog/component
│   ├── types/                      # TypeScript 타입 정의
│   └── styles/plugin.css           # 스타일시트
├── skills/                         # 에이전트 스킬 번들
│   └── ax-workflow/
│       ├── SKILL.md                # 메인 스킬 문서
│       ├── scripts/                # 결정적 MCP 호출 스크립트
│       └── reference/              # 산출물 샘플 + 플레이북 예시
├── docs/                           # 결정 기록과 상태 모델 문서
│   └── decisions/
│       ├── auth-and-persistence.md
│       └── planning-research-mvp-state-model.md
├── scripts/
│   └── patch_hermes_dashboard_public_api.py
├── mcp_server.py                   # MCP 서버 (stdio)
├── __init__.py                     # 플러그인 훅 + 자동 트리거
├── plugin.yaml                     # 에이전트 플러그인 매니페스트
├── test_api.py                     # API 테스트
├── Dockerfile                      # Railway/Docker 배포 이미지
├── package.json
├── tsconfig.json
└── vite.config.ts
```

## Installation

### 1. 플러그인 배포

```bash
# 공유 워크스페이스 저장소 클론
git clone https://github.com/ImJaeOne/hermes-shared-workspace.git

# Hermes 플러그인 디렉토리에 배포
cp -r hermes-shared-workspace/hermes-ax-plugin/ ~/.hermes/plugins/hermes-ax-plugin/
```

### 2. 플러그인 활성화

`~/.hermes/config.yaml`에 추가:

```yaml
plugins:
  enabled:
    - hermes-ax-plugin
```

### 3. MCP 서버 등록

`~/.hermes/config.yaml`에 추가:

```yaml
mcp_servers:
  hermes-ax:
    command: ~/.hermes/hermes-agent/venv/bin/python3
    args:
      - ~/.hermes/plugins/hermes-ax-plugin/mcp_server.py
    timeout: 30
```

### 4. MCP 서버 로드

```
hermes> /reload-mcp
```

### 5. 확인

```
hermes> /skills list
# ax-workflow 스킬이 표시되는지 확인

hermes> 기획 에이전트의 워크플로우 목록을 보여줘
# ax_list_workflows 도구가 호출되는지 확인
```

### 6. AX 인증 방향

AX Dashboard는 별도 로그인 UI/세션을 운영하지 않고, 상위 Hermes Dashboard가 주입하는 parent gate token을 사용합니다.

- `/api/plugins/hermes-ax/*` 요청은 상위 Dashboard의 `X-Hermes-Session-Token` 검증을 통과한 뒤 AX 라우터에 도달한다고 전제합니다.
- AX 프론트엔드는 `window.__HERMES_SESSION_TOKEN__`을 읽어 API 요청에 전달하며, 이 값을 AX 자체 세션 토큰처럼 저장하거나 삭제하지 않습니다.
- `/auth/session`은 parent token이 있는 요청을 `parent-dashboard` 사용자로 표시합니다.
- `/auth/login`은 AX 자체 로그인이 비활성화되었음을 나타내기 위해 `410 Gone`을 반환합니다.
- `/auth/logout`은 legacy AX cookie만 정리하며 parent Dashboard 인증은 무효화하지 않습니다.
- 공개 배포의 실제 사용자 인증은 Supabase Auth를 1차 선택지로 두고, Railway는 호스팅/볼륨/네트워킹 플랫폼으로 분리해 봅니다.
- 인증과 런타임 지식 저장 방식의 현재 결정은 `docs/decisions/auth-and-persistence.md`를 기준으로 합니다.

레거시 부트스트랩 관리자 환경변수는 기존 DB/세션 호환을 위해 남아 있을 수 있지만, AX UI 접근 제어의 기본 경로로 사용하지 않습니다.

### 7. 기획 자료조사 MVP 정보구조

1차 MVP는 Slack 회사명 채널을 AX 회사 프로젝트로 매핑하고, 실제 실행 범위는 `자료조사` 단계로 한정합니다.

- 예: Slack `#덕우전자` → AX 회사 프로젝트 `[덕우전자] 기획 자료조사`
- `자료 요청 중 → 자료 확인 대기 → 자료조사 실행 중 → 사용자 검토 대기 → 수정 요청 처리 중 → 자료조사 확정` 상태를 기준으로 진행합니다.
- 업무 상태는 `workflow_instances.status`가 아니라 `stage_definitions`와 `current_stage_id`로 표현합니다.
- Slack 채널/회사명/후속 단계 placeholder는 MVP에서는 `workflow_instances.metadata_json`에 저장합니다.
- 시놉시스(목차), 스토리보드, 원고는 다음 단계 placeholder로만 유지합니다.

상세 상태 모델과 DB 활용안은 `docs/decisions/planning-research-mvp-state-model.md`를 기준으로 합니다.

### 8. Slack 채널 온보딩 Webhook

Issue #21 기준 Slack 회사 채널 온보딩은 AX 플러그인 API의 아래 엔드포인트로 수신합니다.

```text
POST /api/plugins/hermes-ax/slack/events
```

로컬 Docker 또는 Railway 배포 환경에는 최소 아래 환경변수를 설정합니다.

| 환경변수 | 용도 |
|----------|------|
| `HERMES_AX_SLACK_SIGNING_SECRET` 또는 `SLACK_SIGNING_SECRET` | Slack Events API 서명 검증 |
| `HERMES_AX_SLACK_BOT_TOKEN` 또는 `SLACK_BOT_TOKEN` | `chat.postMessage`, `conversations.info` 호출 |
| `HERMES_AX_SLACK_BOT_USER_ID` 또는 `SLACK_BOT_USER_ID` | `member_joined_channel` 이벤트에서 기획팀 임팀장 봇 참여 여부 확인 |
| `HERMES_AX_SLACK_DRY_RUN=true` | 로컬/API 테스트에서 Slack으로 실제 메시지를 보내지 않고 전송 성공으로 기록 |
| `HERMES_AX_SLACK_ALLOW_UNSIGNED_EVENTS=true` | 로컬 fixture 테스트용. 운영에서는 사용하지 않음 |

Slack 이벤트가 들어오면 `#덕우전자` 같은 채널명에서 회사명 `덕우전자`를 추출하고, `planning_research_mvp_v1` 템플릿의 `[덕우전자] 기획 자료조사` 워크플로우와 매핑합니다. 매핑과 재시도 처리 상태는 SQLite의 `slack_channel_project_mappings`, `slack_event_receipts` 테이블에 저장됩니다.

로컬 검증은 실제 Slack 호출 없이 아래 API 테스트로 확인할 수 있습니다.

```bash
cd /Users/LIM/workspace/innodive-automation/hermes-ax-plugin
HERMES_AX_SLACK_DRY_RUN=true \
HERMES_AX_SLACK_SIGNING_SECRET=test-slack-signing-secret \
HERMES_AX_SLACK_BOT_USER_ID=UBOTLEAD \
~/.hermes/hermes-agent/venv/bin/python3 test_api.py
```

Docker 대시보드에서 수동 확인할 때는 포트 충돌을 피하기 위해 호스트 Hermes Dashboard가 `9119`를 쓰고 있는지 먼저 확인하고, 필요하면 Docker 호스트 포트를 `9120`처럼 분리합니다.

```bash
cd /Users/LIM/workspace/innodive-automation/hermes-ax-plugin

docker build -t hermes-ax-plugin:local .
docker rm -f hermes-ax-local 2>/dev/null || true

docker run --rm \
  --name hermes-ax-local \
  -p 9120:9119 \
  -e PORT=9119 \
  -e RUN_MODE=dashboard \
  -e HERMES_HOME=/data/.hermes \
  -e HERMES_AX_SESSION_COOKIE_SECURE=false \
  -e HERMES_AX_SLACK_DRY_RUN=true \
  -e HERMES_AX_SLACK_SIGNING_SECRET=test-slack-signing-secret \
  -e HERMES_AX_SLACK_BOT_USER_ID=UBOTLEAD \
  -v hermes_ax_data:/data \
  hermes-ax-plugin:local
```

접속 URL:

```text
http://127.0.0.1:9120/ax
```

Railway에서는 서비스 Root Directory를 `hermes-ax-plugin`으로 두고, Railway Volume을 `/data`에 마운트한 뒤 `HERMES_HOME=/data/.hermes`, `RUN_MODE=both` 또는 `dashboard`, Slack 관련 secret 환경변수를 설정합니다. 운영에서는 `HERMES_AX_SLACK_DRY_RUN`, `HERMES_AX_SLACK_ALLOW_UNSIGNED_EVENTS`를 끕니다.

Slack Events API는 Slack이 `X-Hermes-Session-Token` 같은 Dashboard 브라우저 세션 토큰을 보낼 수 없기 때문에 공개 webhook endpoint로 열려야 합니다. Docker 이미지는 빌드 시 Hermes Dashboard의 public API allowlist에 아래 exact path 하나만 추가합니다.

```text
/api/plugins/hermes-ax/slack/events
```

이 경로가 public으로 열리더라도 플러그인 라우터 내부에서 Slack signing secret을 먼저 검증합니다. 운영 배포에서 Slack URL Verification이 `Your URL didn't respond with the value of the challenge parameter.`로 실패하고 응답이 `{"detail":"Unauthorized"}`라면, 아직 이 이미지 패치가 배포되지 않았거나 production이 PR 반영 전 브랜치를 실행 중인 상태일 가능성이 큽니다.

Slack App의 Request URL은 trailing slash 없이 아래처럼 설정합니다.

```text
https://<railway-domain>/api/plugins/hermes-ax/slack/events
```

### 9. 자료조사 worker 실행 엔진

Issue #24 기준 자료조사 worker는 Enterprise API를 전제로 하지 않고, adapter 방식으로 실행됩니다. Slack 사용자는 자료를 올리고 결과를 받는 흐름만 사용하며, NotebookLM/MCP/쿠키 같은 설정 용어는 사용자-facing 메시지에 노출하지 않습니다.

| 환경변수 | 기본값 | 용도 |
|----------|--------|------|
| `HERMES_AX_RESEARCH_ENGINE` | `mock` | `mock`, `notebooklm_py`, `gemini_rag` 중 선택 |
| `HERMES_AX_RESEARCH_FALLBACK_ENGINE` | `mock` | 기본 엔진 실패/미설정 시 대체 엔진 |
| `HERMES_AX_RESEARCH_SKILL_ID` | `skill_001` | AX DB `skills` 테이블에서 로드할 자료조사 프롬프트 |
| `HERMES_AX_NOTEBOOKLM_AUTH_JSON` | 없음 | `notebooklm-py` storage state JSON secret 또는 파일 경로 |
| `HERMES_AX_NOTEBOOKLM_AUTH_PATH` | 없음 | `notebooklm-py` storage state 파일 경로 |
| `HERMES_AX_NOTEBOOKLM_PROFILE` | 없음 | `notebooklm-py` profile 이름 |
| `HERMES_AX_NOTEBOOKLM_KEEP_NOTEBOOKS` | `false` | 실행 후 NotebookLM 임시 노트북 보존 여부 |
| `HERMES_AX_NOTEBOOKLM_TIMEOUT` | `60` | NotebookLM 호출 timeout 초 |

`notebooklm_py` 엔진은 Google 계정 이메일/비밀번호를 환경변수에 넣지 않습니다. 대신 전용 Google 계정으로 한 번 로그인해 만든 browser storage state JSON을 secret으로 넣습니다. `/data/secrets/notebooklm-storage-state.json` 같은 값은 컨테이너 내부 예시 경로일 뿐 자동으로 존재하지 않으므로, 아래처럼 직접 만들고 Railway secret 또는 Docker volume mount로 전달해야 합니다.

로컬에서 storage state JSON을 만드는 예:

```bash
mkdir -p /Users/LIM/secrets/innodive-automation
cd /Users/LIM/workspace/innodive-automation/hermes-ax-plugin

python3 -m venv .venv-notebooklm-auth
source .venv-notebooklm-auth/bin/activate
pip install playwright
python -m playwright install chromium

AUTH_CAPTURE_SCRIPT=$(mktemp "${TMPDIR:-/tmp}/notebooklm-auth.XXXXXX.py")
trap 'rm -f "$AUTH_CAPTURE_SCRIPT"' EXIT
cat > "$AUTH_CAPTURE_SCRIPT" <<'PY'
from pathlib import Path
from playwright.sync_api import sync_playwright

out = Path('/Users/LIM/secrets/innodive-automation/notebooklm-storage-state.json')
out.parent.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto('https://notebooklm.google.com/', wait_until='domcontentloaded')
    input('브라우저에서 NotebookLM 전용 Google 계정으로 로그인한 뒤 NotebookLM 홈이 보이면 Enter를 누르세요: ')
    context.storage_state(path=str(out))
    browser.close()

print(str(out))
PY
python3 "$AUTH_CAPTURE_SCRIPT"
rm -f "$AUTH_CAPTURE_SCRIPT"
trap - EXIT
```

`python3 - <<'PY'`처럼 Python 코드를 표준입력 heredoc으로 바로 실행하면, `input()`이 터미널 입력을 읽지 못해 `EOFError: EOF when reading a line`이 납니다. 반드시 위처럼 임시 `.py` 파일로 저장한 뒤 실행합니다.

로컬 Docker에서 실제 NotebookLM을 붙여 확인할 때는 host 파일을 컨테이너 내부 경로로 read-only mount합니다.

```bash
-v /Users/LIM/secrets/innodive-automation/notebooklm-storage-state.json:/data/secrets/notebooklm-storage-state.json:ro \
-e HERMES_AX_RESEARCH_ENGINE=notebooklm_py \
-e HERMES_AX_RESEARCH_FALLBACK_ENGINE=mock \
-e HERMES_AX_NOTEBOOKLM_AUTH_PATH=/data/secrets/notebooklm-storage-state.json
```

Railway에서는 파일 경로를 만들기 어렵다면 `HERMES_AX_NOTEBOOKLM_AUTH_JSON`에 JSON 파일 내용 전체를 secret env로 넣는 방식이 가장 단순합니다. `HERMES_AX_NOTEBOOKLM_AUTH_PATH`를 쓰려면 해당 파일이 실제 배포 컨테이너 내부 경로에 존재해야 합니다. 이 JSON은 로그인 세션이므로 비밀번호급 secret으로 취급하고 Git, PR, Slack, artifact, activity log에 남기지 않습니다.

배포 환경에서 NotebookLM 인증 설정이 실제로 들어갔는지는 secret 값을 출력하지 말고 존재 여부와 JSON/path 유효성만 확인합니다. Railway UI에서는 대상 service의 `Variables`에서 key 존재 여부를 확인하고, 런타임 컨테이너에서는 `railway ssh` 접속 후 아래를 실행합니다.

```bash
python3 - <<'PY'
import json
import os
from pathlib import Path

keys = [
    'HERMES_AX_RESEARCH_ENGINE',
    'HERMES_AX_RESEARCH_FALLBACK_ENGINE',
    'HERMES_AX_NOTEBOOKLM_AUTH_JSON',
    'HERMES_AX_NOTEBOOKLM_AUTH_PATH',
    'HERMES_AX_NOTEBOOKLM_PROFILE',
]
for key in keys:
    value = os.getenv(key, '')
    if key.endswith('AUTH_JSON'):
        print(key, 'present=', bool(value), 'length=', len(value))
    else:
        print(key, 'value=', value if value else '<unset>')

auth_json = os.getenv('HERMES_AX_NOTEBOOKLM_AUTH_JSON', '').strip()
if auth_json:
    try:
        json.loads(auth_json)
        print('AUTH_JSON_valid_json=True')
    except Exception as exc:
        print('AUTH_JSON_valid_json=False', type(exc).__name__)

auth_path = os.getenv('HERMES_AX_NOTEBOOKLM_AUTH_PATH', '').strip()
if auth_path:
    p = Path(auth_path)
    print('AUTH_PATH_exists=', p.exists())
    print('AUTH_PATH_is_file=', p.is_file())
    print('AUTH_PATH_size=', p.stat().st_size if p.exists() else 0)
    if p.is_file():
        try:
            json.loads(p.read_text())
            print('AUTH_PATH_valid_json=True')
        except Exception as exc:
            print('AUTH_PATH_valid_json=False', type(exc).__name__)
PY
```

해석 기준:

- `HERMES_AX_RESEARCH_ENGINE=mock` 또는 unset이면 NotebookLM을 쓰지 않고 mock 엔진으로 실행됩니다.
- `HERMES_AX_RESEARCH_ENGINE=notebooklm_py`인데 `AUTH_JSON`/`AUTH_PATH`/`PROFILE`이 모두 없으면 실제 NotebookLM 실행은 불가능하고 fallback이 있으면 mock으로 넘어갑니다.
- `AUTH_JSON_present=True`와 `AUTH_JSON_valid_json=True`이면 Railway secret 방식이 최소 형식상 들어간 것입니다.
- `AUTH_PATH_exists=True`, `AUTH_PATH_is_file=True`, `AUTH_PATH_valid_json=True`이면 컨테이너 내부 파일 경로 방식이 최소 형식상 들어간 것입니다.
- `AUTH_PATH`와 `AUTH_JSON`을 둘 다 설정하면 현재 구현은 `AUTH_PATH`를 먼저 사용하므로, 파일 경로가 틀린 상태라면 `AUTH_JSON`이 있어도 실패할 수 있습니다. Railway에서는 보통 둘 중 하나만 쓰고, 가능하면 `AUTH_JSON` 방식을 권장합니다.

자료 확인 답변이 들어오면 `planning_worker_requests`에 queued request가 쌓입니다. 운영/테스트에서는 아래 endpoint로 실행할 수 있습니다.

```text
POST /api/plugins/hermes-ax/worker/requests/<request_id>/run
POST /api/plugins/hermes-ax/worker/run-queued?limit=1
```

local/CI 검증은 외부 인증 없이 mock adapter로 통과해야 합니다. `HERMES_AX_RESEARCH_ENGINE=notebooklm_py`인데 인증 정보나 패키지가 없으면 사용자에게는 비기술적 연결 문제로 안내하고, fallback이 설정되어 있으면 mock 또는 후속 `gemini_rag` 경로로 계속 진행합니다.

## Development

### 프론트엔드 빌드

```bash
cd ~/.hermes/plugins/hermes-ax-plugin

# 의존성 설치
npm install

# 개발 서버
npm run dev

# 프로덕션 빌드
npm run build
```

빌드 결과물은 `dashboard/dist/`에 생성됩니다.

### MCP 서버 테스트

```bash
# 서버 로드 테스트
~/.hermes/hermes-agent/venv/bin/python3 -c "
import sys; sys.path.insert(0, '.')
sys.path.insert(0, 'dashboard')
from mcp_server import mcp
print(f'Tools: {len(mcp._tool_manager._tools)}')
for name in sorted(mcp._tool_manager._tools.keys()):
    print(f'  - {name}')
"
```

### API 테스트

```bash
~/.hermes/hermes-agent/venv/bin/python3 test_api.py
```

## MCP Tools (15)

### 조회

| 도구 | 설명 |
|------|------|
| `ax_list_workflows` | 에이전트별 워크플로우 목록 |
| `ax_get_workflow` | 워크플로우 상세 (단계, 산출물, 코멘트) |
| `ax_get_artifact` | 산출물 상세 조회 |
| `ax_list_approvals` | 승인 대기 목록 |
| `ax_get_stats` | 전체 통계 |
| `ax_get_playbook` | 워크플로우 플레이북 조회 |
| `ax_poll_events` | 새 이벤트 폴링 |

### 생성/수정

| 도구 | 설명 |
|------|------|
| `ax_create_workflow` | 새 워크플로우 생성 |
| `ax_create_artifact` | 산출물 생성 (마크다운/JSON) |
| `ax_update_artifact` | 산출물 수정 |
| `ax_add_comment` | 코멘트 추가 |
| `ax_transition_stage` | 다음 단계로 전환 |
| `ax_decide_approval` | 승인/거절 처리 |
| `ax_save_playbook` | 플레이북 생성/업데이트 |

### 자동화

| 도구 | 설명 |
|------|------|
| `ax_create_kanban_task` | Kanban 태스크 생성 (에이전트 디스패치) |

## Agent Types & Pipelines

### Planning Agent (`planning`)

1차 기획 자료조사 MVP는 회사 프로젝트 중심으로 다음 상태를 사용합니다.

```
자료 요청 중 → 자료 확인 대기 → 자료조사 실행 중 → 사용자 검토 대기 → 수정 요청 처리 중 → 자료조사 확정
```

- Slack `#회사명` 채널은 AX 회사 프로젝트 `[회사명] 기획 자료조사`로 매핑합니다.
- 실제 실행 대상은 `자료조사`이며, 시놉시스(목차)/스토리보드/원고는 후속 단계 placeholder로 유지합니다.
- 상세 상태 모델은 `docs/decisions/planning-research-mvp-state-model.md`를 기준으로 합니다.

기존 샘플 데이터의 `Discovery → Brief Draft → Stakeholder Review → Handoff` 흐름은 AX Dashboard의 범용 단계/승인 기능을 보여주는 데모로만 취급합니다.

### Design Agent (`design`)

```
Research → Concept Sketch → Design Review(승인) → Handoff
```

디자인 파이프라인은 현재 데모/후속 자동화 영역이며, 기획 자료조사 MVP의 실행 범위에는 포함하지 않습니다.

## Skill Structure

`skills/ax-workflow/` 는 플러그인 로드 시 `~/.hermes/skills/ax-workflow/`에 자동 심볼릭 링크됩니다.

```
ax-workflow/
├── SKILL.md                          메인 문서
├── scripts/                          결정적 MCP 호출 스크립트
│   ├── create-workflow.md            워크플로우 생성 흐름
│   ├── transition-stage.md           단계 전환 흐름
│   ├── create-artifact.md            산출물 생성 흐름
│   ├── handle-approval.md            승인 처리 흐름
│   └── poll-and-dispatch.md          이벤트 폴링 + 자동 디스패치
└── reference/                        산출물 샘플 + 플레이북
    ├── playbook-sales.md             영업 파이프라인 플레이북
    ├── playbook-blog.md              블로그 콘텐츠 플레이북
    ├── sample-proposal.md            제안서 템플릿
    ├── sample-meeting-notes.md       미팅 노트 템플릿
    ├── sample-ticket.json            지원 티켓 JSON 샘플
    └── sample-brief.md              캠페인 브리프 템플릿
```

## HITL (Human-in-the-Loop)

승인이 필요한 단계(`transition_mode: approval_required`)에서는:

1. 에이전트가 `ax_transition_stage` 호출
2. 승인 요청 자동 생성, 워크플로우 상태 `pending_approval`
3. 사람이 대시보드에서 승인/거절
4. 승인 시 → 자동 전환 + `trigger_next` 이벤트 발행
5. Plugin hook이 감지 → Kanban 태스크 자동 생성 → 에이전트 디스패치

## REST API

대시보드 플러그인 API는 Hermes Dashboard를 통해 접근:

```
Base URL: http://127.0.0.1:9119/api/plugins/hermes-ax
```

주요 엔드포인트:

| Method | Path | 설명 |
|--------|------|------|
| GET | `/agents` | 에이전트 타입 목록 |
| GET | `/board/{agent_id}` | 칸반 보드 데이터 |
| GET | `/stats` | 전체 통계 |
| POST | `/workflows` | 워크플로우 생성 |
| GET | `/workflows/{id}` | 워크플로우 상세 |
| POST | `/workflows/{id}/transition` | 단계 전환 |
| POST | `/artifacts` | 산출물 생성 |
| GET | `/artifacts/{id}` | 산출물 상세 |
| POST | `/artifacts/{id}/comments` | 코멘트 추가 |
| GET | `/approvals` | 승인 목록 |
| POST | `/approvals/{id}/decide` | 승인/거절 |
| GET | `/events` | 이벤트 폴링 |
| GET | `/skills` | 스킬 목록 |
| GET/PUT | `/templates/{id}/definition` | 플레이북 조회/저장 |

## License

Private - TOKTOKHAN-DEV
