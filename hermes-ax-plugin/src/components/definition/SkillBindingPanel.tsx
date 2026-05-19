import React, { useCallback, useEffect, useState } from "react";
import type { StageDefinition, Skill, WorkflowSkillBinding } from "../../types/models";
import { createSkillBinding, deleteSkillBinding, getSkillBindings } from "../../api/client";
import { useApp } from "../../context/AppContext";
import { SkillBindingItem } from "./SkillBindingItem";

interface Props {
  templateId: string;
  stages: StageDefinition[];
}

export function SkillBindingPanel({ templateId, stages }: Props) {
  const { skills } = useApp();
  const [bindings, setBindings] = useState<WorkflowSkillBinding[]>([]);
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [selectedStageId, setSelectedStageId] = useState("");
  const [executionOrder, setExecutionOrder] = useState(0);
  const [adding, setAdding] = useState(false);

  const loadBindings = useCallback(async () => {
    try {
      const data = await getSkillBindings(templateId);
      setBindings(data);
    } catch (e) {
      console.error("Failed to load bindings:", e);
    }
  }, [templateId]);

  useEffect(() => {
    loadBindings();
  }, [loadBindings]);

  const handleAdd = async () => {
    if (!selectedSkillId) return;
    setAdding(true);
    try {
      await createSkillBinding(templateId, {
        skill_id: selectedSkillId,
        stage_id: selectedStageId || null,
        execution_order: executionOrder,
      });
      setSelectedSkillId("");
      setSelectedStageId("");
      setExecutionOrder(bindings.length);
      loadBindings();
    } catch (e) {
      console.error("Failed to create binding:", e);
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (bindingId: number) => {
    try {
      await deleteSkillBinding(templateId, bindingId);
      loadBindings();
    } catch (e) {
      console.error("Failed to delete binding:", e);
    }
  };

  return (
    <div className="ax-binding-panel">
      <h3 className="ax-section-title">스킬 바인딩</h3>

      <div className="ax-binding-add">
        <select className="ax-select" value={selectedSkillId} onChange={(e) => setSelectedSkillId(e.target.value)}>
          <option value="">스킬 선택...</option>
          {skills.map((s) => (
            <option key={s.id} value={s.id}>{s.name}{s.agent_type_id ? ` (${s.agent_type_id})` : ' (전역)'}</option>
          ))}
        </select>
        <select className="ax-select" value={selectedStageId} onChange={(e) => setSelectedStageId(e.target.value)}>
          <option value="">전체 단계</option>
          {stages.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <input
          className="ax-input ax-input-narrow"
          type="number"
          min={0}
          value={executionOrder}
          onChange={(e) => setExecutionOrder(Number(e.target.value))}
          title="실행 순서"
        />
        <button className="ax-btn ax-btn-primary ax-btn-xs" onClick={handleAdd} disabled={!selectedSkillId || adding}>
          {adding ? "추가 중..." : "바인딩 추가"}
        </button>
      </div>

      <div className="ax-binding-list">
        {bindings.length === 0 ? (
          <div className="ax-empty">바인딩된 스킬이 없습니다.</div>
        ) : (
          bindings.map((b) => (
            <SkillBindingItem key={b.id} binding={b} onDelete={handleDelete} />
          ))
        )}
      </div>
    </div>
  );
}
