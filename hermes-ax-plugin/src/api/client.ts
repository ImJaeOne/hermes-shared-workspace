import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AgentsResponse,
  ApprovalsResponse,
  ArtifactDetailResponse,
  ArtifactUploadResponse,
  AuthSessionResponse,
  BoardResponse,
  CreateArtifactRequest,
  LoginRequest,
  LoginResponse,
  CreateCommentRequest,
  CreateSkillBindingRequest,
  CreateSkillRequest,
  CreateTemplateRequest,
  CreateWorkflowRequest,
  DecideApprovalRequest,
  EventsResponse,
  SkillsResponse,
  StatsResponse,
  TransitionRequest,
  TransitionResponse,
  UpdateArtifactRequest,
  UpdateCommentRequest,
  UpdateDefinitionRequest,
  UpdateSkillRequest,
  UpdateStageRequest,
  UpdateWorkflowRequest,
  WorkflowDetailResponse,
} from "../types/api";
import type { Skill, WorkflowDefinition, WorkflowSkillBinding } from "../types/models";

const API_BASE = "/api/plugins/hermes-ax";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function getSessionToken(): string {
  return (window as any).__HERMES_SESSION_TOKEN__ || "";
}

async function parseErrorDetail(res: Response): Promise<string> {
  const text = await res.text().catch(() => res.statusText);
  return text || res.statusText || "요청을 처리하지 못했습니다.";
}

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getSessionToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { "X-Hermes-Session-Token": token } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorDetail(res));
  }
  return res.json();
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export function isUnauthorizedError(error: unknown): boolean {
  return isApiError(error) && error.status === 401;
}

