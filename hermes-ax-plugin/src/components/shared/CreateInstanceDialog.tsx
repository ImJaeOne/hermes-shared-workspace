import React, { useState } from "react";
import { useApp } from "../../context/AppContext";
import { createWorkflow, getApiErrorMessage } from "../../api/client";

interface Props {
  onClose: () => void;
}

export function CreateInstanceDialog({ onClose }: Props) {
  const { boardData, refreshBoard, authenticated, authLoading } = useApp();
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState(0);
  const [assignee, setAssignee] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const templateId = boardData?.template_id;

  const handleSubmit = async () => {
    if (!title.trim() || !templateId || !authenticated) return;
    setSubmitting(true);
    setError("");
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
      setError(getApiErrorMessage(e, "워크플로우를 생성하지 못했습니다."));
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
          {!authenticated && <p className="ax-auth-required">로그인 후 새 티켓을 생성할 수 있습니다.</p>}
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
          {error && <p className="ax-form-error">{error}</p>}
        </div>
        <div className="ax-dialog-footer">
          <button className="ax-btn ax-btn-ghost" onClick={onClose}>취소</button>
          <button className="ax-btn ax-btn-primary" onClick={handleSubmit} disabled={!title.trim() || !templateId || !authenticated || authLoading || submitting}>
            {submitting ? "생성 중..." : "생성"}
          </button>
        </div>
      </div>
    </div>
  );
}
