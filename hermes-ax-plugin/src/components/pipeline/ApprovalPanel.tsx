import React, { useState } from "react";
import type { ApprovalRequest } from "../../types/models";
import { decideApproval } from "../../api/client";
import { useApp } from "../../context/AppContext";

interface Props {
  approval: ApprovalRequest;
  onDecided: () => void;
}

export function ApprovalPanel({ approval, onDecided }: Props) {
  const { username } = useApp();
  const [note, setNote] = useState("");
  const [deciding, setDeciding] = useState(false);

  const handleDecide = async (status: "approved" | "rejected") => {
    const decidedBy = username || "anonymous";
    setDeciding(true);
    try {
      await decideApproval(approval.id, { status, decided_by: decidedBy, note });
      onDecided();
    } catch (e) {
      console.error("Failed to decide approval:", e);
    } finally {
      setDeciding(false);
    }
  };

  return (
    <div className="ax-approval-panel">
      <div className="ax-approval-header">
        <span className="ax-approval-icon">&#9888;</span>
        <span className="ax-approval-title">승인 대기 중</span>
      </div>
      <p className="ax-approval-desc">
        다음 단계로 진행하려면 승인이 필요합니다.
        {approval.stage_name && <> 대상 단계: <strong>{approval.stage_name}</strong></>}
      </p>
      <div className="ax-approval-form">
        <textarea
          className="ax-textarea"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="사유 (선택)..."
          rows={2}
        />
        <div className="ax-approval-actions">
          <button
            className="ax-btn ax-btn-sm"
            style={{ background: "rgba(251,44,54,0.15)", color: "#fb2c36", borderColor: "rgba(251,44,54,0.3)" }}
            onClick={() => handleDecide("rejected")}
            disabled={deciding}
          >
            반려
          </button>
          <button
            className="ax-btn ax-btn-sm"
            style={{ background: "rgba(74,222,128,0.15)", color: "#4ade80", borderColor: "rgba(74,222,128,0.3)" }}
            onClick={() => handleDecide("approved")}
            disabled={deciding}
          >
            승인
          </button>
        </div>
      </div>
    </div>
  );
}
