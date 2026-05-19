# Script: 승인 처리

승인 요청 생성부터 결과 처리까지의 결정적 흐름.

## 승인이 필요한 시점
`stage_definitions.transition_mode == "approval_required"` 인 단계로 전환할 때 자동 발생.

## 실행 흐름

### Step 1: 승인 대기 목록 확인
```
approvals = ax_list_approvals(status="pending")
```
- `approvals.approvals` → 대기 중인 승인 목록
- 각 항목: `id`, `workflow_id`, `workflow_title`, `stage_name`, `requested_at`

### Step 2-A: 승인 요청 생성 (자동)
`ax_transition_stage` 호출 시 대상 단계가 `approval_required`이면 자동 생성됨.
```
result = ax_transition_stage(
    workflow_id="{workflow_id}",
    to_stage_id="{approval_stage_id}",
    note="리뷰 요청: {산출물 요약}"
)
# result.pending_approval == True
# result.approval_id → 승인 요청 ID
```

### Step 2-B: 승인 대기 중 행동
- 워크플로우 상태: `pending_approval` (단계 전환 불가)
- **가능한 작업**: 산출물 추가/수정, 코멘트 추가
- **불가능한 작업**: 다른 단계로 전환
- 다른 워크플로우 작업으로 전환하여 대기 시간 활용

### Step 3: 승인/거절 결정
```
result = ax_decide_approval(
    approval_id="{approval_id}",
    decision="approved",    # 또는 "rejected"
    decided_by="{결정자 이름}",
    note="{결정 사유}"
)
```

### Step 4: 결과 분기

#### 승인됨 (approved)
- 워크플로우가 자동으로 해당 단계로 전환됨
- `stage_changed` 이벤트에 `trigger_next: True` 포함
- 다음 단계 작업 즉시 시작 가능

#### 거절됨 (rejected)
- 워크플로우가 현재 단계에 머물며 `active`로 복원
- 거절 사유 확인:
  ```
  approvals = ax_list_approvals(
      status="rejected",
      workflow_id="{workflow_id}"
  )
  # approvals.approvals[-1].note → 거절 사유
  ```
- 산출물 보완 후 다시 전환 요청

## 폴링으로 승인 감지
```
events = ax_poll_events(since={last_cursor})
for event in events.events:
    if event.kind == "approval_approved" and event.payload.trigger_next:
        # 해당 워크플로우의 다음 단계 작업 시작
    elif event.kind == "approval_rejected":
        # 산출물 보완 필요
```
