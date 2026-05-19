import React, { useState } from "react";
import { useApp } from "../../context/AppContext";
import { createTemplate } from "../../api/client";

interface Props {
  onClose: () => void;
}

export function CreateWorkflowDialog({ onClose }: Props) {
  const { selectedAgentId, refreshAll } = useApp();
  const [name, setName] = useState("");
  const [stages, setStages] = useState([{ name: "" }]);
  const [submitting, setSubmitting] = useState(false);

  const addStage = () => setStages([...stages, { name: "" }]);

  const removeStage = (index: number) => {
    if (stages.length <= 1) return;
    setStages(stages.filter((_, i) => i !== index));
  };

  const updateStageName = (index: number, value: string) => {
    const updated = [...stages];
    updated[index] = { name: value };
    setStages(updated);
  };

  const canSubmit = name.trim() && stages.every((s) => s.name.trim()) && stages.length >= 1;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      await createTemplate({
        agent_type_id: selectedAgentId,
        name: name.trim(),
        stages: stages.map((s) => ({ name: s.name.trim() })),
      });
      await refreshAll();
      onClose();
    } catch (e) {
      console.error("Failed to create template:", e);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="ax-overlay" onClick={onClose}>
      <div className="ax-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="ax-dialog-header">
          <h2>새 워크플로우 템플릿</h2>
        </div>
        <div className="ax-dialog-body">
          <label className="ax-label">
            워크플로우 이름
            <input
              className="ax-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="예: 블로그, 카드뉴스, 뉴스레터"
              autoFocus
            />
          </label>
          <div>
            <span className="ax-label" style={{ marginBottom: 8, display: "block" }}>단계 설정</span>
            {stages.map((stage, i) => (
              <div className="ax-stage-row" key={i}>
                <span className="ax-stage-order">{i + 1}</span>
                <input
                  className="ax-input"
                  style={{ flex: 1 }}
                  value={stage.name}
                  onChange={(e) => updateStageName(i, e.target.value)}
                  placeholder={`단계 ${i + 1} 이름`}
                  onKeyDown={(e) => e.key === "Enter" && (i === stages.length - 1 ? addStage() : undefined)}
                />
                <button
                  className="ax-btn ax-btn-ghost ax-btn-xs"
                  onClick={() => removeStage(i)}
                  disabled={stages.length <= 1}
                >
                  삭제
                </button>
              </div>
            ))}
            <button className="ax-btn ax-btn-ghost ax-btn-sm" onClick={addStage} style={{ marginTop: 4 }}>
              + 단계 추가
            </button>
          </div>
        </div>
        <div className="ax-dialog-footer">
          <button className="ax-btn ax-btn-ghost" onClick={onClose}>취소</button>
          <button className="ax-btn ax-btn-primary" onClick={handleSubmit} disabled={!canSubmit || submitting}>
            {submitting ? "생성 중..." : "템플릿 생성"}
          </button>
        </div>
      </div>
    </div>
  );
}
