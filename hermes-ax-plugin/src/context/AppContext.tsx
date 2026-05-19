import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { AgentType, AgentTypeId, ApprovalRequest, Skill } from "../types/models";
import type { BoardResponse, StatsResponse } from "../types/api";
import { getAgents, getApprovals, getBoard, getSkills, getStats, usePolling } from "../api/client";

export type ViewMode = "kanban" | "pipeline" | "skills" | "definition";

interface AppState {
  username: string;
  setUsername: (name: string) => void;
  selectedAgentId: AgentTypeId;
  setSelectedAgentId: (id: AgentTypeId) => void;
  selectedTemplateId: string | null;
  setSelectedTemplateId: (id: string | null) => void;
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  selectedWorkflowId: string | null;
  setSelectedWorkflowId: (id: string | null) => void;
  agents: AgentType[];
  boardData: BoardResponse | null;
  stats: StatsResponse | null;
  skills: Skill[];
  pendingApprovals: ApprovalRequest[];
  loading: boolean;
  refreshBoard: () => void;
  refreshAll: () => void;
  refreshSkills: () => void;
  refreshApprovals: () => void;
}

const AppContext = createContext<AppState | null>(null);

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [username, setUsernameState] = useState(() => localStorage.getItem("ax_username") || "");
  const [selectedAgentId, setSelectedAgentIdRaw] = useState<AgentTypeId>("sales");
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("kanban");
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);

  const setSelectedAgentId = useCallback((id: AgentTypeId) => {
    setSelectedAgentIdRaw(id);
    setSelectedTemplateId(null);
  }, []);
  const [agents, setAgents] = useState<AgentType[]>([]);
  const [boardData, setBoardData] = useState<BoardResponse | null>(null);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalRequest[]>([]);
  const [loading, setLoading] = useState(true);

  const { needsRefresh, clearRefresh } = usePolling(7000);

  const setUsername = useCallback((name: string) => {
    localStorage.setItem("ax_username", name);
    setUsernameState(name);
  }, []);

  const loadAgents = useCallback(async () => {
    try {
      const data = await getAgents();
      setAgents(data);
    } catch (e) {
      console.error("Failed to load agents:", e);
    }
  }, []);

  const refreshBoard = useCallback(async () => {
    try {
      const [board, st] = await Promise.all([getBoard(selectedAgentId, selectedTemplateId ?? undefined), getStats()]);
      setBoardData(board);
      setStats(st);
    } catch (e) {
      console.error("Failed to load board:", e);
    }
  }, [selectedAgentId, selectedTemplateId]);

  const refreshSkills = useCallback(async () => {
    try {
      const data = await getSkills(selectedAgentId);
      setSkills(data);
    } catch (e) {
      console.error("Failed to load skills:", e);
    }
  }, [selectedAgentId]);

  const refreshApprovals = useCallback(async () => {
    try {
      const data = await getApprovals();
      setPendingApprovals(data);
    } catch (e) {
      console.error("Failed to load approvals:", e);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    await loadAgents();
    await Promise.all([refreshBoard(), refreshSkills(), refreshApprovals()]);
    setLoading(false);
  }, [loadAgents, refreshBoard, refreshSkills, refreshApprovals]);

  // Initial load
  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  // Refresh on agent or template change
  useEffect(() => {
    refreshBoard();
  }, [selectedAgentId, selectedTemplateId, refreshBoard]);

  // Polling refresh
  useEffect(() => {
    if (needsRefresh) {
      refreshBoard();
      refreshApprovals();
      clearRefresh();
    }
  }, [needsRefresh, clearRefresh, refreshBoard, refreshApprovals]);

  return (
    <AppContext.Provider
      value={{
        username,
        setUsername,
        selectedAgentId,
        setSelectedAgentId,
        selectedTemplateId,
        setSelectedTemplateId,
        viewMode,
        setViewMode,
        selectedWorkflowId,
        setSelectedWorkflowId,
        agents,
        boardData,
        stats,
        skills,
        pendingApprovals,
        loading,
        refreshBoard,
        refreshAll,
        refreshSkills,
        refreshApprovals,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}
