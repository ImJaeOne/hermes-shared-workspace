"""Pydantic request schemas for the Hermes AX dashboard API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StageInput(BaseModel):
    name: str
    slug: str = ""


class CreateTemplateBody(BaseModel):
    agent_type_id: str
    name: str
    stages: list[StageInput] = Field(..., min_length=1)


class CreateWorkflowBody(BaseModel):
    template_id: str
    title: str
    priority: int = 0
    assignee: str = ""
    metadata_json: str = "{}"


class UpdateWorkflowBody(BaseModel):
    title: str | None = None
    status: str | None = None
    priority: int | None = None
    assignee: str | None = None
    metadata_json: str | None = None


class TransitionBody(BaseModel):
    to_stage_id: str
    triggered_by: str = "user"
    note: str = ""


class CreateArtifactBody(BaseModel):
    workflow_id: str
    stage_id: str
    artifact_type: str
    title: str
    content: str = ""
    content_type: str = "text/markdown"
    status: str = "draft"


class UpdateArtifactBody(BaseModel):
    title: str | None = None
    content: str | None = None
    content_type: str | None = None
    status: str | None = None


class CreateCommentBody(BaseModel):
    author: str = ""
    body: str


class UpdateCommentBody(BaseModel):
    body: str


class CreateSkillBody(BaseModel):
    name: str
    description: str = ""
    content: str = ""
    agent_type_id: str | None = None


class UpdateSkillBody(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    agent_type_id: str | None = None


class UpdateDefinitionBody(BaseModel):
    content: str


class CreateSkillBindingBody(BaseModel):
    skill_id: str
    stage_id: str | None = None
    execution_order: int = 0


class UpdateStageBody(BaseModel):
    transition_mode: str | None = None
    approval_roles: str | None = None


class DecideApprovalBody(BaseModel):
    status: str  # 'approved' or 'rejected'
    decided_by: str = ""
    note: str = ""


class LoginBody(BaseModel):
    username: str
    password: str
