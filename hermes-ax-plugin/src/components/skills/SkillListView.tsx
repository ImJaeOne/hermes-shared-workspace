import React, { useState } from "react";
import { useApp } from "../../context/AppContext";
import { deleteSkill } from "../../api/client";
import type { Skill } from "../../types/models";
import { SkillCard } from "./SkillCard";
import { SkillEditorDialog } from "./SkillEditorDialog";

export function SkillListView() {
  const { skills, refreshSkills, agents, selectedAgentId } = useApp();
  const [search, setSearch] = useState("");
  const [filterAgent, setFilterAgent] = useState("");
  const [editingSkill, setEditingSkill] = useState<Skill | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const filtered = skills.filter((s) => {
    const matchSearch = !search || s.name.toLowerCase().includes(search.toLowerCase()) || s.description.toLowerCase().includes(search.toLowerCase());
    const matchAgent = !filterAgent || s.agent_type_id === filterAgent || (!s.agent_type_id && filterAgent === "global");
    return matchSearch && matchAgent;
  });

  const handleDelete = async (skill: Skill) => {
    if (!confirm(`"${skill.name}" 스킬을 삭제하시겠습니까?`)) return;
    try {
      await deleteSkill(skill.id);
      refreshSkills();
    } catch (e) {
      console.error("Failed to delete skill:", e);
    }
  };

  return (
    <div className="ax-skills-view">
      <div className="ax-skills-header">
        <h2 className="ax-section-title">스킬 관리 — {agents.find((a) => a.id === selectedAgentId)?.name || selectedAgentId}</h2>
        <button className="ax-btn ax-btn-primary ax-btn-sm" onClick={() => setShowCreate(true)}>
          + 새 스킬
        </button>
      </div>

      <div className="ax-skills-filters">
        <input
          className="ax-input"
          placeholder="스킬 검색..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="ax-select" value={filterAgent} onChange={(e) => setFilterAgent(e.target.value)}>
          <option value="">모든 타입</option>
          <option value="global">전역</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
      </div>

      <div className="ax-skills-list">
        {filtered.length === 0 ? (
          <div className="ax-empty">등록된 스킬이 없습니다.</div>
        ) : (
          filtered.map((skill) => (
            <SkillCard
              key={skill.id}
              skill={skill}
              onEdit={setEditingSkill}
              onDelete={handleDelete}
            />
          ))
        )}
      </div>

      {showCreate && (
        <SkillEditorDialog onClose={() => setShowCreate(false)} onSaved={refreshSkills} />
      )}
      {editingSkill && (
        <SkillEditorDialog skill={editingSkill} onClose={() => setEditingSkill(null)} onSaved={refreshSkills} />
      )}
    </div>
  );
}
