import React from "react";
import type { StageDefinition, WorkflowInstance } from "../../types/models";
import { KanbanCard } from "./KanbanCard";

interface Props {
  stage: StageDefinition;
  workflows: WorkflowInstance[];
  isDone?: boolean;
}

export function KanbanColumn({ stage, workflows, isDone }: Props) {
  return (
    <div className={`ax-kanban-col ${isDone ? "ax-kanban-col-done" : ""}`}>
      <div className="ax-kanban-col-header">
        <span className="ax-kanban-col-name">{stage.name}</span>
        <span className="ax-kanban-col-count">{workflows.length}</span>
      </div>
      <div className="ax-kanban-col-body">
        {workflows.map((wf) => (
          <KanbanCard key={wf.id} workflow={wf} />
        ))}
        {workflows.length === 0 && (
          <div className="ax-kanban-empty">항목 없음</div>
        )}
      </div>
    </div>
  );
}
