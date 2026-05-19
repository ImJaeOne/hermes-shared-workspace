import React, { useCallback, useEffect, useState } from "react";
import type { Artifact } from "../../types/models";
import type { ArtifactDetailResponse } from "../../types/api";
import { getArtifact, updateArtifact } from "../../api/client";
import { StatusBadge } from "../shared/StatusBadge";
import { ArtifactViewer } from "./ArtifactViewer";
import { CommentSection } from "../comments/CommentSection";

const TYPE_ICONS: Record<string, string> = {
  email: "Mail",
  contact_info: "User",
  meeting_notes: "FileText",
  proposal: "FileText",
  contract: "FileCheck",
  report: "BarChart",
  brief: "Clipboard",
  content_draft: "Edit",
  analytics: "LineChart",
  ticket: "Ticket",
  log: "Terminal",
  resolution_note: "CheckCircle",
};

function formatSize(bytes: number): string {
  if (bytes === 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface Props {
  artifact: Artifact;
  onRefresh: () => void;
}

export function ArtifactCard({ artifact, onRefresh }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<ArtifactDetailResponse | null>(null);

  const loadDetail = useCallback(async () => {
    try {
      const data = await getArtifact(artifact.id);
      setDetail(data);
    } catch (e) {
      console.error("Failed to load artifact:", e);
    }
  }, [artifact.id]);

  useEffect(() => {
    if (expanded && !detail) {
      loadDetail();
    }
  }, [expanded, detail, loadDetail]);

  const handleStatusToggle = async () => {
    const next = artifact.status === "draft" ? "final" : "draft";
    try {
      await updateArtifact(artifact.id, { status: next });
      onRefresh();
    } catch (e) {
      console.error("Failed to update artifact:", e);
    }
  };

  const iconName = TYPE_ICONS[artifact.artifact_type] || "File";
  const sizeStr = formatSize(artifact.file_size || 0);
  const mimeShort = artifact.mime_type && artifact.mime_type !== artifact.content_type
    ? artifact.mime_type.split("/")[1]
    : "";

  return (
    <div className="ax-artifact-card">
      <div className="ax-artifact-card-header" onClick={() => setExpanded(!expanded)}>
        <div className="ax-artifact-card-info">
          <span className="ax-artifact-icon">{iconName}</span>
          <span className="ax-artifact-type">{artifact.artifact_type}</span>
          <span className="ax-artifact-title">{artifact.title}</span>
          {(sizeStr || mimeShort) && (
            <span className="ax-artifact-file-meta">
              {mimeShort && <span>{mimeShort}</span>}
              {sizeStr && <span>{sizeStr}</span>}
            </span>
          )}
        </div>
        <div className="ax-artifact-card-actions">
          <StatusBadge status={artifact.status} />
          <button
            className="ax-btn ax-btn-ghost ax-btn-xs"
            onClick={(e) => { e.stopPropagation(); handleStatusToggle(); }}
          >
            {artifact.status === "draft" ? "최종 확정" : "초안으로"}
          </button>
          <span className="ax-artifact-chevron">{expanded ? "\u25B2" : "\u25BC"}</span>
        </div>
      </div>

      {expanded && (
        <div className="ax-artifact-card-body">
          <ArtifactViewer artifact={detail || artifact} />
          <CommentSection
            artifactId={artifact.id}
            comments={detail?.comments || []}
            onRefresh={loadDetail}
          />
        </div>
      )}
    </div>
  );
}
