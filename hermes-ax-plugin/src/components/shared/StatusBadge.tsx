import React from "react";

const STATUS_STYLES: Record<string, { bg: string; color: string; label?: string }> = {
  active: { bg: "rgba(255,189,56,0.1)", color: "var(--color-warning, #ffbd38)", label: "활성" },
  completed: { bg: "rgba(74,222,128,0.1)", color: "var(--color-success, #4ade80)", label: "완료" },
  failed: { bg: "rgba(251,44,54,0.1)", color: "var(--color-destructive, #fb2c36)", label: "실패" },
  paused: { bg: "rgba(255,189,56,0.06)", color: "var(--color-muted-foreground)", label: "일시정지" },
  cancelled: { bg: "var(--color-muted)", color: "var(--color-muted-foreground)", label: "취소" },
  pending_approval: { bg: "rgba(245,158,11,0.15)", color: "#f59e0b", label: "승인 대기" },
  draft: { bg: "rgba(139,92,246,0.1)", color: "#a78bfa", label: "초안" },
  final: { bg: "rgba(74,222,128,0.1)", color: "var(--color-success, #4ade80)", label: "최종" },
  archived: { bg: "var(--color-muted)", color: "var(--color-muted-foreground)", label: "보관" },
};

const PRIORITY_LABELS: Record<number, { label: string; color: string }> = {
  0: { label: "보통", color: "var(--color-muted-foreground)" },
  1: { label: "높음", color: "var(--color-warning, #ffbd38)" },
  2: { label: "긴급", color: "var(--color-destructive, #fb2c36)" },
};

interface StatusBadgeProps {
  status: string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const style = STATUS_STYLES[status] || { bg: "#f3f4f6", color: "#6b7280" };
  return (
    <span
      className="ax-badge"
      style={{ backgroundColor: style.bg, color: style.color }}
    >
      {style.label || status}
    </span>
  );
}

interface PriorityBadgeProps {
  priority: number;
}

export function PriorityBadge({ priority }: PriorityBadgeProps) {
  if (priority === 0) return null;
  const info = PRIORITY_LABELS[priority] || PRIORITY_LABELS[0];
  return (
    <span className="ax-badge ax-badge-priority" style={{ color: info.color, borderColor: info.color }}>
      {info.label}
    </span>
  );
}