export function getApiErrorMessage(error: unknown, fallback: string = "요청을 처리하지 못했습니다."): string {
  if (isApiError(error)) {
    if (error.status === 401) {
      return "로그인이 필요합니다.";
    }
    return error.detail || fallback;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

// --- Auth ---
export const login = (body: LoginRequest) =>
  fetchJSON<LoginResponse>("/auth/login", { method: "POST", body: JSON.stringify(body) });

export const getAuthSession = () => fetchJSON<AuthSessionResponse>("/auth/session");

export const logout = () => fetchJSON<{ ok: boolean }>("/auth/logout", { method: "POST" });

// --- Agent ---
export const getAgents = () => fetchJSON<AgentsResponse>("/agents");
export const getAgent = (id: string) => fetchJSON<AgentsResponse[number]>(`/agents/${id}`);

// --- Board ---
export const getBoard = (agentId: string, templateId?: string) => {
  const params = templateId ? `?template_id=${templateId}` : "";
  return fetchJSON<BoardResponse>(`/board/${agentId}${params}`);
};
export const getStats = () => fetchJSON<StatsResponse>("/stats");

// --- Template ---
export const createTemplate = (body: CreateTemplateRequest) =>
  fetchJSON<{ id: string }>("/templates", { method: "POST", body: JSON.stringify(body) });

export const deleteTemplate = (id: string) =>
  fetchJSON<{ ok: boolean }>(`/templates/${id}`, { method: "DELETE" });

// --- Workflow ---
export const createWorkflow = (body: CreateWorkflowRequest) =>
  fetchJSON<{ id: string }>("/workflows", { method: "POST", body: JSON.stringify(body) });

export const getWorkflow = (id: string) => fetchJSON<WorkflowDetailResponse>(`/workflows/${id}`);

export const deleteWorkflow = (id: string) =>
  fetchJSON<{ ok: boolean }>(`/workflows/${id}`, { method: "DELETE" });

export const updateWorkflow = (id: string, body: UpdateWorkflowRequest) =>
  fetchJSON<{ ok: boolean }>(`/workflows/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export const transitionWorkflow = (id: string, body: TransitionRequest) =>
  fetchJSON<TransitionResponse>(`/workflows/${id}/transition`, { method: "POST", body: JSON.stringify(body) });

// --- Artifact ---
export const createArtifact = (body: CreateArtifactRequest) =>
  fetchJSON<{ id: string }>("/artifacts", { method: "POST", body: JSON.stringify(body) });

export const getArtifact = (id: string) => fetchJSON<ArtifactDetailResponse>(`/artifacts/${id}`);

export const updateArtifact = (id: string, body: UpdateArtifactRequest) =>
  fetchJSON<{ ok: boolean }>(`/artifacts/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export const getArtifactFileUrl = (id: string) => `${API_BASE}/artifacts/${id}/file`;

export async function uploadArtifact(formData: FormData): Promise<ArtifactUploadResponse> {
  const token = getSessionToken();
  const res = await fetch(`${API_BASE}/artifacts/upload`, {
    method: "POST",
    credentials: "include",
    headers: {
      ...(token ? { "X-Hermes-Session-Token": token } : {}),
    },
    body: formData,
  });
  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorDetail(res));
  }
  return res.json();
}

// --- Comment ---
export const createComment = (artifactId: string, body: CreateCommentRequest) =>
  fetchJSON<{ id: number }>(`/artifacts/${artifactId}/comments`, { method: "POST", body: JSON.stringify(body) });

export const updateComment = (commentId: number, body: UpdateCommentRequest) =>
  fetchJSON<{ ok: boolean }>(`/comments/${commentId}`, { method: "PATCH", body: JSON.stringify(body) });

export const deleteComment = (commentId: number) =>
  fetchJSON<{ ok: boolean }>(`/comments/${commentId}`, { method: "DELETE" });

// --- Skills ---
export const getSkills = (agentTypeId?: string) =>
  fetchJSON<SkillsResponse>(agentTypeId ? `/skills?agent_type_id=${agentTypeId}` : "/skills");

export const createSkill = (body: CreateSkillRequest) =>
  fetchJSON<{ id: string }>("/skills", { method: "POST", body: JSON.stringify(body) });

export const getSkill = (id: string) => fetchJSON<Skill>(`/skills/${id}`);

export const updateSkill = (id: string, body: UpdateSkillRequest) =>
  fetchJSON<{ ok: boolean }>(`/skills/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export const deleteSkill = (id: string) =>
  fetchJSON<{ ok: boolean }>(`/skills/${id}`, { method: "DELETE" });

// --- Workflow Definitions ---
export const getDefinition = (templateId: string) =>
  fetchJSON<WorkflowDefinition>(`/templates/${templateId}/definition`);

export const updateDefinition = (templateId: string, body: UpdateDefinitionRequest) =>
  fetchJSON<{ ok: boolean }>(`/templates/${templateId}/definition`, { method: "PUT", body: JSON.stringify(body) });

// --- Skill Bindings ---
export const getSkillBindings = (templateId: string) =>
  fetchJSON<WorkflowSkillBinding[]>(`/templates/${templateId}/skills`);

export const createSkillBinding = (templateId: string, body: CreateSkillBindingRequest) =>
  fetchJSON<{ id: number }>(`/templates/${templateId}/skills`, { method: "POST", body: JSON.stringify(body) });

export const deleteSkillBinding = (templateId: string, bindingId: number) =>
  fetchJSON<{ ok: boolean }>(`/templates/${templateId}/skills/${bindingId}`, { method: "DELETE" });

// --- Stage HITL ---
export const updateStage = (stageId: string, body: UpdateStageRequest) =>
  fetchJSON<{ ok: boolean }>(`/stages/${stageId}`, { method: "PATCH", body: JSON.stringify(body) });

// --- Approvals ---
export const getApprovals = (workflowId?: string) =>
  fetchJSON<ApprovalsResponse>(workflowId ? `/approvals?workflow_id=${workflowId}` : "/approvals");

export const decideApproval = (approvalId: string, body: DecideApprovalRequest) =>
  fetchJSON<{ ok: boolean; status: string }>(`/approvals/${approvalId}/decide`, { method: "POST", body: JSON.stringify(body) });

// --- Events ---
export const getEvents = (since: number, limit = 200) =>
  fetchJSON<EventsResponse>(`/events?since=${since}&limit=${limit}`);

// --- Polling Hook ---
export function usePolling(intervalMs: number = 7000) {
  const cursorRef = useRef(0);
  const [needsRefresh, setNeedsRefresh] = useState(false);

  useEffect(() => {
    const poll = async () => {
      try {
        const { events, cursor } = await getEvents(cursorRef.current);
        if (events.length > 0) {
          cursorRef.current = cursor;
          setNeedsRefresh(true);
        }
      } catch {
        // Silently ignore polling errors
      }
    };

    const id = setInterval(poll, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  const clearRefresh = useCallback(() => setNeedsRefresh(false), []);

  return { needsRefresh, clearRefresh };
}
