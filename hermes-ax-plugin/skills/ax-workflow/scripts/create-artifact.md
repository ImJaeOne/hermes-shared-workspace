# Script: 산출물 생성

워크플로우 단계에 산출물을 생성하고 코멘트를 추가하는 결정적 흐름.

## 사전 조건
- `workflow_id`, `stage_id`
- 산출물 유형(`artifact_type`)과 내용

## 산출물 유형별 content_type 매핑

| artifact_type | content_type | 설명 |
|--------------|-------------|------|
| `contact_info` | `application/json` | 연락처 정보 |
| `ticket` | `application/json` | 지원 티켓 |
| `email` | `text/markdown` | 이메일 본문 |
| `meeting_notes` | `text/markdown` | 미팅 노트 |
| `proposal` | `text/markdown` | 제안서 |
| `contract` | `text/markdown` | 계약서 |
| `report` | `text/markdown` | 보고서 |
| `brief` | `text/markdown` | 기획 브리프 |
| `content_draft` | `text/markdown` | 콘텐츠 초안 |
| `resolution_note` | `text/markdown` | 해결 노트 |
| `log` | `text/plain` | 작업 로그 |

## 실행 흐름

### Step 1: 기존 산출물 확인
```
wf = ax_get_workflow(workflow_id="{workflow_id}")
```
현재 단계에 같은 `artifact_type`이 이미 있는지 확인.
- 있으면 → `ax_update_artifact`로 수정 검토
- 없으면 → 새로 생성

### Step 2: 내용 작성
`reference/` 디렉토리의 샘플을 참고하여 내용 작성.
- 마크다운: 제목(##), 구조화된 섹션, 리스트/테이블 활용
- JSON: snake_case 필드명, 필수 필드 누락 없이

### Step 3: 산출물 생성
```
art = ax_create_artifact(
    workflow_id="{workflow_id}",
    stage_id="{stage_id}",
    artifact_type="{type}",
    title="{제목}",
    content="{내용}",
    content_type="{content_type}",
    status="draft"
)
```

### Step 4: 코멘트 추가 (선택)
작성 의도, 참고사항, 리뷰 요청 등을 기록.
```
ax_add_comment(
    artifact_id=art.id,
    author="{에이전트 이름}",
    body="{코멘트 내용}"
)
```

### Step 5: 상태 변경 (완성 시)
초안 완료 후 최종 확정:
```
ax_update_artifact(
    artifact_id=art.id,
    status="final"
)
```

## 에러 처리
- 워크플로우 없음 → `art.error` 확인
- 내용이 비어있으면 안 됨 → content 필수 검증
