---
name: ax-workflow
description: "Hermes AX Dashboard 워크플로우 관리 — 단계별 작업 수행, 산출물 생성, 승인 요청"
version: 1.0.0
metadata:
  hermes:
    tags: [workflow, ax-dashboard, kanban, automation]
---

# AX 워크플로우 관리 스킬

AX Dashboard는 에이전트 타입별 워크플로우를 칸반 보드로 관리하는 시스템입니다.
이 스킬은 워크플로우의 각 단계에서 에이전트가 수행해야 할 작업을 정의합니다.

## 스킬 구조

```
ax-workflow/
├── SKILL.md                          ← 이 파일 (개요 + MCP 도구 + 단계별 지침)
├── scripts/                          ← 결정적 MCP 호출 스크립트
│   ├── create-workflow.md            워크플로우 생성 흐름
│   ├── transition-stage.md           단계 전환 흐름
│   ├── create-artifact.md            산출물 생성 흐름
│   ├── handle-approval.md            승인 처리 흐름
│   └── poll-and-dispatch.md          이벤트 폴링 + 자동 디스패치
└── reference/                        ← 산출물 샘플 + 플레이북 예시
    ├── playbook-sales.md             영업 파이프라인 플레이북
    ├── playbook-blog.md              블로그 콘텐츠 플레이북
    ├── sample-proposal.md            제안서 템플릿
    ├── sample-meeting-notes.md       미팅 노트 템플릿
    ├── sample-ticket.json            지원 티켓 JSON 샘플
    └── sample-brief.md               캠페인 브리프 템플릿
```

**사용법**:
- 작업 전 `scripts/` 의 해당 스크립트를 읽고 MCP 호출 순서를 따른다
- 산출물 작성 시 `reference/` 의 샘플을 참고하여 구조와 톤을 맞춘다
- 플레이북은 `reference/playbook-*.md` 를 기반으로 `ax_save_playbook`으로 커스터마이징한다

## 시스템 개요

### 에이전트 타입
| ID | 이름 | 설명 |
|----|------|------|
| `sales` | Sales Agent | 영업 파이프라인 — 리드 유입부터 계약 완료까지 |
| `marketing` | Marketing Agent | 캠페인 파이프라인 — 기획부터 분석까지 |
| `support` | Support Agent | 티켓 해결 파이프라인 — 접수부터 후속 조치까지 |

### 워크플로우 템플릿
| ID | 에이전트 | 이름 |
|----|----------|------|
| `sales_pipeline_v1` | sales | Sales Pipeline v1 |
| `mktg_blog` | marketing | 블로그 |
| `mktg_cardnews` | marketing | 카드뉴스 |
| `support_pipeline_v1` | support | Support Pipeline v1 |

---

## MCP 도구 사용법

### 조회 도구
- `ax_list_workflows(agent_id, template_id?)` — 워크플로우 목록
- `ax_get_workflow(workflow_id)` — 워크플로우 상세 (단계, 산출물, 코멘트)
- `ax_get_artifact(artifact_id)` — 산출물 상세
- `ax_list_approvals(status?, workflow_id?)` — 승인 대기 목록
- `ax_get_stats()` — 전체 통계
- `ax_poll_events(since?, limit?)` — 새 이벤트 폴링

### 생성/수정 도구
- `ax_create_workflow(template_id, title, priority?, assignee?)` — 워크플로우 생성
- `ax_create_artifact(workflow_id, stage_id, artifact_type, title, content, content_type?, status?)` — 산출물 생성
- `ax_update_artifact(artifact_id, title?, content?, content_type?, status?)` — 산출물 수정
- `ax_add_comment(artifact_id, author, body)` — 코멘트 추가
- `ax_transition_stage(workflow_id, to_stage_id, note?)` — 단계 전환
- `ax_decide_approval(approval_id, decision, decided_by, note?)` — 승인/거절

### 자동화 도구
- `ax_create_kanban_task(workflow_id, stage_id, title?, body?, priority?)` — Kanban 태스크 생성

---

## 단계별 작업 지침

### 1. 영업 (Sales Pipeline)

#### Lead In (리드 유입)
- **산출물**: `contact_info` (application/json)
- **작업**: 리드 기본 정보 수집 (이름, 회사, 이메일, 전화, 유입 경로)
- **포맷**: JSON `{"name": "", "company": "", "email": "", "phone": "", "source": ""}`

#### Qualification (검증)
- **산출물**: `email`, `meeting_notes`
- **작업**: 초기 연락 이메일 발송, 미팅 진행 후 노트 작성
- **이메일**: 전문적이고 친근한 톤, 가치 제안 포함, CTA 포함
- **미팅 노트**: 참석자, 핵심 논의사항, 의사결정, 액션 아이템

#### Proposal (제안) — `approval_required`
- **산출물**: `proposal`, `email`
- **작업**: 고객 맞춤 솔루션 제안서 작성
- **구조**: 요약 → 고객 현황 → 제안 솔루션 → ROI → 일정 → 가격 → 팀 소개
- **승인**: 매니저 승인 필요. `ax_transition_stage` 호출 시 자동으로 승인 요청 생성됨.

#### Negotiation (협상)
- **산출물**: `contract`, `email`
- **작업**: 계약 조건 협의, 계약서 초안 작성
- **주의**: 법무 검토 필요 사항은 코멘트로 기록

