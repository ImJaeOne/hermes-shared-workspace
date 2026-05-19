import React, { useState } from "react";
import { useApp } from "../../context/AppContext";
import { KanbanColumn } from "./KanbanColumn";
import { EmptyState } from "../shared/EmptyState";
import { CreateInstanceDialog } from "../shared/CreateInstanceDialog";

export function KanbanBoard() {
  const { boardData, selectedAgentId } = useApp();
  const [showCreateInstance, setShowCreateInstance] = useState(false);

  if (!boardData) {
    return <EmptyState message="보드 데이터 로딩 중..." />;
  }

  if (boardData.columns.length === 0) {
    return <EmptyState message="이 에이전트에 설정된 파이프라인 단계가 없습니다." />;
  }

  return (
    <div className="ax-kanban">
      <div className="ax-kanban-toolbar">
        <button className="ax-btn ax-btn-primary ax-btn-sm" onClick={() => setShowCreateInstance(true)}>
          + 새 티켓
        </button>
      </div>
      <div className="ax-kanban-columns">
        {boardData.columns.map((col) => (
          <KanbanColumn
            key={col.stage.id}
            stage={col.stage}
            workflows={col.workflows}
          />
        ))}
        {boardData.completed.length > 0 && (
          <KanbanColumn
            stage={{ id: "__done", template_id: "", name: "완료", slug: "done", stage_order: 999, expected_artifacts: "[]", trigger_conditions: "{}", transition_mode: "auto", approval_roles: "[]", created_at: "" }}
            workflows={boardData.completed}
            isDone
          />
        )}
      </div>
      {showCreateInstance && <CreateInstanceDialog onClose={() => setShowCreateInstance(false)} />}
    </div>
  );
}
