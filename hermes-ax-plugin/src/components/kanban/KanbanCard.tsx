import React from "react";
import type { WorkflowInstance } from "../../types/models";
import { useApp } from "../../context/AppContext";
import { deleteWorkflow } from "../../api/client";
import { StatusBadge, PriorityBadge } from "../shared/StatusBadge";

interface Props {
  workflow: WorkflowInstance;
}

export function KanbanCard({ workflow }: Props) {
  const { setViewMode, setSelectedWorkflowId, refreshBoard } = useApp();

  const handleClick = () => {
    setSelectedWorkflowId(workflow.id);
    setViewMode("pipeline");
  };

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(`"${workflow.title}" 워크플로우를 삭제하시겠습니까?`)) return;
    try {
      await deleteWorkflow(workflow.id);
      await refreshBoard();
    } catch (err) {
      console.error("Failed to delete workflow:", err);
    }
  };

  const timeAgo = formatTimeAgo(workflow.updated_at);
  const isPendingApproval = workflow.status === "pending_approval";

  return (
    <div className={`ax-kanban-card ${isPendingApproval ? "ax-kanban-card-pending" : ""}`} onClick={handleClick}>
      <div className="ax-kanban-card-top">
        <span className="ax-kanban-card-title">{workflow.title}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
          <PriorityBadge priority={workflow.priority} />
          <button
            className="ax-btn ax-btn-ghost ax-btn-xs ax-btn-delete"
            onClick={handleDelete}
            title="삭제"
          >
            ×
          </button>
        </div>
      </div>
      <div className="ax-kanban-card-meta">
        <StatusBadge status={workflow.status} />
        {isPendingApproval && (
          <span className="ax-badge ax-badge-approval">승인 대기</span>
        )}
        {workflow.artifact_count != null && workflow.artifact_count > 0 && (
          <span className="ax-kanban-card-artifacts">
            산출물 {workflow.artifact_count}개
          </span>
        )}
      </div>
      <div className="ax-kanban-card-footer">
        {workflow.assignee && <span className="ax-kanban-card-assignee">{workflow.assignee}</span>}
        <span className="ax-kanban-card-time">{timeAgo}</span>
      </div>
    </div>
  );
}

function formatTimeAgo(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return "방금";
    if (diffMin < 60) return `${diffMin}분 전`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}시간 전`;
    const diffDay = Math.floor(diffHr / 24);
    return `${diffDay}일 전`;
  } catch {
    return "";
  }
}
