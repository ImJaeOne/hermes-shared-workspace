import React, { useState } from "react";
import { useApp } from "../../context/AppContext";
import { createWorkflow } from "../../api/client";

interface Props {
  onClose: () => void;
}

export function CreateInstanceDialog({ onClose }: Props) {
  const { boardData, refreshBoard } = useApp();
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState(0);
  const [assignee, setAssignee] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const templateId = boardData?.template_id;

  const handleSubmit = async () => {
    if (!title.trim() || !templateId) return;
    setSubmitting(true);
    try {
      await createWorkflow({
        template_id: templateId,
        title: title.trim(),
        priority,
        assignee: assignee.trim(),
      });
      await refreshBoard();
      onClose();
    } catch (e) {
      console.error("Failed to create workflow:", e);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="ax-overlay" onClick={onClose}>
      <div className="ax-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="ax-dialog-header">
          <h2>새 티켓 생성</h2>
        </div>
        <div className="ax-dialog-body">
          <label className="ax-label">
            제목
            <input
              className="ax-input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="예: Acme Corp 딜"
              autoFocus
              onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            />
          </label>
          <label className="ax-label">
            우선순위
            <select className="ax-select" value={priority} onChange={(e) => setPriority(Number(e.target.value))}>
              <option value={0}>보통</option>
              <option value={1}>높음</option>
              <option value={2}>긴급</option>
            </select>
          </label>
          <label className="ax-label">
            담당자
            <input
              className="ax-input"
              value={assignee}
              onChange={(e) => setAssignee(e.target.value)}
              placeholder="선택사항"
            />
          </label>
        </div>
        <div className="ax-dialog-footer">
          <button className="ax-btn ax-btn-ghost" onClick={onClose}>취소</button>
          <button className="ax-btn ax-btn-primary" onClick={handleSubmit} disabled={!title.trim() || !templateId || submitting}>
            {submitting ? "생성 중..." : "생성"}
          </button>
        </div>
      </div>
    </div>
  );
}
