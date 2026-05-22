import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { downloadArtifactFile, getApiErrorMessage, getArtifact, getWorkflow } from "../../api/client";
import { useApp } from "../../context/AppContext";
import type { WorkflowDetailResponse } from "../../types/api";
import type { Artifact, StageDefinition, WorkflowInstance } from "../../types/models";
import { CreateInstanceDialog } from "../shared/CreateInstanceDialog";
import { EmptyState } from "../shared/EmptyState";
import { PriorityBadge, StatusBadge } from "../shared/StatusBadge";
import { ArtifactViewer } from "../artifacts/ArtifactViewer";

interface ProjectSummary {
  workflow: WorkflowInstance;
  stageName: string;
}

const NEXT_STAGE_PREVIEW = ["시놉시스", "스토리보드", "원고"];

export function PlanningProjectBoard() {
  const { boardData, setSelectedWorkflowId, setViewMode } = useApp();
  const [showCreateInstance, setShowCreateInstance] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [workflowDetail, setWorkflowDetail] = useState<WorkflowDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const detailRequestSeqRef = useRef(0);

  const projects = useMemo<ProjectSummary[]>(() => {
    if (!boardData) return [];

    const activeProjects = boardData.columns.flatMap((column) =>
      column.workflows.map((workflow) => ({
        workflow,
        stageName: workflow.current_stage_name || column.stage.name,
      })),
    );

    const completedProjects = boardData.completed.map((workflow) => ({
      workflow,
      stageName: workflow.current_stage_name || "완료",
    }));

    return [...activeProjects, ...completedProjects].sort((a, b) => {
      if (a.workflow.status === "completed" && b.workflow.status !== "completed") return 1;
      if (a.workflow.status !== "completed" && b.workflow.status === "completed") return -1;
      return new Date(b.workflow.updated_at).getTime() - new Date(a.workflow.updated_at).getTime();
    });
  }, [boardData]);

  useEffect(() => {
    if (projects.length === 0) {
      setSelectedProjectId(null);
      setWorkflowDetail(null);
      return;
    }
    if (!selectedProjectId || !projects.some((project) => project.workflow.id === selectedProjectId)) {
      setSelectedProjectId(projects[0].workflow.id);
    }
  }, [projects, selectedProjectId]);

  const loadWorkflowDetail = useCallback(async (workflowId: string) => {
    const requestSeq = detailRequestSeqRef.current + 1;
    detailRequestSeqRef.current = requestSeq;
    setDetailLoading(true);
    setDetailError("");
    try {
      const detail = await getWorkflow(workflowId);
      if (detailRequestSeqRef.current !== requestSeq) return;
      setWorkflowDetail(detail);
    } catch (error) {
      if (detailRequestSeqRef.current !== requestSeq) return;
      setWorkflowDetail(null);
      setDetailError(getApiErrorMessage(error, "회사 프로젝트 상세 정보를 불러오지 못했습니다."));
    } finally {
      if (detailRequestSeqRef.current === requestSeq) {
        setDetailLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!selectedProjectId) {
      detailRequestSeqRef.current += 1;
      setWorkflowDetail(null);
      setDetailLoading(false);
      return;
    }
    void loadWorkflowDetail(selectedProjectId);
  }, [selectedProjectId, loadWorkflowDetail]);

  const handleOpenPipeline = (workflowId: string) => {
    setSelectedWorkflowId(workflowId);
    setViewMode("pipeline");
  };

  if (!boardData) {
    return <EmptyState message="회사 프로젝트 목록을 불러오는 중입니다..." />;
  }

  if (boardData.columns.length === 0) {
    return <EmptyState message="기획 단계 설정이 없습니다. 관리자에게 기획 단계 설정을 요청하세요." />;
  }

  const selectedProject = projects.find((project) => project.workflow.id === selectedProjectId) ?? null;

  return (
    <div className="ax-planning-board">
      <section className="ax-planning-projects-panel">
        <div className="ax-planning-panel-header">
          <div>
            <p className="ax-eyebrow">기획 자료조사 MVP</p>
            <h2>회사 프로젝트</h2>
            <p className="ax-planning-help">회사명별로 자료조사 상태와 최신 산출물을 확인하세요.</p>
          </div>
          <button className="ax-btn ax-btn-primary ax-btn-sm" onClick={() => setShowCreateInstance(true)}>
            + 새 회사 프로젝트 시작
          </button>
        </div>

        {projects.length === 0 ? (
          <div className="ax-planning-empty-card">
            <strong>아직 시작된 회사 프로젝트가 없습니다.</strong>
            <span>새 회사 프로젝트를 시작하면 자료조사 단계부터 진행 상태가 표시됩니다.</span>
          </div>
        ) : (
          <div className="ax-planning-project-list">
            {projects.map((project) => {
              const workflow = project.workflow;
              const isSelected = workflow.id === selectedProjectId;
              return (
                <button
                  key={workflow.id}
                  className={`ax-planning-project-card ${isSelected ? "ax-planning-project-card-active" : ""}`}
                  onClick={() => setSelectedProjectId(workflow.id)}
                >
                  <div className="ax-planning-project-card-main">
                    <div>
                      <span className="ax-planning-company-name">{workflow.title}</span>
                      <span className="ax-planning-stage-label">{getPlanningStageLabel(project.stageName, workflow.status)}</span>
                    </div>
                    <div className="ax-planning-project-badges">
                      <PriorityBadge priority={workflow.priority} />
                      <StatusBadge status={workflow.status} />
                    </div>
                  </div>
                  <div className="ax-planning-project-meta">
                    <span>산출물 {workflow.artifact_count ?? 0}개</span>
                    <span>{workflow.assignee ? `담당자 ${workflow.assignee}` : "담당자 미지정"}</span>
                    <span>{formatTimeAgo(workflow.updated_at)}</span>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </section>

      <section className="ax-planning-detail-panel">
        {!selectedProject ? (
          <div className="ax-planning-detail-placeholder">
            <h3>회사 프로젝트를 선택하세요</h3>
            <p>선택한 회사의 자료조사 진행 상태와 최신 산출물이 여기에 표시됩니다.</p>
          </div>
        ) : detailLoading ? (
          <EmptyState message="자료조사 상세 정보를 불러오는 중입니다..." />
        ) : detailError ? (
          <div className="ax-planning-detail-placeholder ax-planning-detail-error">
            <h3>상세 정보를 불러오지 못했습니다</h3>
            <p>{detailError}</p>
          </div>
        ) : workflowDetail ? (
          <ProjectDetail workflow={workflowDetail} onOpenPipeline={() => handleOpenPipeline(workflowDetail.id)} />
        ) : (
          <div className="ax-planning-detail-placeholder">
            <h3>{selectedProject.workflow.title}</h3>
            <p>상세 정보를 선택하면 자료조사 산출물이 표시됩니다.</p>
          </div>
        )}
      </section>

      {showCreateInstance && <CreateInstanceDialog onClose={() => setShowCreateInstance(false)} />}
    </div>
  );
}

function ProjectDetail({ workflow, onOpenPipeline }: { workflow: WorkflowDetailResponse; onOpenPipeline: () => void }) {
  const currentStage = workflow.stages.find((stage) => stage.is_current);
  const latestArtifacts = useMemo(() => {
    const latestOnly = workflow.artifacts.filter((artifact) => artifact.is_latest !== 0);
    const candidates = latestOnly.length > 0 ? latestOnly : workflow.artifacts;
    return [...candidates]
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
      .slice(0, 6);
  }, [workflow.artifacts]);
  const latestArtifactIds = latestArtifacts.map((artifact) => artifact.id).join("|");
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(latestArtifacts[0]?.id ?? null);
  const [selectedArtifact, setSelectedArtifact] = useState<Artifact | null>(null);
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [artifactError, setArtifactError] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const artifactRequestSeqRef = useRef(0);
  const completedCount = workflow.stages.filter((stage) => stage.is_completed).length;
  const progressCount = Math.min(workflow.stages.length, completedCount + 1);
  const progressPercent = workflow.status === "completed"
    ? 100
    : workflow.stages.length > 0
      ? Math.round((progressCount / workflow.stages.length) * 100)
      : 0;

  useEffect(() => {
    if (latestArtifacts.length === 0) {
      setSelectedArtifactId(null);
      setSelectedArtifact(null);
      return;
    }
    if (!selectedArtifactId || !latestArtifacts.some((artifact) => artifact.id === selectedArtifactId)) {
      setSelectedArtifactId(latestArtifacts[0].id);
    }
  }, [latestArtifactIds, latestArtifacts, selectedArtifactId]);

  useEffect(() => {
    if (!selectedArtifactId) {
      artifactRequestSeqRef.current += 1;
      setSelectedArtifact(null);
      setArtifactLoading(false);
      setArtifactError("");
      return;
    }

    const requestSeq = artifactRequestSeqRef.current + 1;
    artifactRequestSeqRef.current = requestSeq;
    setArtifactLoading(true);
    setArtifactError("");
    setDownloadError("");
    void getArtifact(selectedArtifactId)
      .then((artifact) => {
        if (artifactRequestSeqRef.current !== requestSeq) return;
        setSelectedArtifact(artifact);
      })
      .catch((error) => {
        if (artifactRequestSeqRef.current !== requestSeq) return;
        setSelectedArtifact(null);
        setArtifactError(getApiErrorMessage(error, "산출물 상세 정보를 불러오지 못했습니다."));
      })
      .finally(() => {
        if (artifactRequestSeqRef.current === requestSeq) {
          setArtifactLoading(false);
        }
      });
  }, [selectedArtifactId]);

  const handleDownloadSelectedArtifact = async () => {
    if (!selectedArtifact) return;
    setDownloadError("");
    try {
      await downloadArtifactFile(selectedArtifact.id, getArtifactDownloadName(selectedArtifact));
    } catch (error) {
      setDownloadError(getApiErrorMessage(error, "산출물을 다운로드하지 못했습니다."));
    }
  };

  return (
    <div className="ax-planning-detail-content">
      <div className="ax-planning-detail-header">
        <div>
          <p className="ax-eyebrow">선택한 회사</p>
          <h2>{workflow.title}</h2>
          <div className="ax-planning-detail-meta">
            <StatusBadge status={workflow.status} />
            <PriorityBadge priority={workflow.priority} />
            {workflow.assignee && <span>담당자 {workflow.assignee}</span>}
            <span>최근 업데이트 {formatDateTime(workflow.updated_at)}</span>
          </div>
        </div>
        <button className="ax-btn ax-btn-ghost ax-btn-sm" onClick={onOpenPipeline}>
          상세 진행 관리
        </button>
      </div>

      <div className="ax-planning-research-summary">
        <div>
          <p className="ax-eyebrow">현재 기획 단계</p>
          <strong>{getPlanningStageLabel(currentStage?.name ?? workflow.current_stage_name ?? "자료조사", workflow.status)}</strong>
          <span>{workflow.artifacts.length}개 산출물 · {progressPercent}% 진행</span>
        </div>
        <div className="ax-planning-progress-bar" aria-label={`기획 단계 ${progressPercent}% 진행`}>
          <span style={{ width: `${progressPercent}%` }} />
        </div>
      </div>

      <div className="ax-planning-section-grid">
        <section className="ax-planning-section-card">
          <div className="ax-planning-section-header">
            <h3>자료조사 진행 상태</h3>
            <span>{currentStage ? formatStageStatus(currentStage) : "대기"}</span>
          </div>
          <div className="ax-planning-stage-list">
            {workflow.stages.map((stage) => (
              <StageStatusRow key={stage.id} stage={stage} />
            ))}
          </div>
        </section>

        <section className="ax-planning-section-card">
          <div className="ax-planning-section-header">
            <h3>최신 산출물</h3>
            <span>{workflow.artifacts.length}개</span>
          </div>
          {latestArtifacts.length === 0 ? (
            <p className="ax-planning-muted">아직 등록된 산출물이 없습니다. 자료조사가 완료되면 이 영역에 결과물이 표시됩니다.</p>
          ) : (
            <div className="ax-planning-artifact-list">
              {latestArtifacts.map((artifact) => (
                <ArtifactRow
                  key={artifact.id}
                  artifact={artifact}
                  stages={workflow.stages}
                  selected={artifact.id === selectedArtifactId}
                  onSelect={() => setSelectedArtifactId(artifact.id)}
                />
              ))}
            </div>
          )}
          <div className="ax-planning-artifact-preview">
            <div className="ax-planning-artifact-preview-header">
              <div>
                <p className="ax-eyebrow">산출물 미리보기</p>
                <h4>{selectedArtifact?.title ?? "산출물을 선택하세요"}</h4>
                {selectedArtifact && (
                  <span>
                    v{selectedArtifact.version ?? 1} · {selectedArtifact.mime_type || selectedArtifact.content_type}
                    {selectedArtifact.original_filename ? ` · ${selectedArtifact.original_filename}` : ""}
                  </span>
                )}
              </div>
              <button
                className="ax-btn ax-btn-ghost ax-btn-sm"
                onClick={handleDownloadSelectedArtifact}
                disabled={!selectedArtifact || artifactLoading}
              >
                다운로드
              </button>
            </div>
            {artifactLoading ? (
              <p className="ax-planning-muted">산출물 미리보기를 불러오는 중입니다...</p>
            ) : artifactError ? (
              <p className="ax-form-error">{artifactError}</p>
            ) : selectedArtifact ? (
              <ArtifactViewer artifact={selectedArtifact} />
            ) : (
              <p className="ax-planning-muted">최신 산출물 행을 선택하면 미리보기가 표시됩니다.</p>
            )}
            {downloadError && <p className="ax-form-error">{downloadError}</p>}
          </div>
        </section>
      </div>

      <section className="ax-planning-next-preview">
        <div>
          <h3>다음 단계 미리보기</h3>
          <p>1차 MVP에서는 자료조사 이후 단계는 비활성 상태로만 표시합니다.</p>
        </div>
        <div className="ax-planning-next-items">
          {NEXT_STAGE_PREVIEW.map((label) => (
            <span key={label} className="ax-planning-next-item">{label}</span>
          ))}
        </div>
      </section>
    </div>
  );
}

function StageStatusRow({ stage }: { stage: StageDefinition & { is_completed: boolean; is_current: boolean } }) {
  const stateClass = stage.is_completed ? "done" : stage.is_current ? "current" : "disabled";
  return (
    <div className={`ax-planning-stage-row ax-planning-stage-row-${stateClass}`}>
      <span className="ax-planning-stage-dot" />
      <div>
        <strong>{getPlanningStageLabel(stage.name)}</strong>
        <span>{formatStageStatus(stage)}</span>
      </div>
    </div>
  );
}

function ArtifactRow({ artifact, stages, selected, onSelect }: { artifact: Artifact; stages: StageDefinition[]; selected: boolean; onSelect: () => void }) {
  const stageName = stages.find((stage) => stage.id === artifact.stage_id)?.name;
  return (
    <button
      type="button"
      className={`ax-planning-artifact-row ${selected ? "ax-planning-artifact-row-active" : ""}`}
      onClick={onSelect}
    >
      <div>
        <strong>{artifact.title}</strong>
        <span>
          {getPlanningStageLabel(stageName ?? artifact.artifact_type)} · {artifact.artifact_type}
          {artifact.version ? ` · v${artifact.version}` : ""}
        </span>
      </div>
      <div className="ax-planning-artifact-meta">
        <StatusBadge status={artifact.status} />
        <span>{formatDateTime(artifact.updated_at)}</span>
      </div>
    </button>
  );
}

function getPlanningStageLabel(stageName: string, status?: string): string {
  const label = stageName.trim();
  const normalized = label.toLowerCase();
  const isWorkflowStatusLabel = Boolean(status);

  if (label.includes("자료 요청") || normalized.includes("material-requesting")) return "자료 요청 중";
  if (label.includes("자료 확인") || normalized.includes("material-waiting")) return "자료 확인 대기";
  if (label.includes("자료조사 실행") || normalized.includes("research-running")) return "자료조사 실행 중";
  if (label.includes("사용자 검토") || normalized.includes("user-review-waiting")) return "사용자 검토 대기";
  if (label.includes("수정 요청") || normalized.includes("revision-running")) return "수정 요청 처리 중";
  if (label.includes("자료조사 확정") || normalized.includes("research-confirmed")) return "자료조사 확정";
  if (normalized.includes("source_material")) return "전달 자료";
  if (normalized.includes("research_report")) return "자료조사 결과";

  if (status === "completed") return "기획 자료 정리 완료";
  if (status === "pending_approval") return "검토 대기";
  if (status === "paused") return "일시정지";
  if (status === "failed") return "확인 필요";

  if (normalized.includes("research") || normalized.includes("자료") || normalized.includes("조사")) {
    return isWorkflowStatusLabel ? "자료조사 진행 중" : "자료조사";
  }
  if (normalized.includes("synopsis") || normalized.includes("시놉")) return isWorkflowStatusLabel ? "시놉시스 준비" : "시놉시스";
  if (normalized.includes("storyboard") || normalized.includes("스토리")) return isWorkflowStatusLabel ? "스토리보드 준비" : "스토리보드";
  if (normalized.includes("script") || normalized.includes("원고")) return isWorkflowStatusLabel ? "원고 준비" : "원고";
  if (normalized.includes("done") || normalized.includes("완료")) return "기획 자료 정리 완료";
  return label || "자료조사 진행 중";
}

function formatStageStatus(stage: { is_completed?: boolean; is_current?: boolean }): string {
  if (stage.is_completed) return "완료";
  if (stage.is_current) return "진행 중";
  return "다음 단계";
}

function getArtifactDownloadName(artifact: Artifact): string {
  if (artifact.original_filename) return artifact.original_filename;
  const safeTitle = artifact.title.trim().replace(/[\\/:*?"<>|]+/g, "_") || artifact.id;
  const mime = artifact.mime_type || artifact.content_type;
  const ext = mime === "text/markdown"
    ? "md"
    : mime === "text/plain"
      ? "txt"
      : mime === "application/json"
        ? "json"
        : "bin";
  return `${safeTitle}.${ext}`;
}

function formatDateTime(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleString("ko-KR", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function formatTimeAgo(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return "방금";
    if (diffMin < 60) return `${diffMin}분 전`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}시간 전`;
    const diffDay = Math.floor(diffHr / 24);
    return `${diffDay}일 전`;
  } catch {
    return "";
  }
}
