import React from "react";
import type { Artifact } from "../../types/models";
import { ArtifactCard } from "./ArtifactCard";
import { EmptyState } from "../shared/EmptyState";

interface Props {
  artifacts: Artifact[];
  onRefresh: () => void;
}

export function ArtifactList({ artifacts, onRefresh }: Props) {
  if (artifacts.length === 0) {
    return <EmptyState message="이 단계에 산출물이 아직 없습니다." />;
  }

  return (
    <div className="ax-artifact-list">
      {artifacts.map((art) => (
        <ArtifactCard key={art.id} artifact={art} onRefresh={onRefresh} />
      ))}
    </div>
  );
}