#### Close (계약) — `approval_required`
- **산출물**: `contract`, `report`
- **작업**: 최종 계약서 확정, 계약 완료 보고서 작성
- **승인**: 매니저 + 디렉터 승인 필요

---

### 2. 마케팅 — 블로그 (mktg_blog)

#### 주제 선정 (topic)
- **산출물**: `brief`
- **작업**: 블로그 주제 기획 (타겟 독자, 핵심 메시지, 키워드)

#### 초안 작성 (draft)
- **산출물**: `content_draft`
- **작업**: 블로그 본문 초안 작성 (마크다운)
- **구조**: 헤드라인 → 도입 → 본문 (섹션별) → 결론 → CTA

#### 리뷰 (review) — `approval_required`
- **산출물**: `content_draft` (수정본)
- **작업**: 초안 리뷰, 피드백 반영
- **승인**: 매니저 승인 필요

#### 발행 (publish)
- **산출물**: `report`
- **작업**: 발행 후 성과 보고서 작성 (조회수, 전환율, 공유 수)

---

### 3. 마케팅 — 카드뉴스 (mktg_cardnews)

#### 기획 (plan)
- **산출물**: `brief`
- **작업**: 카드뉴스 주제, 슬라이드 구성, 핵심 메시지 기획

#### 디자인 (design)
- **산출물**: `content_draft`
- **작업**: 슬라이드별 비주얼 컨셉 및 레이아웃 설명

#### 카피 작성 (copy)
- **산출물**: `content_draft`
- **작업**: 슬라이드별 카피 텍스트 작성

#### 승인 (approve) — `approval_required`
- **산출물**: `report`
- **작업**: 최종 검토 및 승인 요청
- **승인**: 매니저 승인 필요

#### 배포 (distribute)
- **산출물**: `report`
- **작업**: 배포 채널별 결과 보고 (도달, 반응, 전환)

---

### 4. 지원 (Support Pipeline)

#### Ticket Created (접수)
- **산출물**: `ticket` (application/json)
- **작업**: 티켓 기본 정보 등록
- **포맷**: JSON `{"customer": "", "issue": "", "severity": "", "category": "", "reported_at": ""}`
- **심각도**: critical (1시간), high (4시간), medium (24시간), low (72시간)

#### Triage (분류)
- **산출물**: `ticket`, `log`
- **작업**: 심각도 분류, 카테고리 태깅, 초기 분석 로그 작성

#### Investigation (조사)
- **산출물**: `log`, `meeting_notes`
- **작업**: 근본 원인 조사, 로그 분석, 관련 팀 미팅

#### Resolution (해결)
- **산출물**: `resolution_note`
- **작업**: 해결 방안 적용, 근본 원인 / 수정 내용 / 검증 결과 문서화

#### Follow-up (후속조치)
- **산출물**: `email`, `report`
- **작업**: 고객 안내 이메일 발송, 최종 보고서 작성

---

## 산출물 작성 규칙

### content_type 별 포맷
| content_type | 용도 | 작성 규칙 |
|-------------|------|----------|
| `text/markdown` | 이메일, 보고서, 제안서, 노트 | 마크다운 형식. 제목(##), 리스트, 테이블 활용 |
| `application/json` | 연락처, 티켓 | 구조화된 JSON. 필드명은 snake_case |
| `text/plain` | 로그 | 타임스탬프 포함 텍스트 (`YYYY-MM-DD HH:MM - 내용`) |

### status 흐름
- `draft` → 초안 작성 중
- `final` → 완성/확정됨
- `archived` → 보관됨

---

## 승인 처리 (HITL)

### 승인이 필요한 단계
`transition_mode: approval_required`가 설정된 단계로 전환 시 자동으로 승인 요청이 생성됩니다.

### 처리 흐름
1. `ax_transition_stage` 호출 → 승인 요청 자동 생성, 워크플로우 상태 `pending_approval`
2. 승인 대기 중 → 다른 작업 수행 가능 (다른 워크플로우)
3. `ax_list_approvals(status="pending")` → 대기 중인 승인 확인
4. `ax_decide_approval(approval_id, "approved", decided_by, note)` → 승인 후 자동 전환
5. 거절 시 → 워크플로우가 현재 단계에 머물며 `active`로 복원

### 주의사항
- 승인 대기 중인 워크플로우에는 산출물 추가/수정은 가능하지만 단계 전환은 불가
- 승인 거절 시 피드백(코멘트)을 확인하고 산출물을 보완한 후 다시 전환 요청

---

## 자동 작업 흐름

### 이벤트 폴링 방식
```
1. ax_poll_events(since=마지막_커서) 로 새 이벤트 확인
2. 'approval_approved' 또는 'stage_changed' 이벤트 감지
3. 해당 워크플로우의 현재 단계 확인
4. 단계별 지침에 따라 산출물 생성
5. 완료 후 다음 단계로 전환
```

### 에러 시 행동
- DB 오류 → 3회 재시도 후 실패 보고
- 산출물 생성 실패 → 코멘트로 실패 사유 기록, 재시도
- 승인 거절 → 거절 사유 확인 후 산출물 보완
- 워크플로우 없음 → 새 워크플로우 생성 또는 관리자에게 보고
