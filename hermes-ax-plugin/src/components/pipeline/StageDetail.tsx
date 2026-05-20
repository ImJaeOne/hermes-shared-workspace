import React, { useState } from "react";
import type { Artifact, StageDefinition } from "../../types/models";
import type { WorkflowDetailResponse } from "../../types/api";
import { ArtifactList } from "../artifacts/ArtifactList";
import { createArtifact, getApiErrorMessage, uploadArtifact } from "../../api/client";
import { useApp } from "../../context/AppContext";

interface Props {
  stage: StageDefinition & { is_completed: boolean; is_current: boolean };
  artifacts: Artifact[];
  workflow: WorkflowDetailResponse;
  onRefresh: () => void;
}

export function StageDetail({ stage, artifacts, workflow, onRefresh }: Props) {
  const { authenticated, authLoading } = useApp();
  const [showAdd, setShowAdd] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newType, setNewType] = useState("");
  const [newContent, setNewContent] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const expectedTypes: string[] = (() => {
    try { return JSON.parse(stage.expected_artifacts); } catch { return []; }
  })();

  const handleAddArtifact = async () => {
    if (!newTitle.trim() || !newType || !authenticated) return;
    setSubmitting(true);
    setError("");
    try {
      if (selectedFile) {
        const formData = new FormData();
        formData.append("workflow_id", workflow.id);
        formData.append("stage_id", stage.id);
        formData.append("artifact_type", newType);
        formData.append("title", newTitle.trim());
        formData.append("status", "draft");
        formData.append("file", selectedFile);
        await uploadArtifact(formData);
      } else {
        await createArtifact({
          workflow_id: workflow.id,
          stage_id: stage.id,
          artifact_type: newType,
          title: newTitle.trim(),
          content: newContent,
          content_type: "text/markdown",
        });
      }
      setNewTitle("");
      setNewType("");
      setNewContent("");
      setSelectedFile(null);
      setShowAdd(false);
      onRefresh();
    } catch (e) {
      setError(getApiErrorMessage(e, "산출물을 추가하지 못했습니다."));
      console.error("Failed to create artifact:", e);
    } finally {
      setSubmitting(false);
    }
  };

  const hitlBadge = stage.transition_mode === "approval_required" ? (
    <span className="ax-badge ax-badge-approval">승인 필요</span>
  ) : null;

  return (
    <div className="ax-stage-detail">
      <div className="ax-stage-detail-header">
        <h3>{stage.name}</h3>
        <div className="ax-stage-detail-meta">
          {stage.is_completed && <span className="ax-badge" style={{ background: "rgba(74,222,128,0.1)", color: "var(--color-success, #4ade80)" }}>완료</span>}
          {stage.is_current && <span className="ax-badge" style={{ background: "rgba(255,189,56,0.1)", color: "var(--color-warning, #ffbd38)" }}>현재</span>}
          {!stage.is_completed && !stage.is_current && <span className="ax-badge" style={{ background: "var(--color-muted)", color: "var(--color-muted-foreground)" }}>예정</span>}
          {hitlBadge}
          {expectedTypes.length > 0 && (
            <span className="ax-stage-expected">예상 산출물: {expectedTypes.join(", ")}</span>
          )}
        </div>
        <button className="ax-btn ax-btn-primary ax-btn-sm" onClick={() => setShowAdd(!showAdd)} disabled={!authenticated || authLoading}>
          {showAdd ? "취소" : "+ 산출물 추가"}
        </button>
      </div>

      {!authenticated && <p className="ax-auth-required">로그인 후 산출물을 추가할 수 있습니다.</p>}

      {showAdd && authenticated && (
        <div className="ax-add-artifact">
          <label className="ax-label">
            유형
            <select className="ax-select" value={newType} onChange={(e) => setNewType(e.target.value)}>
              <option value="">유형 선택...</option>
              {expectedTypes.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
              <option value="other">기타</option>
            </select>
          </label>
          <label className="ax-label">
            제목
            <input className="ax-input" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="산출물 제목" />
          </label>
          <label className="ax-label">
            파일 업로드 (선택)
            <input
              type="file"
              className="ax-input ax-file-input"
              onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
            />
          </label>
          {selectedFile && (
            <div className="ax-file-preview">
              <span>{selectedFile.name}</span>
              <span className="ax-file-size">{(selectedFile.size / 1024).toFixed(1)} KB</span>
              <button className="ax-btn ax-btn-ghost ax-btn-xs" onClick={() => setSelectedFile(null)}>제거</button>
            </div>
          )}
          {!selectedFile && (
            <label className="ax-label">
              내용
              <textarea className="ax-textarea" value={newContent} onChange={(e) => setNewContent(e.target.value)} rows={5} placeholder="마크다운 또는 일반 텍스트..." />
            </label>
          )}
          <button className="ax-btn ax-btn-primary ax-btn-sm" onClick={handleAddArtifact} disabled={!newTitle.trim() || !newType || submitting}>
            {submitting ? "추가 중..." : "산출물 추가"}
          </button>
          {error && <p className="ax-form-error">{error}</p>}
        </div>
      )}

      <ArtifactList artifacts={artifacts} onRefresh={onRefresh} />
    </div>
  );
}
