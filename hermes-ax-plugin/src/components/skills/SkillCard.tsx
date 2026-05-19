import React from "react";
import type { Skill } from "../../types/models";

interface Props {
  skill: Skill;
  onEdit: (skill: Skill) => void;
  onDelete: (skill: Skill) => void;
}

export function SkillCard({ skill, onEdit, onDelete }: Props) {
  return (
    <div className="ax-skill-card">
      <div className="ax-skill-card-header">
        <div className="ax-skill-card-info">
          <span className="ax-skill-card-name">{skill.name}</span>
          {skill.agent_type_id ? (
            <span className="ax-badge" style={{ background: "var(--color-muted)", color: "var(--color-muted-foreground)" }}>
              {skill.agent_type_id}
            </span>
          ) : (
            <span className="ax-badge" style={{ background: "rgba(167,139,250,0.15)", color: "#a78bfa" }}>
              전역
            </span>
          )}
        </div>
        <div className="ax-skill-card-actions">
          <button className="ax-btn ax-btn-ghost ax-btn-xs" onClick={() => onEdit(skill)}>편집</button>
          <button className="ax-btn ax-btn-ghost ax-btn-xs" onClick={() => onDelete(skill)}>삭제</button>
        </div>
      </div>
      {skill.description && (
        <p className="ax-skill-card-desc">{skill.description}</p>
      )}
      {skill.content && (
        <pre className="ax-skill-card-preview">{skill.content.slice(0, 200)}{skill.content.length > 200 ? "..." : ""}</pre>
      )}
    </div>
  );
}
