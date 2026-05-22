import React, { useState } from "react";
import { useApp } from "../../context/AppContext";
import type { AgentTypeId } from "../../types/models";
import type { ViewMode } from "../../context/AppContext";
import { UserPanel } from "./UserPanel";
import { CreateWorkflowDialog } from "../shared/CreateWorkflowDialog";
import { deleteTemplate, getApiErrorMessage } from "../../api/client";

const AGENT_TABS: { id: AgentTypeId; label: string; icon: string }[] = [
  { id: "planning", label: "기획", icon: "ClipboardList" },
  { id: "design", label: "디자인", icon: "PenTool" },
];

const AGENT_COLORS: Record<AgentTypeId, string> = {
  planning: "#3b82f6",
  design: "#ec4899",
};

export function Header() {
  const {
    selectedAgentId, setSelectedAgentId,
    selectedTemplateId, setSelectedTemplateId,
    stats, viewMode, setViewMode, setSelectedWorkflowId,
    pendingApprovals, authenticated, authLoading, currentUserLabel, agents, refreshAll,
  } = useApp();
  const [showCreate, setShowCreate] = useState(false);
  const [showUser, setShowUser] = useState(false);

  const agent = agents.find((a) => a.id === selectedAgentId);
  const templates = agent?.templates ?? [];

  const handleTabClick = (id: AgentTypeId) => {
    setSelectedAgentId(id);
    setViewMode("kanban");
    setSelectedWorkflowId(null);
  };

  const handleTemplateClick = (templateId: string) => {
    setSelectedTemplateId(templateId);
    setViewMode("kanban");
    setSelectedWorkflowId(null);
  };

  const handleDeleteTemplate = async (e: React.MouseEvent, templateId: string, templateName: string) => {
    e.stopPropagation();
    if (!confirm(`"${templateName}" 워크플로우 템플릿을 삭제하시겠습니까?\n관련된 모든 완료된 티켓도 함께 삭제됩니다.`)) return;
    try {
      await deleteTemplate(templateId);
      setSelectedTemplateId(null);
      await refreshAll();
    } catch (err) {
      alert(getApiErrorMessage(err, "삭제 실패"));
    }
  };

  const handleNavClick = (mode: ViewMode) => {
    setViewMode(mode);
    setSelectedWorkflowId(null);
  };

  const handleBackToBoard = () => {
    setViewMode("kanban");
    setSelectedWorkflowId(null);
  };

  const agentStats = stats?.by_agent?.[selectedAgentId];
  const isSubView = viewMode !== "kanban";
  const showTemplateCreate = selectedAgentId !== "planning";
  const userButtonLabel = authLoading ? "확인 중..." : authenticated ? currentUserLabel : "세션 확인";

  return (
    <header className="ax-header">
      <div className="ax-header-top">
        <div className="ax-header-title">
          <h1>AX Dashboard</h1>
          {isSubView && (
            <button className="ax-btn ax-btn-ghost ax-btn-sm" onClick={handleBackToBoard}>
              {"← 보드로 돌아가기"}
            </button>
          )}
        </div>
        <div className="ax-header-actions">
          {viewMode === "kanban" && (
            <>
              <button className="ax-btn ax-btn-ghost ax-btn-sm" onClick={() => handleNavClick("skills")}>
                스킬 관리
              </button>
              <button className="ax-btn ax-btn-ghost ax-btn-sm" onClick={() => handleNavClick("definition")}>
                {selectedAgentId === "planning" ? "기획 단계 설정" : "워크플로우 정의"}
              </button>
            </>
          )}
          {pendingApprovals.length > 0 && (
            <span className="ax-approval-badge" title={`${pendingApprovals.length}건 승인 대기`}>
              {pendingApprovals.length}
            </span>
          )}
          {showTemplateCreate && (
            <button className="ax-btn ax-btn-primary ax-btn-sm" onClick={() => setShowCreate(true)}>
              {"+ 새 워크플로우"}
            </button>
          )}
          <button className="ax-btn ax-btn-ghost ax-btn-sm" onClick={() => setShowUser(true)}>
            {userButtonLabel}
          </button>
        </div>
      </div>

      {viewMode === "kanban" && (
        <>
          <nav className="ax-tabs">
            {AGENT_TABS.map((tab) => (
              <button
                key={tab.id}
                className={`ax-tab ${selectedAgentId === tab.id ? "ax-tab-active" : ""}`}
                style={selectedAgentId === tab.id ? { borderBottomColor: AGENT_COLORS[tab.id] } : undefined}
                onClick={() => handleTabClick(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </nav>

          {selectedAgentId !== "planning" && templates.length > 1 && (
            <nav className="ax-template-tabs">
              {templates.map((tmpl) => {
                const isActive = selectedTemplateId
                  ? selectedTemplateId === tmpl.id
                  : templates[0]?.id === tmpl.id;
                return (
                  <span key={tmpl.id} className={`ax-tab ax-tab-sm ax-tab-with-action ${isActive ? "ax-tab-active" : ""}`}>
                    <button className="ax-tab-label" onClick={() => handleTemplateClick(tmpl.id)}>
                      {tmpl.name}
                    </button>
                    <button
                      className="ax-tab-delete"
                      onClick={(e) => handleDeleteTemplate(e, tmpl.id, tmpl.name)}
                      title="템플릿 삭제"
                    >
                      ×
                    </button>
                  </span>
                );
              })}
            </nav>
          )}

          <div className="ax-stats-bar">
            <span className="ax-stat">
              <span className="ax-stat-dot ax-stat-dot-active" /> {"활성: "}{agentStats?.active ?? stats?.active ?? 0}
            </span>
            <span className="ax-stat">
              <span className="ax-stat-dot ax-stat-dot-completed" /> {"완료: "}{agentStats?.completed ?? stats?.completed ?? 0}
            </span>
            <span className="ax-stat">
              <span className="ax-stat-dot ax-stat-dot-failed" /> {"실패: "}{agentStats?.failed ?? stats?.failed ?? 0}
            </span>
            <span className="ax-stat">
              {"오늘 산출물: "}{stats?.artifacts_today ?? 0}
            </span>
            {(stats?.pending_approvals ?? 0) > 0 && (
              <span className="ax-stat">
                <span className="ax-stat-dot" style={{ background: "#f59e0b" }} /> {"승인 대기: "}{stats?.pending_approvals}
              </span>
            )}
          </div>
        </>
      )}

      {showCreate && showTemplateCreate && <CreateWorkflowDialog onClose={() => setShowCreate(false)} />}
      {showUser && <UserPanel onClose={() => setShowUser(false)} />}
    </header>
  );
}
