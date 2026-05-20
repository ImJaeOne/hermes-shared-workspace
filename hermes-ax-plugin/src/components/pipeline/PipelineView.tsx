import React, { useCallback, useEffect, useState } from "react";
import { useApp } from "../../context/AppContext";
import { getApiErrorMessage, getWorkflow, transitionWorkflow, updateWorkflow } from "../../api/client";
import type { WorkflowDetailResponse } from "../../types/api";
import { StageTimeline } from "./StageTimeline";
import { StageDetail } from "./StageDetail";
import { ApprovalPanel } from "./ApprovalPanel";
import { ActivityTimeline } from "./ActivityTimeline";
import { StatusBadge, PriorityBadge } from "../shared/StatusBadge";
import { EmptyState } from "../shared/EmptyState";

export function PipelineView() {
  const { selectedWorkflowId, refreshBoard, refreshApprovals, authenticated, authLoading } = useApp();
  const [workflow, setWorkflow] = useState<WorkflowDetailResponse | null>(null);
  const [selectedStageId, setSelectedStageId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState("");

  const loadWorkflow = useCallback(async () => {
    if (!selectedWorkflowId) {
      setWorkflow(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const data = await getWorkflow(selectedWorkflowId);
      setWorkflow(data);
      setSelectedStageId((prev) => prev ?? data.current_stage_id);
    } catch (e) {
      console.error("Failed to load workflow:", e);
    } finally {
      setLoading(false);
    }
  }, [selectedWorkflowId]);

  useEffect(() => {
    void loadWorkflow();
  }, [loadWorkflow]);

  const handleTransition = async (toStageId: string) => {
    if (!workflow || !authenticated) return;
    setActionError("");
    try {
      const result = await transitionWorkflow(workflow.id, { to_stage_id: toStageId });
      if (result.pending_approval) {
        await loadWorkflow();
        await refreshBoard();
        await refreshApprovals();
      } else {
        setSelectedStageId(toStageId);
        await loadWorkflow();
        await refreshBoard();
      }
    } catch (e) {
      setActionError(getApiErrorMessage(e, "단계를 전환하지 못했습니다."));
      console.error("Transition failed:", e);
    }
  };

  const handleStatusChange = async (status: string) => {
    if (!workflow || !authenticated) return;
    setActionError("");
    try {
      await updateWorkflow(workflow.id, { status });
      await loadWorkflow();
      await refreshBoard();
    } catch (e) {
      setActionError(getApiErrorMessage(e, "상태를 변경하지 못했습니다."));
      console.error("Status change failed:", e);
    }
  };

  const handleApprovalDecided = async () => {
    await loadWorkflow();
    await refreshBoard();
    await refreshApprovals();
  };

  if (loading) {
    return <EmptyState message="워크플로우 로딩 중..." />;
  }

  if (!workflow) {
    return <EmptyState message="워크플로우를 찾을 수 없습니다." />;
  }

  const currentStageOrder = workflow.stages.find((s) => s.is_current)?.stage_order ?? 0;
  const selectedStage = workflow.stages.find((s) => s.id === selectedStageId);
  const nextStage = workflow.stages.find((s) => s.stage_order === currentStageOrder + 1);
  const stageArtifacts = workflow.artifacts.filter((a) => a.stage_id === selectedStageId);
  const isPendingApproval = workflow.status === "pending_approval";
  const writeDisabled = !authenticated || authLoading;

  return (
    <div className="ax-pipeline">
      <div className="ax-pipeline-header">
        <div className="ax-pipeline-header-info">
          <h2 className="ax-pipeline-title">{workflow.title}</h2>
          <div className="ax-pipeline-meta">
            <StatusBadge status={workflow.status} />
            <PriorityBadge priority={workflow.priority} />
            {workflow.assignee && <span className="ax-pipeline-assignee">담당자: {workflow.assignee}</span>}
          </div>
        </div>
        <div className="ax-pipeline-actions">
          {workflow.status === "active" && nextStage && (
            <button className="ax-btn ax-btn-primary ax-btn-sm" onClick={() => handleTransition(nextStage.id)} disabled={writeDisabled}>
              {nextStage.name}(으)로 진행 →
            </button>
          )}
          {workflow.status === "active" && (
            <>
              <button className="ax-btn ax-btn-ghost ax-btn-sm" onClick={() => handleStatusChange("paused")} disabled={writeDisabled}>일시정지</button>
              <button className="ax-btn ax-btn-ghost ax-btn-sm" onClick={() => handleStatusChange("completed")} disabled={writeDisabled}>완료</button>
            </>
          )}
          {workflow.status === "paused" && (
            <button className="ax-btn ax-btn-primary ax-btn-sm" onClick={() => handleStatusChange("active")} disabled={writeDisabled}>재개</button>
          )}
        </div>
      </div>

      {!authenticated && <p className="ax-auth-required">로그인 후 워크플로우 전환과 상태 변경을 사용할 수 있습니다.</p>}
      {actionError && <p className="ax-form-error ax-action-error">{actionError}</p>}

      {isPendingApproval && workflow.pending_approval && (
        <ApprovalPanel approval={workflow.pending_approval} onDecided={handleApprovalDecided} />
      )}

      <StageTimeline
        stages={workflow.stages}
        selectedStageId={selectedStageId}
        onSelectStage={setSelectedStageId}
      />

      {selectedStage && (
        <StageDetail
          stage={selectedStage}
          artifacts={stageArtifacts}
          workflow={workflow}
          onRefresh={loadWorkflow}
        />
      )}

      <ActivityTimeline activityLogs={workflow.activity_logs} stages={workflow.stages} />

      {workflow.transitions.length > 0 && (
        <div className="ax-transitions">
          <h3 className="ax-section-title">전환 이력</h3>
          <div className="ax-transition-list">
            {workflow.transitions.map((t) => {
              const fromName = workflow.stages.find((s) => s.id === t.from_stage_id)?.name || "시작";
              const toName = workflow.stages.find((s) => s.id === t.to_stage_id)?.name || "?";
              return (
                <div key={t.id} className="ax-transition-item">
                  <span className="ax-transition-flow">{fromName} → {toName}</span>
                  <span className="ax-transition-by">{t.triggered_by}</span>
                  {t.note && <span className="ax-transition-note">{t.note}</span>}
                  <span className="ax-transition-time">{new Date(t.created_at).toLocaleString("ko-KR")}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
