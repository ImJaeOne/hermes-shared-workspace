import React from "react";
import { AppProvider, useApp } from "../context/AppContext";
import { Header } from "./layout/Header";
import { KanbanBoard } from "./kanban/KanbanBoard";
import { PlanningProjectBoard } from "./planning/PlanningProjectBoard";
import { PipelineView } from "./pipeline/PipelineView";
import { SkillListView } from "./skills/SkillListView";
import { DefinitionEditorView } from "./definition/DefinitionEditorView";

function AppInner() {
  const { viewMode, loading, selectedAgentId } = useApp();

  if (loading) {
    return (
      <div className="ax-loading">
        <div className="ax-spinner" />
        <span>AX 대시보드 로딩 중...</span>
      </div>
    );
  }

  const renderView = () => {
    switch (viewMode) {
      case "pipeline":
        return <PipelineView />;
      case "skills":
        return <SkillListView />;
      case "definition":
        return <DefinitionEditorView />;
      default:
        if (selectedAgentId === "planning") {
          return <PlanningProjectBoard />;
        }
        return <KanbanBoard />;
    }
  };

  return (
    <div className="ax-root">
      <Header />
      <main className="ax-main">
        {renderView()}
      </main>
    </div>
  );
}

export function App() {
  return (
    <AppProvider>
      <AppInner />
    </AppProvider>
  );
}
