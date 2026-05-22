import React, { useCallback, useEffect, useState } from "react";
import { useApp } from "../../context/AppContext";
import { getAgents, getDefinition, updateDefinition } from "../../api/client";
import type { StageDefinition, WorkflowDefinition } from "../../types/models";
import { MarkdownEditor } from "../shared/MarkdownEditor";
import { SkillBindingPanel } from "./SkillBindingPanel";
import { StageHITLConfig } from "./StageHITLConfig";

export function DefinitionEditorView() {
  const { selectedAgentId, selectedTemplateId, agents } = useApp();
  const [definition, setDefinition] = useState<WorkflowDefinition | null>(null);
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [stages, setStages] = useState<StageDefinition[]>([]);

  const agent = agents.find((a) => a.id === selectedAgentId);
  const template = selectedTemplateId
    ? agent?.templates?.find((t) => t.id === selectedTemplateId)
    : agent?.templates?.[0];
  const templateId = template?.id;
  const isPlanning = selectedAgentId === "planning";

  const loadDefinition = useCallback(async () => {
    if (!templateId) return;
    try {
      const defn = await getDefinition(templateId);
      setDefinition(defn);
      setContent(defn.content || "");
    } catch (e) {
      console.error("Failed to load definition:", e);
    }
  }, [templateId]);

  const loadStages = useCallback(async () => {
    if (!template) return;
    setStages(template.stages || []);
  }, [template]);

  const refreshAgentStages = useCallback(async () => {
    try {
      const data = await getAgents();
      const ag = data.find((a) => a.id === selectedAgentId);
      const tmpl = selectedTemplateId
        ? ag?.templates?.find((t) => t.id === selectedTemplateId)
        : ag?.templates?.[0];
      if (tmpl) {
        setStages(tmpl.stages || []);
      }
    } catch (e) {
      console.error("Failed to refresh stages:", e);
    }
  }, [selectedAgentId, selectedTemplateId]);

  useEffect(() => {
    loadDefinition();
    loadStages();
  }, [loadDefinition, loadStages]);

  const handleSave = async () => {
    if (!templateId) return;
    setSaving(true);
    try {
      await updateDefinition(templateId, { content });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      console.error("Failed to save definition:", e);
    } finally {
      setSaving(false);
    }
  };

  if (!templateId) {
    return <div className="ax-empty">활성 템플릿이 없습니다.</div>;
  }

  return (
    <div className="ax-definition-view">
      <div className="ax-definition-header">
        <h2 className="ax-section-title">{isPlanning ? "기획 단계 설정" : "워크플로우 정의"} — {template?.name}</h2>
        <div className="ax-definition-actions">
          {saved && <span className="ax-save-indicator">저장됨</span>}
          <button className="ax-btn ax-btn-primary ax-btn-sm" onClick={handleSave} disabled={saving}>
            {saving ? "저장 중..." : "플레이북 저장"}
          </button>
        </div>
      </div>

      <div className="ax-definition-content">
        <div className="ax-definition-editor-section">
          <h3 className="ax-section-title">플레이북 (마크다운)</h3>
          <MarkdownEditor
            value={content}
            onChange={setContent}
            placeholder={isPlanning ? "기획 단계 운영 메모를 작성하세요... (자료조사 기준, 검토 조건 등)" : "워크플로우 플레이북을 작성하세요... (스킬 실행 방법, 상태 전환 조건 등)"}
            rows={16}
          />
        </div>

        <div className="ax-definition-panels">
          <SkillBindingPanel templateId={templateId} stages={stages} />
          <StageHITLConfig stages={stages} onRefresh={refreshAgentStages} />
        </div>
      </div>
    </div>
  );
}
