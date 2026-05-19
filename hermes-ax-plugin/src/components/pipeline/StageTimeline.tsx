import React from "react";
import type { TransitionMode } from "../../types/models";

interface StageWithStatus {
  id: string;
  name: string;
  stage_order: number;
  is_completed: boolean;
  is_current: boolean;
  transition_mode: TransitionMode;
}

interface Props {
  stages: StageWithStatus[];
  selectedStageId: string | null;
  onSelectStage: (id: string) => void;
}

export function StageTimeline({ stages, selectedStageId, onSelectStage }: Props) {
  return (
    <div className="ax-timeline">
      {stages.map((stage, i) => {
        const isSelected = stage.id === selectedStageId;
        let nodeClass = "ax-timeline-node";
        if (stage.is_completed) nodeClass += " ax-timeline-node-completed";
        else if (stage.is_current) nodeClass += " ax-timeline-node-current";
        else nodeClass += " ax-timeline-node-future";
        if (isSelected) nodeClass += " ax-timeline-node-selected";

        return (
          <React.Fragment key={stage.id}>
            {i > 0 && (
              <div className={`ax-timeline-connector ${stage.is_completed ? "ax-timeline-connector-done" : ""}`} />
            )}
            <button className={nodeClass} onClick={() => onSelectStage(stage.id)}>
              <span className="ax-timeline-dot">
                {stage.transition_mode === "approval_required" && (
                  <span className="ax-timeline-lock" title="승인 필요">&#128274;</span>
                )}
              </span>
              <span className="ax-timeline-label">{stage.name}</span>
            </button>
          </React.Fragment>
        );
      })}
    </div>
  );
}
