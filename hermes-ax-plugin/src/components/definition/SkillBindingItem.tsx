import React from "react";
import type { WorkflowSkillBinding } from "../../types/models";

interface Props {
  binding: WorkflowSkillBinding;
  onDelete: (bindingId: number) => void;
}

export function SkillBindingItem({ binding, onDelete }: Props) {
  return (
    <div className="ax-binding-item">
      <div className="ax-binding-item-info">
        <span className="ax-binding-order">#{binding.execution_order}</span>
        <span className="ax-binding-skill-name">{binding.skill_name || binding.skill_id}</span>
        {binding.skill_description && (
          <span className="ax-binding-skill-desc">{binding.skill_description}</span>
        )}
        {binding.stage_id ? (
          <span className="ax-badge" style={{ background: "var(--color-muted)", color: "var(--color-muted-foreground)" }}>
            특정 단계
          </span>
        ) : (
          <span className="ax-badge" style={{ background: "rgba(74,222,128,0.1)", color: "var(--color-success, #4ade80)" }}>
            전체 단계
          </span>
        )}
      </div>
      <button className="ax-btn ax-btn-ghost ax-btn-xs" onClick={() => onDelete(binding.id)}>
        제거
      </button>
    </div>
  );
}
