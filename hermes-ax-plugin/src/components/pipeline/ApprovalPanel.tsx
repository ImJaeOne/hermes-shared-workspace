import React, { useState } from "react";
import type { ApprovalRequest } from "../../types/models";
import { decideApproval, getApiErrorMessage } from "../../api/client";
import { useApp } from "../../context/AppContext";

interface Props {
  approval: ApprovalRequest;
  onDecided: () => void;
}

export function ApprovalPanel({ approval, onDecided }: Props) {
  const { authenticated, authLoading, currentUserLabel, authUser } = useApp();
  const [note, setNote] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [error, setError] = useState("");

  const handleDecide = async (status: "approved" | "rejected") => {
    if (!authenticated) return;
    setDeciding(true);
    setError("");
    try {
      await decideApproval(approval.id, {
        status,
        decided_by: currentUserLabel || authUser?.username || "user",
        note: note.trim() || undefined,
      });
      onDecided();
    } catch (e) {
      setError(getApiErrorMessage(e, "승인 상태를 변경하지 못했습니다."));
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
      {!authenticated && <p className="ax-auth-required">로그인 후 승인 또는 반려할 수 있습니다.</p>}
      <div className="ax-approval-form">
        <textarea
          className="ax-textarea"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="사유 (선택)..."
          rows={2}
          disabled={!authenticated || authLoading || deciding}
        />
        <div className="ax-approval-actions">
          <button
            className="ax-btn ax-btn-sm"
            style={{ background: "rgba(251,44,54,0.15)", color: "#fb2c36", borderColor: "rgba(251,44,54,0.3)" }}
            onClick={() => handleDecide("rejected")}
            disabled={!authenticated || authLoading || deciding}
          >
            반려
          </button>
          <button
            className="ax-btn ax-btn-sm"
            style={{ background: "rgba(74,222,128,0.15)", color: "#4ade80", borderColor: "rgba(74,222,128,0.3)" }}
            onClick={() => handleDecide("approved")}
            disabled={!authenticated || authLoading || deciding}
          >
            승인
          </button>
        </div>
        {error && <p className="ax-form-error">{error}</p>}
      </div>
    </div>
  );
}
