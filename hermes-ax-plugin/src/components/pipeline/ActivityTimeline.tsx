import React, { useMemo } from "react";
import type { ActivityLog, StageDefinition } from "../../types/models";

interface Props {
  activityLogs?: ActivityLog[];
  stages: Array<Pick<StageDefinition, "id" | "name">>;
}

const ACTION_LABELS: Record<string, string> = {
  "workflow.create": "워크플로우 생성",
  "workflow.transition": "단계 전환",
  "workflow.request_approval": "승인 요청",
  "approval.approved": "승인 완료",
  "approval.rejected": "반려",
  "artifact.create": "산출물 생성",
  "artifact.update": "산출물 수정",
  "artifact.upload": "산출물 업로드",
  "comment.create": "코멘트 작성",
  "comment.update": "코멘트 수정",
  "comment.delete": "코멘트 삭제",
  "auth.login": "로그인",
  "auth.logout": "로그아웃",
};

const ACTOR_KIND_LABELS: Record<ActivityLog["actor_kind"], string> = {
  human: "사람",
  agent: "에이전트",
  system: "시스템",
};

function safeParseMetadata(metadataJson: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(metadataJson || "{}");
    return parsed && typeof parsed === "object" ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function formatDateTime(value: string): string {
  try {
    return new Date(value).toLocaleString("ko-KR");
  } catch {
    return value;
  }
}

function formatActionLabel(action: string): string {
  return ACTION_LABELS[action] || action;
}

function getStageName(stageMap: Map<string, string>, rawValue: unknown): string | null {
  if (typeof rawValue !== "string" || !rawValue) return null;
  return stageMap.get(rawValue) || rawValue;
}

function buildSummary(log: ActivityLog, stageMap: Map<string, string>): string[] {
  const metadata = safeParseMetadata(log.metadata_json);
  const lines: string[] = [];

  const fromStage = getStageName(stageMap, metadata.from_stage_id ?? metadata.from_stage ?? metadata.fromStageId);
  const toStage = getStageName(stageMap, metadata.to_stage_id ?? metadata.to_stage ?? metadata.toStageId);
  if (fromStage || toStage) {
    lines.push(`단계: ${fromStage || "시작"} → ${toStage || "미정"}`);
  }

  const artifactTitle = typeof metadata.artifact_title === "string" ? metadata.artifact_title : typeof metadata.title === "string" ? metadata.title : null;
  const artifactType = typeof metadata.artifact_type === "string" ? metadata.artifact_type : typeof metadata.type === "string" ? metadata.type : null;
  if (artifactTitle || artifactType) {
    lines.push(`산출물: ${artifactTitle || "제목 없음"}${artifactType ? ` (${artifactType})` : ""}`);
  }

  const approvalStage = getStageName(stageMap, metadata.stage_id ?? metadata.target_stage_id ?? metadata.approval_stage_id);
  if (approvalStage && !lines.some((line) => line.includes("단계:"))) {
    lines.push(`대상 단계: ${approvalStage}`);
  }

  const note = typeof metadata.note === "string" ? metadata.note : null;
  if (note) {
    lines.push(`메모: ${note}`);
  }

  if (lines.length === 0 && log.target_type) {
    lines.push(`대상: ${log.target_type}${log.target_id ? ` #${log.target_id}` : ""}`);
  }

  return lines;
}

export function ActivityTimeline({ activityLogs, stages }: Props) {
  const stageMap = useMemo(() => new Map(stages.map((stage) => [stage.id, stage.name])), [stages]);
  const logs = useMemo(() => {
    return [...(activityLogs ?? [])].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  }, [activityLogs]);

  return (
    <section className="ax-activity">
      <div className="ax-activity-header">
        <h3 className="ax-section-title">활동 타임라인</h3>
        <span className="ax-activity-count">{logs.length}건</span>
      </div>
      {logs.length === 0 ? (
        <div className="ax-activity-empty">표시할 활동 로그가 없습니다.</div>
      ) : (
        <div className="ax-activity-list">
          {logs.map((log) => {
            const summaryLines = buildSummary(log, stageMap);
            return (
              <article key={log.id} className="ax-activity-item">
                <div className="ax-activity-item-top">
                  <div className="ax-activity-main">
                    <span className={`ax-activity-kind-badge ax-activity-kind-${log.actor_kind}`}>
                      {ACTOR_KIND_LABELS[log.actor_kind]}
                    </span>
                    <strong className="ax-activity-actor">{log.actor_label || "알 수 없음"}</strong>
                    <span className="ax-activity-action">{formatActionLabel(log.action)}</span>
                  </div>
                  <time className="ax-activity-time">{formatDateTime(log.created_at)}</time>
                </div>
                {summaryLines.length > 0 && (
                  <div className="ax-activity-summary">
                    {summaryLines.map((line, index) => (
                      <p key={`${log.id}-${index}`}>{line}</p>
                    ))}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
