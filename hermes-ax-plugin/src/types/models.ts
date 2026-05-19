export type AgentTypeId = "sales" | "marketing" | "support";

export type WorkflowStatus =
  | "active"
  | "completed"
  | "failed"
  | "paused"
  | "cancelled"
  | "pending_approval";

export type ArtifactStatus = "draft" | "final" | "archived";

export type ContentType =
  | "text/plain"
  | "text/markdown"
  | "application/json";

export type TransitionMode = "auto" | "approval_required";

export type EventKind =
  | "workflow_created"
  | "workflow_updated"
  | "stage_changed"
  | "artifact_added"
  | "artifact_updated"
  | "comment_added"
  | "comment_updated"
  | "comment_deleted"
  | "approval_requested"
  | "approval_approved"
  | "approval_rejected"
  | "skill_created"
  | "skill_updated"
  | "skill_deleted"
  | "definition_updated"
  | "binding_created"
  | "binding_deleted"
  | "stage_updated"
  | "template_created"
  | "template_deleted"
  | "workflow_deleted";

export interface AgentType {
  id: AgentTypeId;
  name: string;
  description: string;
  icon: string;
  color: string;
  config_json: string;
  created_at: string;
  templates: WorkflowTemplate[];
}

export interface WorkflowTemplate {
  id: string;
  agent_type_id: AgentTypeId;
  name: string;
  is_active: number;
  version: number;
  created_at: string;
  stages: StageDefinition[];
}

export interface StageDefinition {
  id: string;
  template_id: string;
  name: string;
  slug: string;
  stage_order: number;
  expected_artifacts: string;
  trigger_conditions: string;
  transition_mode: TransitionMode;
  approval_roles: string;
  created_at: string;
}

export interface WorkflowInstance {
  id: string;
  template_id: string;
  agent_type_id: AgentTypeId;
  title: string;
  current_stage_id: string;
  status: WorkflowStatus;
  priority: number;
  assignee: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
  artifact_count?: number;
  current_stage_name?: string;
  current_stage_order?: number;
}

export interface Artifact {
  id: string;
  workflow_id: string;
  stage_id: string;
  artifact_type: string;
  title: string;
  content: string;
  content_type: ContentType;
  status: ArtifactStatus;
  file_path: string;
  file_size: number;
  mime_type: string;
  created_at: string;
  updated_at: string;
  comments?: Comment[];
}

export interface Comment {
  id: number;
  artifact_id: string;
  author: string;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface StageTransition {
  id: number;
  workflow_id: string;
  from_stage_id: string | null;
  to_stage_id: string;
  triggered_by: string;
  note: string;
  created_at: string;
}

export interface AXEvent {
  id: number;
  kind: EventKind;
  workflow_id: string;
  artifact_id: string | null;
  payload: string;
  created_at: string;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  content: string;
  agent_type_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowDefinition {
  id: string | null;
  template_id: string;
  content: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface WorkflowSkillBinding {
  id: number;
  template_id: string;
  skill_id: string;
  stage_id: string | null;
  execution_order: number;
  skill_name?: string;
  skill_description?: string;
}

export interface ApprovalRequest {
  id: string;
  workflow_id: string;
  stage_id: string;
  status: "pending" | "approved" | "rejected";
  requested_at: string;
  decided_by: string;
  decided_at: string | null;
  note: string;
  workflow_title?: string;
  stage_name?: string;
}
