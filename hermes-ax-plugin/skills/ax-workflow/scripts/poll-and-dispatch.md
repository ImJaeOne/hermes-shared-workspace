# Script: 이벤트 폴링 및 자동 디스패치

새 이벤트를 감지하여 자동으로 다음 작업을 디스패치하는 루프.

## 이벤트 종류

| kind | 의미 | 액션 |
|------|------|------|
| `workflow_created` | 새 워크플로우 생성 | 첫 단계 산출물 작업 |
| `stage_changed` | 단계 전환 완료 | 새 단계 작업 시작 |
| `approval_approved` | 승인 완료 | 전환된 단계 작업 시작 |
| `approval_rejected` | 승인 거절 | 산출물 보완 |
| `artifact_added` | 산출물 추가 | 로그 기록 |
| `comment_added` | 코멘트 추가 | 피드백 확인 |

## 폴링 루프

### Step 1: 커서 초기화
```
cursor = 0  # 처음부터. 또는 마지막으로 처리한 이벤트 ID.
```

### Step 2: 이벤트 조회
```
result = ax_poll_events(since=cursor, limit=50)
cursor = result.cursor  # 다음 폴링에 사용
```

### Step 3: 이벤트별 분기 처리
```python
for event in result.events:
    wf_id = event.workflow_id
    payload = event.payload  # dict (자동 파싱됨)

    if event.kind == "stage_changed" and payload.get("trigger_next"):
        # 승인 후 자동 전환된 경우 → 새 단계 작업 시작
        wf = ax_get_workflow(workflow_id=wf_id)
        current_stage = [s for s in wf.stages if s.is_current][0]
        # → create-artifact.md 스크립트 실행

    elif event.kind == "workflow_created":
        # 새 워크플로우 → 첫 단계 작업
        wf = ax_get_workflow(workflow_id=wf_id)
        # → create-workflow.md Step 3부터 실행

    elif event.kind == "approval_rejected":
        # 거절 → 산출물 보완
        approval_id = payload.get("approval_id")
        approvals = ax_list_approvals(status="rejected", workflow_id=wf_id)
        # 거절 사유 확인 후 산출물 수정

    elif event.kind == "comment_added":
        # 새 코멘트 → 피드백 확인
        art_id = event.artifact_id
        if art_id:
            art = ax_get_artifact(artifact_id=art_id)
            # 최신 코멘트 확인 후 필요시 대응
```

### Step 4: Kanban 태스크 생성 (선택)
이벤트 처리 대신 Kanban 태스크로 위임할 경우:
```
ax_create_kanban_task(
    workflow_id=wf_id,
    stage_id=current_stage.id,
    priority=20  # 높음
)
```

## 폴링 간격
- 일반: 60초 간격
- 긴급 워크플로우 진행 중: 10초 간격
- 야간/비활성: 300초 간격
