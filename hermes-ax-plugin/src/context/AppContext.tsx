import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { AgentType, AgentTypeId, ApprovalRequest, Skill } from "../types/models";
import type { AuthUser, BoardResponse, LoginRequest, StatsResponse } from "../types/api";
import {
  clearSessionToken,
  getAgents,
  getApprovals,
  getAuthSession,
  getBoard,
  getSkills,
  getStats,
  login as loginRequest,
  logout as logoutRequest,
  setSessionToken,
  usePolling,
} from "../api/client";

export type ViewMode = "kanban" | "pipeline" | "skills" | "definition";

interface AppState {
  authUser: AuthUser | null;
  authExpiresAt: string | null;
  authenticated: boolean;
  authLoading: boolean;
  currentUserLabel: string;
  login: (payload: LoginRequest) => Promise<void>;
  logout: () => Promise<void>;
  refreshAuthSession: () => Promise<void>;
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
  refreshBoard: () => Promise<void>;
  refreshAll: () => Promise<void>;
  refreshSkills: () => Promise<void>;
  refreshApprovals: () => Promise<void>;
}

const AppContext = createContext<AppState | null>(null);

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authExpiresAt, setAuthExpiresAt] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
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

  const refreshAuthSession = useCallback(async () => {
    setAuthLoading(true);
    try {
      const session = await getAuthSession();
      if (session.authenticated) {
        setAuthUser(session.user);
        setAuthExpiresAt(session.expires_at);
      } else {
        clearSessionToken();
        setAuthUser(null);
        setAuthExpiresAt(null);
      }
    } catch (e) {
      console.error("Failed to load auth session:", e);
      clearSessionToken();
      setAuthUser(null);
      setAuthExpiresAt(null);
    } finally {
      setAuthLoading(false);
    }
  }, []);

  const login = useCallback(async (payload: LoginRequest) => {
    setAuthLoading(true);
    try {
      const response = await loginRequest(payload);
      setSessionToken(response.token);
      setAuthUser(response.user);
      setAuthExpiresAt(response.expires_at);
    } finally {
      setAuthLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    setAuthLoading(true);
    try {
      await logoutRequest();
      clearSessionToken();
      setAuthUser(null);
      setAuthExpiresAt(null);
    } finally {
      setAuthLoading(false);
    }
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
    await Promise.all([loadAgents(), refreshBoard(), refreshSkills(), refreshApprovals(), refreshAuthSession()]);
    setLoading(false);
  }, [loadAgents, refreshBoard, refreshSkills, refreshApprovals, refreshAuthSession]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    refreshBoard();
  }, [selectedAgentId, selectedTemplateId, refreshBoard]);

  useEffect(() => {
    if (needsRefresh) {
      void refreshBoard();
      void refreshApprovals();
      clearRefresh();
    }
  }, [needsRefresh, clearRefresh, refreshBoard, refreshApprovals]);

  const currentUserLabel = useMemo(() => {
    if (!authUser) return "";
    return authUser.display_name?.trim() || authUser.username;
  }, [authUser]);

  return (
    <AppContext.Provider
      value={{
        authUser,
        authExpiresAt,
        authenticated: Boolean(authUser),
        authLoading,
        currentUserLabel,
        login,
        logout,
        refreshAuthSession,
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
