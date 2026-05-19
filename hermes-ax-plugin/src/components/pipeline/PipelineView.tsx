import React, { useCallback, useEffect, useState } from "react";
import { useApp } from "../../context/AppContext";
import { getWorkflow, transitionWorkflow, updateWorkflow } from "../../api/client";
import type { WorkflowDetailResponse } from "../../types/api";
import { StageTimeline } from "./StageTimeline";
import { StageDetail } from "./StageDetail";
import { ApprovalPanel } from "./ApprovalPanel";
import { StatusBadge, PriorityBadge } from "../shared/StatusBadge";
import { EmptyState } from "../shared/EmptyState";

export function PipelineView() {
  const { selectedWorkflowId, refreshBoard, refreshApprovals } = useApp();
  const [workflow, setWorkflow] = useState<WorkflowDetailResponse | null>(null);
  const [selectedStageId, setSelectedStageId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadWorkflow = useCallback(async () => {
    if (!selectedWorkflowId) return;
    try {
      const data = await getWorkflow(selectedWorkflowId);
      setWorkflow(data);
      if (!selectedStageId) {
        setSelectedStageId(data.current_stage_id);
      }
    } catch (e) {
      console.error("Failed to load workflow:", e);
    } finally {
      setLoading(false);
    }
  }, [selectedWorkflowId, selectedStageId]);

  useEffect(() => {
    loadWorkflow();
  }, [loadWorkflow]);

  const handleTransition = async (toStageId: string) => {
    if (!workflow) return;
    try {
      const result = await transitionWorkflow(workflow.id, { to_stage_id: toStageId, triggered_by: "user" });
      if (result.pending_approval) {
        // Transition requires approval, reload to show pending state
        await loadWorkflow();
        refreshBoard();
        refreshApprovals();
      } else {
        setSelectedStageId(toStageId);
        await loadWorkflow();
        refreshBoard();
      }
    } catch (e) {
      console.error("Transition failed:", e);
    }
  };

  const handleStatusChange = async (status: string) => {
    if (!workflow) return;
    try {
      await updateWorkflow(workflow.id, { status });
      await loadWorkflow();
      refreshBoard();
    } catch (e) {
      console.error("Status change failed:", e);
    }
  };

  const handleApprovalDecided = async () => {
    await loadWorkflow();
    refreshBoard();
    refreshApprovals();
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
            <button className="ax-btn ax-btn-primary ax-btn-sm" onClick={() => handleTransition(nextStage.id)}>
              {nextStage.name}(으)로 진행 &rarr;
            </button>
          )}
          {workflow.status === "active" && (
            <>
              <button className="ax-btn ax-btn-ghost ax-btn-sm" onClick={() => handleStatusChange("paused")}>일시정지</button>
              <button className="ax-btn ax-btn-ghost ax-btn-sm" onClick={() => handleStatusChange("completed")}>완료</button>
            </>
          )}
          {workflow.status === "paused" && (
            <button className="ax-btn ax-btn-primary ax-btn-sm" onClick={() => handleStatusChange("active")}>재개</button>
          )}
        </div>
      </div>

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

      {workflow.transitions.length > 0 && (
        <div className="ax-transitions">
          <h3 className="ax-section-title">전환 이력</h3>
          <div className="ax-transition-list">
            {workflow.transitions.map((t) => {
              const fromName = workflow.stages.find((s) => s.id === t.from_stage_id)?.name || "시작";
              const toName = workflow.stages.find((s) => s.id === t.to_stage_id)?.name || "?";
              return (
                <div key={t.id} className="ax-transition-item">
                  <span className="ax-transition-flow">{fromName} &rarr; {toName}</span>
                  <span className="ax-transition-by">{t.triggered_by}</span>
                  {t.note && <span className="ax-transition-note">{t.note}</span>}
                  <span className="ax-transition-time">{new Date(t.created_at).toLocaleString()}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
