# Script: 단계 전환

현재 단계의 산출물을 점검하고 다음 단계로 전환하는 결정적 흐름.

## 사전 조건
- `workflow_id`
- 현재 단계의 필수 산출물이 모두 등록되어 있어야 함

## 실행 흐름

### Step 1: 워크플로우 현황 확인
```
wf = ax_get_workflow(workflow_id="{workflow_id}")
```
- `wf.current_stage_id` → 현재 단계
- `wf.stages` → 전체 단계 목록
- `wf.artifacts` → 등록된 산출물

### Step 2: 산출물 완료 여부 점검
현재 단계의 `expected_artifacts`와 실제 등록된 산출물 비교.

```python
current = [s for s in wf.stages if s.is_current][0]
expected = json.loads(current.expected_artifacts)  # ["proposal", "email"]
actual = [a.artifact_type for a in wf.artifacts if a.stage_id == current.id]
missing = [e for e in expected if e not in actual]
```

- `missing`이 있으면 → 먼저 산출물 생성 (create-artifact.md 참조)
- 모두 충족이면 → Step 3 진행

### Step 3: 다음 단계 ID 결정
```python
current_order = current.stage_order
next_stage = [s for s in wf.stages if s.stage_order == current_order + 1]
```
- 다음 단계가 없으면 → 마지막 단계. 워크플로우 완료 처리 검토.

### Step 4: 전환 실행
```
result = ax_transition_stage(
    workflow_id="{workflow_id}",
    to_stage_id="{next_stage.id}",
    note="단계 완료: {현재 단계 요약}"
)
```

### Step 5: 결과 분기
```python
if result.pending_approval:
    # 승인 필요 단계 → handle-approval.md 참조
    # approval_id = result.approval_id
    # 다른 작업으로 전환, 승인 대기
elif result.ok:
    # 자동 전환 성공 → 다음 단계 작업 시작
    # result.current_stage_id 로 확인
```

## 주의사항
- `pending_approval` 상태인 워크플로우는 전환 불가 → 먼저 승인 처리
- 마지막 단계 완료 시 워크플로우 상태를 `completed`로 변경:
  ```
  # REST API 또는 직접 ax_get_workflow로 확인 후 처리
  ```
