# 기획 자료조사 MVP 정보구조와 상태 모델

상태: Accepted working decision
작성일: 2026-05-22
관련 이슈: [#19](https://github.com/ImJaeOne/hermes-shared-workspace/issues/19)

## 배경

1차 MVP는 기획 전체 파이프라인 중 **자료조사 단계만 실제 실행**한다. 사용자는 Slack에서 `#덕우전자`처럼 회사명 채널을 만들고 자료를 전달하며, AX Dashboard에서는 이 채널이 내부 워크플로우가 아니라 **회사 프로젝트**로 보여야 한다.

비개발자 직원이 사용하는 서비스이므로 UI에서는 `워크플로우 정의`, `인스턴스`, `Artifact` 같은 내부 용어를 직접 노출하지 않는다. 내부 구현은 기존 AX DB의 workflow/template/stage/artifact 구조를 사용하되, 화면·Slack 응대·문서에서는 회사 프로젝트 중심 용어로 번역한다.

## 결정 요약

1. Slack 회사명 채널 하나를 AX의 회사 프로젝트 하나로 매핑한다.
2. 1차 MVP 실행 대상은 `자료조사` 하나이며, `시놉시스(목차)`, `스토리보드`, `원고`는 후속 단계 placeholder로만 둔다.
3. 업무 상태는 `workflow_instances.status`가 아니라 `workflow_instances.current_stage_id`와 `stage_definitions`로 표현한다.
4. 회사명, Slack 채널 ID, 원천, 후속 placeholder 같은 프로젝트 메타데이터는 MVP에서는 `workflow_instances.metadata_json`에 저장한다.
5. 현재 DB schema migration은 하지 않는다. 다만 기존 DB에 새 템플릿/단계를 넣기 위한 idempotent data upsert는 후속 구현 이슈에서 필요할 수 있다.

## 회사 프로젝트 매핑 규칙

### 기본 규칙

| Slack 입력 | 정규화 | AX 회사 프로젝트 |
| --- | --- | --- |
| `#덕우전자` | `덕우전자` | `[덕우전자] 기획 자료조사` |
| `# 덕우전자` | `덕우전자` | `[덕우전자] 기획 자료조사` |
| `#덕우전자-자료조사` | `덕우전자` + 별칭 `자료조사` | `[덕우전자] 기획 자료조사` |

- Slack 채널명에서 선행 `#`, 앞뒤 공백, 반복 공백을 제거한다.
- 1차 MVP에서는 회사명 한글 표기를 AX 프로젝트명으로 그대로 사용한다.
- Slack `channel_id`가 있으면 중복 생성 방지의 우선 키로 사용한다.
- `channel_id`가 없으면 정규화된 `company_name`과 `project_key`를 보조 키로 사용한다.
- 같은 회사가 여러 Slack 채널을 쓰는 상황은 후속 범위로 두며, MVP에서는 회사명 채널 1개를 회사 프로젝트 1개로 본다.
- 채널명 suffix는 MVP에서 `-자료조사`, `_자료조사`, 공백 뒤 `자료조사` 정도만 별칭으로 허용하고, 이 외 복합 규칙은 후속 Slack 연동 구현에서 명시한다.

### 권장 `metadata_json`

```json
{
  "company_name": "덕우전자",
  "project_key": "planning-research:덕우전자",
  "source": "slack",
  "slack": {
    "channel_name": "덕우전자",
    "channel_id": "C0123456789"
  },
  "mvp_scope": "research_only",
  "future_placeholders": ["synopsis", "storyboard", "script"]
}
```

## 1차 MVP 단계와 상태

### 단계 범위

| 단계 | 1차 MVP 처리 | 비고 |
| --- | --- | --- |
| 자료조사 | 실제 실행 | 자료 수집, 자료 확인, 조사 실행, 검토/수정/확정까지 포함 |
| 시놉시스(목차) | placeholder | 후속 구현에서 실행 단계로 승격 |
| 스토리보드 | placeholder | 후속 구현에서 실행 단계로 승격 |
| 원고 | placeholder | 후속 구현에서 실행 단계로 승격 |

후속 placeholder는 별도 `stage_definitions`로 만들지 않고, MVP에서는 `workflow_definitions.content`나 템플릿 설명/문서에만 남긴다. 이렇게 하면 실제 칸반/파이프라인에 실행하지 않는 단계가 섞이지 않는다.

`metadata_json.future_placeholders`는 자동화가 읽을 수 있는 짧은 식별자 목록으로만 사용하고, 사람이 읽는 후속 단계 설명·범위·전환 조건은 `workflow_definitions.content` 또는 이 결정 문서에 둔다.

### 상태 목록

| 순서 | UI 상태명 | 내부 stage slug | 권장 담당 | 의미 |
| ---: | --- | --- | --- | --- |
| 0 | 자료 요청 중 | `material-requesting` | 기획팀 임팀장 | 사용자에게 필요한 자료를 요청하거나 안내하는 상태 |
| 1 | 자료 확인 대기 | `material-waiting` | 기획팀 임팀장 | 사용자가 자료를 전달했고, 실행 가능 여부를 확인하는 상태 |
| 2 | 자료조사 실행 중 | `research-running` | 기획팀 임사원 | 자료조사 worker가 조사 결과를 생성하는 상태 |
| 3 | 사용자 검토 대기 | `user-review-waiting` | human 사용자 | 조사 결과 초안을 사용자에게 보여주고 확인을 기다리는 상태 |
| 4 | 수정 요청 처리 중 | `revision-running` | 기획팀 임사원 | 사용자 수정 요청을 반영하는 상태 |
| 5 | 자료조사 확정 | `research-confirmed` | human 사용자 / 기획팀 임팀장 | 최종 조사 결과가 확정된 완료 상태 |

## 상태 전이 조건

| From | To | 전이 조건 | 주 actor | 내부 업데이트 |
| --- | --- | --- | --- | --- |
| 없음 | 자료 요청 중 | Slack 회사명 채널 감지 또는 AX에서 수동 생성 | 기획팀 임팀장 | `workflow_instances` 생성, `metadata_json`에 회사/Slack 매핑 저장 |
| 자료 요청 중 | 자료 확인 대기 | 사용자가 파일, 링크, 설명 등 자료를 전달 | human 사용자 / 기획팀 임팀장 | `source_material` artifact 생성 또는 자료 목록 comment 기록 |
| 자료 확인 대기 | 자료 요청 중 | 필수 자료가 부족하거나 열람 권한이 없음 | 기획팀 임팀장 | 부족한 자료를 `comments` 또는 transition note에 기록 |
| 자료 확인 대기 | 자료조사 실행 중 | 자료조사 실행에 필요한 최소 입력을 확인 | 기획팀 임팀장 | `assignee = "기획팀 임사원"`, 실행 이벤트 기록 |
| 자료조사 실행 중 | 사용자 검토 대기 | 조사 결과 초안 생성 완료 | 기획팀 임사원 | `research_report` artifact 생성, artifact `status = draft` |
| 사용자 검토 대기 | 자료조사 확정 | 사용자가 조사 결과를 승인/확정 | human 사용자 | artifact `status = final`, workflow `status = completed` |
| 사용자 검토 대기 | 수정 요청 처리 중 | 사용자가 수정 요청 또는 보완 의견을 남김 | human 사용자 / 기획팀 임팀장 | 수정 요청을 `comments`에 기록, workflow `status = active` 유지 |
| 수정 요청 처리 중 | 사용자 검토 대기 | 수정본 생성 완료 | 기획팀 임사원 | 기존 artifact 업데이트 또는 새 draft artifact 생성 |

`사용자 검토 대기 → 수정 요청 처리 중 → 사용자 검토 대기`는 되돌아오는 loop다. 현재 UI의 기본 진행 버튼은 다음 stage 순차 이동에 최적화되어 있으므로, 이 loop를 화면에서 자연스럽게 처리하려면 후속 구현에서 “수정 요청” 전용 액션을 추가하는 것이 좋다.

## Actor 모델

| Actor | 사용자에게 보이는 역할 | 내부 표현 | 권한/제약 |
| --- | --- | --- | --- |
| human 사용자 | 회사 담당자/검토자 | `users`, `activity_logs.actor_kind = human` | 자료 전달, 검토, 수정 요청, 최종 확정 |
| 기획팀 임팀장 | Slack 응대/조율 담당 | `assignee`, `stage_transitions.triggered_by`, `activity_logs.actor_label` | 자료 요청, 자료 충분성 확인, worker 실행 조율 |
| 기획팀 임사원 | 자료조사팀 worker | `assignee`, `stage_transitions.triggered_by`, `activity_logs.actor_label` | 자료조사 실행, 초안/수정본 생성 |
| `planninglearner` | 학습/개선 담당 계정 | `users.username = planninglearner` 또는 role/metadata | 프롬프트·스킬·템플릿 개선 후보 생성 허용 |

일반 사용자와 일반 agent는 산출물/업무 상태만 바꾼다. `planninglearner`만 프롬프트, skill, playbook, template 개선 후보를 만들 수 있으며, 실제 적용은 관리자 검토 후 수행한다. 이 경계는 [AX 인증 및 런타임 지식 저장 방식 결정](./auth-and-persistence.md)의 자가 진화 원칙과 같이 유지한다.

## DB 활용안

| 목적 | 기존 테이블/필드 | 활용 방식 |
| --- | --- | --- |
| 기획 영역 구분 | `agent_types.id = planning` | 기존 Planning Agent 사용 |
| MVP 템플릿 | `workflow_templates` | `planning_research_mvp_v1` 템플릿 추가 권장 |
| 6개 업무 상태 | `stage_definitions` | 각 상태를 stage로 정의하고 `current_stage_id`로 현재 상태 표현 |
| 회사 프로젝트 | `workflow_instances.title` | `[덕우전자] 기획 자료조사`처럼 회사명 중심 제목 사용 |
| Slack 매핑 | `workflow_instances.metadata_json` | `company_name`, `project_key`, `slack.channel_id/name` 저장 |
| 담당자 | `workflow_instances.assignee` | 현재 책임 actor를 사람이 읽는 이름으로 표시 |
| 내부 lifecycle | `workflow_instances.status` | `active`, `pending_approval`, `completed`, `failed`, `cancelled`만 사용 |
| 입력 자료 | `artifacts.artifact_type = source_material` | 사용자가 전달한 파일/링크/자료 목록 |
| 조사 결과 | `artifacts.artifact_type = research_report` | 자료조사 초안/최종본 |
| 수정 요청 | `comments` | 사용자 보완 의견과 수정 요청 기록 |
| 확정 게이트 | `approval_requests` 또는 stage transition note | 최종 확정 흐름에 사용 가능. MVP에서는 stage 기반 확정으로 시작 가능 |
| 전환 이력 | `stage_transitions` | 상태 전환, 주체, 메모 기록 |
| 감사 로그 | `activity_logs` | actor kind/label, action, target 기록 |
| 후속 단계 placeholder | `workflow_definitions.content` | 시놉시스/스토리보드/원고가 후속 단계임을 문서화 |

### Migration 판단

| 항목 | 판단 |
| --- | --- |
| 회사 프로젝트와 Slack 채널 매핑 | MVP는 `metadata_json`으로 충분 |
| 6개 상태 표현 | 기존 `stage_definitions`로 충분 |
| 자료/결과 산출물 | 기존 `artifacts`로 충분 |
| 사용자 검토/수정/확정 | 기존 `comments`, `approval_requests`, `stage_transitions`로 충분 |
| actor 감사 | 기존 `users`, `activity_logs`로 충분 |
| schema migration | 1차 MVP 상태 모델 정리 단계에서는 불필요 |
| data migration/upsert | 기존 DB에 `planning_research_mvp_v1` 템플릿/단계를 주입하려면 후속 구현에서 필요 |
| 선택적 후속 schema | Slack channel id unique 보장, 회사별 검색/권한/다중 채널이 필요해지면 `company_projects` 또는 `channel_project_mappings` 검토 |

`workflow_instances.status`에 `자료 요청 중` 같은 한국어 업무 상태를 직접 넣지 않는다. 현재 보드와 통계는 lifecycle status를 기준으로 동작하므로, 업무 상태는 stage로 유지해야 누락 위험이 작다.

## 비개발자 UI 용어 매핑

| UI 용어 | 내부 용어/필드 | 노출 원칙 |
| --- | --- | --- |
| 회사 프로젝트 | `workflow_instances` | “워크플로우 인스턴스” 대신 사용 |
| 업무 흐름 | `workflow_templates` | 관리자/설정 화면에서만 제한적으로 사용 |
| 진행 상태 | `stage_definitions.name`, `current_stage_id` | “stage” 대신 사용 |
| 자료 | `source_material` artifact | 사용자가 전달한 원본/링크/파일 |
| 자료조사 결과 | `research_report` artifact | worker가 만든 조사 산출물 |
| 초안 | artifact `status = draft` | 사용자 검토 전 |
| 최종본 | artifact `status = final` | 사용자 확정 후 |
| 수정 요청 | `comments` 또는 approval note | 사용자가 요구한 보완 사항 |
| 담당자 | `workflow_instances.assignee` | 임팀장/임사원 등 사람이 읽는 이름 |
| 확정 | `workflow_instances.status = completed` + final artifact | “승인”보다 최종 확인 의미를 우선 |
| 학습 후보 | learner가 만든 skill/prompt/playbook/template 제안 | 일반 업무 산출물과 분리 |

## 후속 구현 메모

- Slack 이벤트 처리 구현 시 `channel_id` 기준 idempotent create/upsert가 필요하다.
- 현재 MCP `ax_create_workflow`가 `metadata_json`을 받지 않는다면 Slack 매핑 저장을 위해 tool 인자 확장 또는 생성 후 업데이트 API가 필요하다.
- actor label이 `mcp`처럼 고정되는 경로는 임팀장/임사원 구분이 흐려질 수 있으므로, 후속 구현에서 `actor_label` 인자를 받도록 확장할지 검토한다.
- 최종 확정에 `approval_required`를 사용할 경우 `자료조사 확정` stage 진입 전에 approval request가 생성되도록 설계하는 것이 자연스럽다.
- `사용자 검토 대기`와 `수정 요청 처리 중` 사이의 loop는 UI에서 별도 액션으로 다루는 것이 좋다.
