# Script: 워크플로우 생성

새 워크플로우를 생성하고 첫 단계 산출물까지 등록하는 결정적 흐름.

## 사전 조건
- `agent_id` (sales | marketing | support)
- 작업 제목, 우선순위, 담당자

## 실행 흐름

### Step 1: 템플릿 확인
```
result = ax_list_workflows(agent_id="{agent_id}")
```
- `result.template_id` → 사용할 템플릿
- `result.stages` → 단계 목록 확인
- `result.stages[0].id` → 첫 번째 단계 ID

### Step 2: 워크플로우 생성
```
wf = ax_create_workflow(
    template_id=result.template_id,
    title="{작업 제목}",
    priority=0,        # 0=보통, 1=높음, 2=긴급
    assignee="{담당자}"
)
```
- `wf.id` → 생성된 워크플로우 ID
- `wf.current_stage_id` → 현재 단계 (= 첫 번째 단계)

### Step 3: 첫 단계 산출물 생성
`result.stages[0].expected_artifacts`를 파싱하여 필요한 산출물 유형 확인.

```
art = ax_create_artifact(
    workflow_id=wf.id,
    stage_id=wf.current_stage_id,
    artifact_type="{expected_artifact_type}",
    title="{산출물 제목}",
    content="{마크다운 또는 JSON 내용}",
    content_type="text/markdown",  # 또는 "application/json"
    status="draft"
)
```

### Step 4: 확인
```
detail = ax_get_workflow(workflow_id=wf.id)
```
- `detail.artifacts` → 등록된 산출물 확인
- `detail.stages` → 각 단계 `is_current` 확인

## 에러 처리
- 템플릿 없음 → `result.template_id`가 None이면 사용자에게 보고
- 생성 실패 → `wf.error` 필드 확인, 3회 재시도
