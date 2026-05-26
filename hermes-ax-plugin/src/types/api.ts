import type {
  ActivityLog,
  AgentType,
  ApprovalRequest,
  Artifact,
  AXEvent,
  Comment,
  Skill,
  SlackMaterialCollectionState,
  SlackWorkflowSourceFile,
  StageDefinition,
  StageTransition,
  WorkflowDefinition,
  WorkflowInstance,
  WorkflowSkillBinding,
} from "./models";

// --- Auth ---
export interface AuthUser {
  id: string;
  username: string;
  display_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AuthSessionResponse {
  authenticated: boolean;
  user: AuthUser | null;
  expires_at: string | null;
}

// --- Agent ---
export type AgentsResponse = AgentType[];

export interface AgentDetailResponse extends AgentType {
  stages: StageDefinition[];
}

// --- Board ---
export interface BoardColumn {
  stage: StageDefinition;
  workflows: WorkflowInstance[];
}

export interface BoardResponse {
  agent_type_id: string;
  template_id: string | null;
  columns: BoardColumn[];
  completed: WorkflowInstance[];
}

// --- Template ---
export interface StageInput {
  name: string;
  slug?: string;
}

export interface CreateTemplateRequest {
  agent_type_id: string;
  name: string;
  stages: StageInput[];
}

// --- Stats ---
export interface StatsResponse {
  active: number;
  completed: number;
  failed: number;
  pending_approvals: number;
  artifacts_today: number;
  by_agent: Record<string, { active: number; completed: number; failed: number }>;
}

// --- Workflow ---
export interface CreateWorkflowRequest {
  template_id: string;
  title: string;
  priority?: number;
  assignee?: string;
  metadata_json?: string;
}

export interface WorkflowDetailResponse extends WorkflowInstance {
  stages: (StageDefinition & { is_completed: boolean; is_current: boolean })[];
  artifacts: Artifact[];
  transitions: StageTransition[];
  activity_logs?: ActivityLog[];
  pending_approval?: ApprovalRequest | null;
  source_files?: SlackWorkflowSourceFile[];
  material_collection_state?: SlackMaterialCollectionState | null;
}

export interface UpdateWorkflowRequest {
  title?: string;
  status?: string;
  priority?: number;
  assignee?: string;
  metadata_json?: string;
}

export interface TransitionRequest {
  to_stage_id: string;
  triggered_by?: string;
  note?: string;
}

export interface TransitionResponse {
  ok: boolean;
  current_stage_id?: string;
  pending_approval?: boolean;
  approval_id?: string;
}

// --- Artifact ---
export interface CreateArtifactRequest {
  workflow_id: string;
  stage_id: string;
  artifact_type: string;
  title: string;
  content: string;
  content_type?: string;
  status?: string;
}

export interface ArtifactDetailResponse extends Artifact {
  comments: Comment[];
}

export interface UpdateArtifactRequest {
  title?: string;
  content?: string;
  content_type?: string;
  status?: string;
}

export interface ArtifactUploadResponse {
  id: string;
  file_path: string;
  file_size: number;
  mime_type: string;
}

// --- Comment ---
export interface CreateCommentRequest {
  author?: string;
  body: string;
}

export interface UpdateCommentRequest {
  body: string;
}

// --- Events ---
export interface EventsResponse {
  events: AXEvent[];
  cursor: number;
}

// --- Skills ---
export interface CreateSkillRequest {
  name: string;
  description?: string;
  content?: string;
  agent_type_id?: string | null;
}

export interface UpdateSkillRequest {
  name?: string;
  description?: string;
  content?: string;
  agent_type_id?: string | null;
}

export type SkillsResponse = Skill[];

// --- Workflow Definition ---
export interface UpdateDefinitionRequest {
  content: string;
}

// --- Skill Binding ---
export interface CreateSkillBindingRequest {
  skill_id: string;
  stage_id?: string | null;
  execution_order?: number;
}

// --- Stage HITL ---
export interface UpdateStageRequest {
  transition_mode?: string;
  approval_roles?: string;
}

// --- Approval ---
export interface DecideApprovalRequest {
  status: "approved" | "rejected";
  decided_by?: string;
  note?: string;
}

export type ApprovalsResponse = ApprovalRequest[];
