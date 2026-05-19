import React, { useState } from "react";
import type { StageDefinition } from "../../types/models";
import { updateStage } from "../../api/client";

interface Props {
  stages: StageDefinition[];
  onRefresh: () => void;
}

export function StageHITLConfig({ stages, onRefresh }: Props) {
  const [updating, setUpdating] = useState<string | null>(null);

  const handleToggle = async (stage: StageDefinition) => {
    setUpdating(stage.id);
    const newMode = stage.transition_mode === "auto" ? "approval_required" : "auto";
    try {
      await updateStage(stage.id, { transition_mode: newMode });
      onRefresh();
    } catch (e) {
      console.error("Failed to update stage:", e);
    } finally {
      setUpdating(null);
    }
  };

  return (
    <div className="ax-hitl-config">
      <h3 className="ax-section-title">Step별 HITL 설정</h3>
      <div className="ax-hitl-list">
        {stages.map((stage) => (
          <div key={stage.id} className="ax-hitl-item">
            <div className="ax-hitl-item-info">
              <span className="ax-hitl-stage-name">{stage.name}</span>
              <span className={`ax-badge ${stage.transition_mode === "approval_required" ? "ax-badge-approval" : ""}`}>
                {stage.transition_mode === "approval_required" ? "승인 필요" : "자동"}
              </span>
            </div>
            <button
              className="ax-btn ax-btn-ghost ax-btn-xs"
              onClick={() => handleToggle(stage)}
              disabled={updating === stage.id}
            >
              {updating === stage.id ? "변경 중..." : stage.transition_mode === "auto" ? "승인 필요로 변경" : "자동으로 변경"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
