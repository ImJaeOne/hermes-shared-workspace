import React, { useState } from "react";
import type { Skill } from "../../types/models";
import { createSkill, updateSkill } from "../../api/client";
import { useApp } from "../../context/AppContext";
import { MarkdownEditor } from "../shared/MarkdownEditor";

interface Props {
  skill?: Skill | null;
  onClose: () => void;
  onSaved: () => void;
}

export function SkillEditorDialog({ skill, onClose, onSaved }: Props) {
  const { agents, selectedAgentId } = useApp();
  const isEdit = !!skill;
  const [name, setName] = useState(skill?.name || "");
  const [description, setDescription] = useState(skill?.description || "");
  const [content, setContent] = useState(skill?.content || "");
  const [agentTypeId, setAgentTypeId] = useState(skill?.agent_type_id || selectedAgentId || "");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      const body = {
        name: name.trim(),
        description,
        content,
        agent_type_id: agentTypeId || null,
      };
      if (isEdit && skill) {
        await updateSkill(skill.id, body);
      } else {
        await createSkill(body);
      }
      onSaved();
      onClose();
    } catch (e) {
      console.error("Failed to save skill:", e);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="ax-overlay" onClick={onClose}>
      <div className="ax-dialog ax-dialog-wide" onClick={(e) => e.stopPropagation()}>
        <div className="ax-dialog-header">
          <h2>{isEdit ? "스킬 수정" : "새 스킬 생성"}</h2>
        </div>
        <div className="ax-dialog-body">
          <label className="ax-label">
            이름
            <input className="ax-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="스킬 이름" />
          </label>
          <label className="ax-label">
            설명
            <input className="ax-input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="스킬 설명 (선택)" />
          </label>
          <label className="ax-label">
            에이전트 타입
            <select className="ax-select" value={agentTypeId} onChange={(e) => setAgentTypeId(e.target.value)}>
              <option value="">전역 (모든 에이전트)</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </label>
          <label className="ax-label">
            프롬프트 내용 (마크다운)
          </label>
          <MarkdownEditor
            value={content}
            onChange={setContent}
            placeholder="스킬 프롬프트를 마크다운으로 작성하세요..."
            rows={14}
          />
        </div>
        <div className="ax-dialog-footer">
          <button className="ax-btn ax-btn-ghost ax-btn-sm" onClick={onClose}>취소</button>
          <button className="ax-btn ax-btn-primary ax-btn-sm" onClick={handleSubmit} disabled={!name.trim() || submitting}>
            {submitting ? "저장 중..." : isEdit ? "수정" : "생성"}
          </button>
        </div>
      </div>
    </div>
  );
}
