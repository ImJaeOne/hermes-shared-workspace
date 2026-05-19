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
│                      plugin_api.py                           │
│                       (FastAPI)                              │
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
├── dashboard/                      # 배포 번들 + 백엔드
│   ├── manifest.json               # 플러그인 매니페스트
│   ├── plugin_api.py               # FastAPI 라우터 (REST API)
│   └── dist/                       # 빌드 산출물
│       ├── index.js
│       └── style.css
├── src/                            # 프론트엔드 소스
│   ├── main.tsx                    # 진입점
│   ├── api/client.ts               # API 클라이언트
│   ├── context/AppContext.tsx       # 전역 상태
│   ├── components/
│   │   ├── kanban/                  # 칸반 보드
│   │   ├── pipeline/               # 파이프라인 뷰 + 승인 패널
│   │   ├── artifacts/              # 산출물 카드/뷰어
│   │   ├── comments/               # 코멘트 시스템
│   │   ├── definition/             # 워크플로우 정의 에디터
│   │   ├── skills/                 # 스킬 관리 UI
│   │   ├── layout/                 # Header, UserPanel
│   │   └── shared/                 # 공통 컴포넌트
│   ├── types/                      # TypeScript 타입 정의
│   └── styles/plugin.css           # 스타일시트
├── skills/                         # 에이전트 스킬 번들
│   └── ax-workflow/
│       ├── SKILL.md                # 메인 스킬 문서
│       ├── scripts/                # 결정적 MCP 호출 스크립트
│       └── reference/              # 산출물 샘플 + 플레이북 예시
├── mcp_server.py                   # MCP 서버 (15 tools, stdio)
├── __init__.py                     # 플러그인 훅 + 자동 트리거
├── plugin.yaml                     # 에이전트 플러그인 매니페스트
├── test_api.py                     # API 테스트
├── package.json
├── tsconfig.json
└── vite.config.ts
```

## Installation

### 1. 플러그인 배포

```bash
# 저장소 클론
git clone https://github.com/TOKTOKHAN-DEV/hermes-ax-plugin.git

# Hermes 플러그인 디렉토리에 배포
cp -r hermes-ax-plugin/ ~/.hermes/plugins/hermes-ax-plugin/
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

hermes> 영업 에이전트의 워크플로우 목록을 보여줘
# ax_list_workflows 도구가 호출되는지 확인
```

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

### Sales Agent (`sales`)
```
Lead In → Qualification → Proposal(승인) → Negotiation → Close(승인)
```

### Marketing Agent (`marketing`)
```
블로그:   주제 선정 → 초안 작성 → 리뷰(승인) → 발행
카드뉴스: 기획 → 디자인 → 카피 작성 → 승인(승인) → 배포
```

### Support Agent (`support`)
```
Ticket Created → Triage → Investigation → Resolution → Follow-up
```

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
