"""Hermes AX Plugin API — FastAPI backend for Agent eXecution Dashboard."""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

try:
    from .activity import _actor_label, _record_activity, _record_user_activity
    from .auth import (
        AUTH_SESSION_TTL_SECONDS,
        AX_SESSION_COOKIE,
        AX_SESSION_COOKIE_SECURE_ENV,
        get_bootstrap_admin_config,
        hash_password,
        hash_session_token,
        normalize_username,
        parse_timestamp,
        serialize_user,
        verify_password,
        env_flag,
    )
    from .db_schema import SCHEMA_SQL, _run_migrations
    from .schemas import (
        CreateArtifactBody,
        CreateCommentBody,
        CreateSkillBindingBody,
        CreateSkillBody,
        CreateTemplateBody,
        CreateWorkflowBody,
        DecideApprovalBody,
        LoginBody,
        TransitionBody,
        UpdateArtifactBody,
        UpdateCommentBody,
        UpdateDefinitionBody,
        UpdateSkillBody,
        UpdateStageBody,
        UpdateWorkflowBody,
    )
except ImportError:
    from activity import _actor_label, _record_activity, _record_user_activity
    from auth import (
        AUTH_SESSION_TTL_SECONDS,
        AX_SESSION_COOKIE,
        AX_SESSION_COOKIE_SECURE_ENV,
        env_flag,
        get_bootstrap_admin_config,
        hash_password,
        hash_session_token,
        normalize_username,
        parse_timestamp,
        serialize_user,
        verify_password,
    )
    from db_schema import SCHEMA_SQL, _run_migrations
    from schemas import (
        CreateArtifactBody,
        CreateCommentBody,
        CreateSkillBindingBody,
        CreateSkillBody,
        CreateTemplateBody,
        CreateWorkflowBody,
        DecideApprovalBody,
        LoginBody,
        TransitionBody,
        UpdateArtifactBody,
        UpdateCommentBody,
        UpdateDefinitionBody,
        UpdateSkillBody,
        UpdateStageBody,
        UpdateWorkflowBody,
    )

router = APIRouter()

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
PLUGIN_DATA_DIR = HERMES_HOME / "plugins" / "hermes-ax-plugin"
DB_DIR = PLUGIN_DATA_DIR
DB_PATH = DB_DIR / "ax.db"
ARTIFACTS_DIR = DB_DIR / "artifacts"

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"



def _require_authenticated_user(conn: sqlite3.Connection, request: Request) -> dict[str, Any]:
    token = _get_request_session_token(request)
    auth = _get_authenticated_session(conn, token)
    if not auth:
        raise HTTPException(401, "Authentication required")
    return auth["user"]


def _create_auth_session(conn: sqlite3.Connection, user_id: str) -> dict[str, str]:
    now_dt = datetime.now(timezone.utc)
    expires_dt = now_dt + timedelta(seconds=AUTH_SESSION_TTL_SECONDS)
    session_token = secrets.token_urlsafe(32)
    session_id = _uuid("axs_")
    now = now_dt.isoformat()
    expires_at = expires_dt.isoformat()
    conn.execute(
        """INSERT INTO auth_sessions
           (id, user_id, session_token_hash, expires_at, created_at, last_seen_at)
           VALUES (?,?,?,?,?,?)""",
        (session_id, user_id, hash_session_token(session_token), expires_at, now, now),
    )
    return {
        "id": session_id,
        "token": session_token,
        "expires_at": expires_at,
        "created_at": now,
        "last_seen_at": now,
    }


def _get_request_session_token(request: Request) -> str:
    header_token = request.headers.get("X-Hermes-Session-Token", "").strip()
    if header_token:
        return header_token
    return request.cookies.get(AX_SESSION_COOKIE, "").strip()


def _get_authenticated_session(conn: sqlite3.Connection, token: str) -> dict[str, Any] | None:
    if not token:
        return None

    row = conn.execute(
        """SELECT
               s.id,
               s.user_id,
               s.expires_at,
               s.created_at,
               s.last_seen_at,
               u.username,
               u.display_name,
               u.role,
               u.is_active,
               u.created_at AS user_created_at,
               u.updated_at AS user_updated_at
           FROM auth_sessions s
           JOIN users u ON u.id = s.user_id
           WHERE s.session_token_hash=?""",
        (hash_session_token(token),),
    ).fetchone()
    if not row:
        return None

    if not row["is_active"]:
        conn.execute("DELETE FROM auth_sessions WHERE id=?", (row["id"],))
        return None

    if parse_timestamp(row["expires_at"]) <= datetime.now(timezone.utc):
        conn.execute("DELETE FROM auth_sessions WHERE id=?", (row["id"],))
        return None

    last_seen_at = _now()
    conn.execute("UPDATE auth_sessions SET last_seen_at=? WHERE id=?", (last_seen_at, row["id"]))
    return {
        "session": {
            "id": row["id"],
            "user_id": row["user_id"],
            "expires_at": row["expires_at"],
            "created_at": row["created_at"],
            "last_seen_at": last_seen_at,
        },
        "user": {
            "id": row["user_id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "is_active": bool(row["is_active"]),
            "created_at": row["user_created_at"],
            "updated_at": row["user_updated_at"],
        },
    }


def _upsert_bootstrap_admin(conn: sqlite3.Connection):
    config = get_bootstrap_admin_config()
    if not config:
        return

    now = _now()
    password_hash = hash_password(config["password"])
    existing = conn.execute(
        "SELECT id FROM users WHERE username=?",
        (config["username"],),
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE users
               SET display_name=?, password_hash=?, role='admin', is_active=1, updated_at=?
               WHERE id=?""",
            (config["display_name"], password_hash, now, existing["id"]),
        )
        return

    conn.execute(
        """INSERT INTO users
           (id, username, display_name, password_hash, role, is_active, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            _uuid("usr_"),
            config["username"],
            config["display_name"],
            password_hash,
            "admin",
            1,
            now,
            now,
        ),
    )


@contextmanager
def get_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows: list) -> list[dict]:
    return [dict(r) for r in rows]

def _emit_event(conn: sqlite3.Connection, kind: str, workflow_id: str | None = None, artifact_id: str | None = None, payload: dict | None = None):
    conn.execute(
        "INSERT INTO ax_events (kind, workflow_id, artifact_id, payload, created_at) VALUES (?,?,?,?,?)",
        (kind, workflow_id, artifact_id, json.dumps(payload or {}), _now()),
    )


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

SEED_DATA: dict[str, Any] = {
    "agents": [
        {
            "id": "sales",
            "name": "Sales Agent",
            "description": "영업 파이프라인 — 리드 유입부터 계약 완료까지",
            "icon": "TrendingUp",
            "color": "#f59e0b",
        },
        {
            "id": "marketing",
            "name": "Marketing Agent",
            "description": "캠페인 파이프라인 — 기획부터 분석까지",
            "icon": "Megaphone",
            "color": "#8b5cf6",
        },
        {
            "id": "support",
            "name": "Support Agent",
            "description": "티켓 해결 파이프라인 — 접수부터 후속 조치까지",
            "icon": "HeadphonesIcon",
            "color": "#10b981",
        },
    ],
    "templates": [
        {"id": "sales_pipeline_v1", "agent_type_id": "sales", "name": "Sales Pipeline v1"},
        {"id": "mktg_blog", "agent_type_id": "marketing", "name": "블로그"},
        {"id": "mktg_cardnews", "agent_type_id": "marketing", "name": "카드뉴스"},
        {"id": "support_pipeline_v1", "agent_type_id": "support", "name": "Support Pipeline v1"},
    ],
    "stages": [
        # Sales
        {"id": "s_lead", "template_id": "sales_pipeline_v1", "name": "Lead In", "slug": "lead-in", "stage_order": 0, "expected_artifacts": '["contact_info"]'},
        {"id": "s_qual", "template_id": "sales_pipeline_v1", "name": "Qualification", "slug": "qualification", "stage_order": 1, "expected_artifacts": '["email","meeting_notes"]'},
        {"id": "s_prop", "template_id": "sales_pipeline_v1", "name": "Proposal", "slug": "proposal", "stage_order": 2, "expected_artifacts": '["proposal","email"]', "transition_mode": "approval_required", "approval_roles": '["manager"]'},
        {"id": "s_nego", "template_id": "sales_pipeline_v1", "name": "Negotiation", "slug": "negotiation", "stage_order": 3, "expected_artifacts": '["contract","email"]'},
        {"id": "s_close", "template_id": "sales_pipeline_v1", "name": "Close", "slug": "close", "stage_order": 4, "expected_artifacts": '["contract","report"]', "transition_mode": "approval_required", "approval_roles": '["manager","director"]'},
        # Marketing — 블로그
        {"id": "mb_topic", "template_id": "mktg_blog", "name": "주제 선정", "slug": "topic", "stage_order": 0, "expected_artifacts": '["brief"]'},
        {"id": "mb_draft", "template_id": "mktg_blog", "name": "초안 작성", "slug": "draft", "stage_order": 1, "expected_artifacts": '["content_draft"]'},
        {"id": "mb_review", "template_id": "mktg_blog", "name": "리뷰", "slug": "review", "stage_order": 2, "expected_artifacts": '["content_draft"]', "transition_mode": "approval_required", "approval_roles": '["manager"]'},
        {"id": "mb_publish", "template_id": "mktg_blog", "name": "발행", "slug": "publish", "stage_order": 3, "expected_artifacts": '["report"]'},
        # Marketing — 카드뉴스
        {"id": "mc_plan", "template_id": "mktg_cardnews", "name": "기획", "slug": "plan", "stage_order": 0, "expected_artifacts": '["brief"]'},
        {"id": "mc_design", "template_id": "mktg_cardnews", "name": "디자인", "slug": "design", "stage_order": 1, "expected_artifacts": '["content_draft"]'},
        {"id": "mc_copy", "template_id": "mktg_cardnews", "name": "카피 작성", "slug": "copy", "stage_order": 2, "expected_artifacts": '["content_draft"]'},
        {"id": "mc_approve", "template_id": "mktg_cardnews", "name": "승인", "slug": "approve", "stage_order": 3, "expected_artifacts": '["report"]', "transition_mode": "approval_required", "approval_roles": '["manager"]'},
        {"id": "mc_dist", "template_id": "mktg_cardnews", "name": "배포", "slug": "distribute", "stage_order": 4, "expected_artifacts": '["report"]'},
        # Support
        {"id": "t_created", "template_id": "support_pipeline_v1", "name": "Ticket Created", "slug": "created", "stage_order": 0, "expected_artifacts": '["ticket"]'},
        {"id": "t_triage", "template_id": "support_pipeline_v1", "name": "Triage", "slug": "triage", "stage_order": 1, "expected_artifacts": '["ticket","log"]'},
        {"id": "t_invest", "template_id": "support_pipeline_v1", "name": "Investigation", "slug": "investigation", "stage_order": 2, "expected_artifacts": '["log","meeting_notes"]'},
        {"id": "t_resolve", "template_id": "support_pipeline_v1", "name": "Resolution", "slug": "resolution", "stage_order": 3, "expected_artifacts": '["resolution_note"]'},
        {"id": "t_follow", "template_id": "support_pipeline_v1", "name": "Follow-up", "slug": "followup", "stage_order": 4, "expected_artifacts": '["email","report"]'},
    ],
    "skills": [
        {
            "id": "skill_001",
            "name": "초기 연락 이메일 작성",
            "description": "리드에게 보내는 첫 번째 연락 이메일을 작성합니다.",
            "content": "# 초기 연락 이메일 작성\n\n## 목적\n리드에게 첫 인상을 남기는 전문적인 이메일을 작성합니다.\n\n## 입력\n- 리드 이름\n- 회사명\n- 관심 제품/서비스\n- 연락 경위 (컨퍼런스, 웹사이트 등)\n\n## 출력 형식\n```\n제목: [제목]\n\n본문:\n[이메일 본문]\n```\n\n## 톤앤매너\n- 전문적이면서도 친근한 톤\n- 가치 제안을 명확히\n- CTA 포함",
            "agent_type_id": "sales",
        },
        {
            "id": "skill_002",
            "name": "미팅 노트 정리",
            "description": "미팅 내용을 구조화된 노트로 정리합니다.",
            "content": "# 미팅 노트 정리\n\n## 목적\n미팅 내용을 체계적으로 정리하여 팀과 공유합니다.\n\n## 구조\n1. 미팅 정보 (일시, 참석자)\n2. 핵심 논의 사항\n3. 의사결정 내용\n4. 액션 아이템 (담당자, 기한)\n5. 다음 미팅 일정\n\n## 작성 규칙\n- 객관적 사실 중심\n- 액션 아이템은 체크리스트로\n- 기한 명시 필수",
            "agent_type_id": None,
        },
        {
            "id": "skill_003",
            "name": "캠페인 브리프 작성",
            "description": "마케팅 캠페인 브리프를 작성합니다.",
            "content": "# 캠페인 브리프 작성\n\n## 필수 항목\n- 캠페인 목표 (SMART 기준)\n- 타겟 오디언스 정의\n- 핵심 메시지\n- 채널 전략\n- 예산 배분\n- 일정 (마일스톤)\n- 성공 지표 (KPI)\n\n## 작성 팁\n- 한 페이지 요약 포함\n- 경쟁사 분석 첨부\n- 과거 캠페인 성과 참조",
            "agent_type_id": "marketing",
        },
        {
            "id": "skill_004",
            "name": "티켓 분류 및 우선순위 결정",
            "description": "지원 티켓을 분류하고 우선순위를 결정합니다.",
            "content": "# 티켓 분류 가이드\n\n## 심각도 레벨\n- **Critical**: 서비스 전체 중단, 데이터 손실 위험\n- **High**: 주요 기능 장애, 다수 사용자 영향\n- **Medium**: 부분 기능 장애, 우회 방법 존재\n- **Low**: UI 이슈, 개선 요청\n\n## 카테고리\n- billing: 결제/구독 관련\n- auth: 인증/권한 관련\n- performance: 성능 관련\n- feature: 기능 요청\n- bug: 버그 리포트\n\n## 응답 SLA\n- Critical: 1시간 내\n- High: 4시간 내\n- Medium: 24시간 내\n- Low: 72시간 내",
            "agent_type_id": "support",
        },
        {
            "id": "skill_005",
            "name": "제안서 작성",
            "description": "고객 맞춤 솔루션 제안서를 작성합니다.",
            "content": "# 솔루션 제안서 작성\n\n## 구조\n1. 요약 (Executive Summary)\n2. 고객 현황 및 과제\n3. 제안 솔루션\n4. 기대 효과 (ROI)\n5. 구현 일정\n6. 가격 구성\n7. 팀 소개\n8. 부록 (기술 스펙)\n\n## 작성 규칙\n- 고객 관점에서 가치 중심 서술\n- 수치와 사례로 뒷받침\n- 경쟁 우위 강조\n- 명확한 다음 단계 제시",
            "agent_type_id": "sales",
        },
    ],
}


def _seed_if_empty(conn: sqlite3.Connection):
    row = conn.execute("SELECT count(*) as c FROM agent_types").fetchone()
    if row["c"] > 0:
        return

    now = _now()
    for a in SEED_DATA["agents"]:
        conn.execute(
            "INSERT INTO agent_types (id, name, description, icon, color, config_json, created_at) VALUES (?,?,?,?,?,?,?)",
            (a["id"], a["name"], a["description"], a["icon"], a["color"], "{}", now),
        )
    for t in SEED_DATA["templates"]:
        conn.execute(
            "INSERT INTO workflow_templates (id, agent_type_id, name, is_active, version, created_at) VALUES (?,?,?,1,1,?)",
            (t["id"], t["agent_type_id"], t["name"], now),
        )
    for s in SEED_DATA["stages"]:
        transition_mode = s.get("transition_mode", "auto")
        approval_roles = s.get("approval_roles", "[]")
        conn.execute(
            "INSERT INTO stage_definitions (id, template_id, name, slug, stage_order, expected_artifacts, trigger_conditions, transition_mode, approval_roles, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (s["id"], s["template_id"], s["name"], s["slug"], s["stage_order"], s["expected_artifacts"], "{}", transition_mode, approval_roles, now),
        )

    # Seed skills
    for sk in SEED_DATA.get("skills", []):
        conn.execute(
            "INSERT INTO skills (id, name, description, content, agent_type_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (sk["id"], sk["name"], sk["description"], sk["content"], sk["agent_type_id"], now, now),
        )

    # --- Sample workflows ---
    _seed_sample_data(conn, now)


def _seed_sample_data(conn: sqlite3.Connection, now: str):
    """Insert sample workflows, artifacts, and comments for demo."""

    def _ins_wf(wid, tmpl, agent, title, stage, status, priority, assignee):
        conn.execute(
            "INSERT INTO workflow_instances (id,template_id,agent_type_id,title,current_stage_id,status,priority,assignee,metadata_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (wid, tmpl, agent, title, stage, status, priority, assignee, "{}", now, now),
        )
        conn.execute(
            "INSERT INTO stage_transitions (workflow_id,from_stage_id,to_stage_id,triggered_by,note,created_at) VALUES (?,?,?,?,?,?)",
            (wid, None, stage, "system", "워크플로우 생성", now),
        )
        _emit_event(conn, "workflow_created", wid)

    def _ins_art(aid, wid, stage, atype, title, content, ctype="text/markdown", status="draft"):
        conn.execute(
            "INSERT INTO artifacts (id,workflow_id,stage_id,artifact_type,title,content,content_type,status,file_path,file_size,mime_type,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, wid, stage, atype, title, content, ctype, status, "", 0, ctype, now, now),
        )
        _emit_event(conn, "artifact_added", wid, aid)

    def _ins_comment(aid, author, body):
        conn.execute(
            "INSERT INTO comments (artifact_id,author,body,created_at,updated_at) VALUES (?,?,?,?,?)",
            (aid, author, body, now, now),
        )

    # ===================== SALES =====================
    # 1) Acme Corp - Proposal 단계 (진행중, 높음)
    _ins_wf("wi_sales_001", "sales_pipeline_v1", "sales", "Acme Corp 엔터프라이즈 딜", "s_prop", "active", 1, "김영업")
    _ins_art("art_s001", "wi_sales_001", "s_lead", "contact_info", "Acme Corp 담당자 정보",
             json.dumps({"name": "John Smith", "company": "Acme Corp", "email": "john@acme.com", "phone": "+82-10-1234-5678", "source": "컨퍼런스"}, ensure_ascii=False),
             "application/json", "final")
    _ins_comment("art_s001", "김영업", "컨퍼런스에서 만난 핵심 의사결정자입니다. CTO 직급.")
    _ins_art("art_s002", "wi_sales_001", "s_qual", "email", "초기 미팅 요청 이메일",
             "## 미팅 요청\n\n안녕하세요 John,\n\n지난 컨퍼런스에서 말씀드렸던 솔루션 데모를 진행하고 싶습니다.\n\n다음 주 화요일 오후 2시 가능하실까요?\n\n감사합니다.", "text/markdown", "final")
    _ins_art("art_s003", "wi_sales_001", "s_qual", "meeting_notes", "1차 미팅 노트",
             "## 1차 미팅 (2025-05-08)\n\n**참석자**: John Smith (CTO), Sarah Lee (VP Eng)\n\n### 핵심 사항\n- 현재 레거시 시스템 교체 검토 중\n- 예산 약 5억원 확보됨\n- Q3 내 도입 희망\n\n### 액션 아이템\n- [ ] 기술 스펙 문서 전달\n- [ ] 가격 제안서 준비\n- [ ] 2차 기술 미팅 일정 조율", "text/markdown", "final")
    _ins_comment("art_s003", "박팀장", "예산 규모가 괜찮네요. 프리미엄 패키지로 제안 준비해주세요.")
    _ins_comment("art_s003", "김영업", "네, 내일까지 제안서 초안 올리겠습니다.")
    _ins_art("art_s004", "wi_sales_001", "s_prop", "proposal", "Acme Corp 제안서 초안",
             "## 솔루션 제안서 — Acme Corp\n\n### 1. 제안 범위\n- 엔터프라이즈 플랜 (사용자 500명)\n- 커스텀 통합 개발 (3개월)\n- 전담 기술 지원 (12개월)\n\n### 2. 가격\n| 항목 | 금액 |\n|------|------|\n| 라이선스 (연간) | 3억원 |\n| 통합 개발 | 1.5억원 |\n| 기술 지원 | 5천만원 |\n| **합계** | **5억원** |\n\n### 3. 일정\n- 계약 체결: 6월\n- 개발 착수: 7월\n- 1차 배포: 9월", "text/markdown", "draft")
    _ins_comment("art_s004", "박팀장", "통합 개발 금액을 좀 더 세분화해서 보여주면 좋겠어요.")

    # 2) Beta Inc - Lead In 단계 (신규)
    _ins_wf("wi_sales_002", "sales_pipeline_v1", "sales", "Beta Inc 스타트업 패키지", "s_lead", "active", 0, "이대리")
    _ins_art("art_s010", "wi_sales_002", "s_lead", "contact_info", "Beta Inc 연락처",
             json.dumps({"name": "최민수", "company": "Beta Inc", "email": "ms.choi@betainc.kr", "phone": "+82-10-9876-5432", "source": "웹사이트 문의"}, ensure_ascii=False),
             "application/json", "final")

    # 3) Gamma - Negotiation 단계 (긴급)
    _ins_wf("wi_sales_003", "sales_pipeline_v1", "sales", "Gamma Ltd 글로벌 계약", "s_nego", "active", 2, "김영업")
    _ins_art("art_s020", "wi_sales_003", "s_nego", "contract", "계약서 초안 v2",
             "## 계약서 초안\n\n**계약 당사자**: Hermes Inc ↔ Gamma Ltd\n\n### 주요 조건\n- 계약 기간: 24개월\n- 총 계약 금액: $500,000\n- 지불 조건: 분기별 균등 분할\n- SLA: 99.9% 가용성 보장\n\n### 특이 사항\n- 아시아 태평양 지역 독점 조항 요청 중\n- 법무팀 검토 필요", "text/markdown", "draft")
    _ins_comment("art_s020", "김영업", "법무팀에 독점 조항 관련 검토 요청했습니다.")
    _ins_comment("art_s020", "박팀장", "독점 조항은 리스크가 있어요. 지역 제한 범위를 좁히는 방향으로 협의하세요.")

    # 4) 완료된 딜
    _ins_wf("wi_sales_004", "sales_pipeline_v1", "sales", "Delta Corp 연간 계약", "s_close", "completed", 0, "이대리")

    # ===================== MARKETING — 블로그 =====================
    # 1) Q3 블로그 포스트 — 초안 작성 단계
    _ins_wf("wi_mktg_001", "mktg_blog", "marketing", "Q3 제품 런칭 블로그 포스트", "mb_draft", "active", 1, "정마케터")
    _ins_art("art_m001", "wi_mktg_001", "mb_topic", "brief", "Q3 블로그 주제 기획",
             "## Q3 블로그 주제\n\n### 주제\nAI 워크플로우 자동화로 팀 생산성 높이기\n\n### 타겟 독자\n- B2B SaaS 의사결정자 (CTO, VP Eng)\n- IT/테크 산업 종사자\n\n### 핵심 메시지\n- 복잡한 워크플로우를 AI로 간소화\n- 실제 고객 사례로 효과 입증", "text/markdown", "final")
    _ins_comment("art_m001", "정마케터", "CMO 승인 완료. 초안 작성 착수합니다.")
    _ins_art("art_m002", "wi_mktg_001", "mb_draft", "content_draft", "블로그 초안",
             "## 혁신을 가속화하는 차세대 플랫폼\n\n### 헤드라인 A\n\"복잡한 워크플로우, 이제 AI가 알아서 처리합니다\"\n\n### 헤드라인 B\n\"팀 생산성 300% 향상 — 실제 고객 사례로 검증\"\n\n### 본문\n- 5분 만에 설정, 즉시 효과\n- 50+ 통합 지원\n- 엔터프라이즈급 보안\n\n### CTA\n\"무료 체험 시작하기\" / \"데모 신청\"", "text/markdown", "draft")
    _ins_comment("art_m002", "이디자이너", "헤드라인 B가 더 임팩트 있는 것 같아요. 숫자가 눈에 들어옵니다.")

    # 2) 발행 완료된 블로그
    _ins_wf("wi_mktg_003", "mktg_blog", "marketing", "Q2 브랜드 인지도 블로그", "mb_publish", "completed", 0, "정마케터")
    _ins_art("art_m020", "wi_mktg_003", "mb_publish", "report", "Q2 블로그 성과 보고서",
             "## Q2 블로그 성과 요약\n\n### 주요 지표\n- 조회수: 85,000\n- 전환율: 2.8%\n- 공유: 420건\n\n### 인사이트\n- LinkedIn 공유가 가장 높은 유입 채널\n- 웨비나 참석자의 리드 전환율이 일반 대비 3배", "text/markdown", "final")
    _ins_comment("art_m020", "CMO", "좋은 결과네요. Q3에는 블로그 발행 빈도를 늘려보겠습니다.")

    # ===================== MARKETING — 카드뉴스 =====================
    # 1) 5월 카드뉴스 — 카피 작성 단계
    _ins_wf("wi_mktg_002", "mktg_cardnews", "marketing", "5월 제품 업데이트 카드뉴스", "mc_copy", "active", 0, "정마케터")
    _ins_art("art_m010", "wi_mktg_002", "mc_plan", "brief", "5월 카드뉴스 기획",
             "## 5월 카드뉴스 기획\n\n### 주제\nHermes 5월 주요 업데이트 안내\n\n### 내용 요소\n1. AI 워크플로우 자동화 기능 출시\n2. 대시보드 플러그인 시스템 오픈\n3. 고객 사례: Beta Inc의 업무 효율 200% 향상기", "text/markdown", "final")
    _ins_art("art_m011", "wi_mktg_002", "mc_copy", "content_draft", "5월 카드뉴스 카피",
             "## Hermes 5월 업데이트\n\n**슬라이드 1**: AI 워크플로우 자동화 출시!\n**슬라이드 2**: 대시보드 플러그인으로 확장하세요\n**슬라이드 3**: Beta Inc 성공 사례\n**슬라이드 4**: 지금 무료 체험 시작하기", "text/markdown", "draft")

    # ===================== SUPPORT =====================
    # 1) 결제 오류 - Investigation 단계 (긴급)
    _ins_wf("wi_sup_001", "support_pipeline_v1", "support", "[긴급] 결제 시스템 오류 #4521", "t_invest", "active", 2, "최엔지니어")
    _ins_art("art_t001", "wi_sup_001", "t_created", "ticket", "결제 오류 티켓",
             json.dumps({"customer": "MegaCorp", "issue": "결제 처리 시 500 에러 발생", "severity": "critical", "category": "billing", "reported_at": "2025-05-10T09:30:00Z"}, ensure_ascii=False),
             "application/json", "final")
    _ins_art("art_t002", "wi_sup_001", "t_triage", "log", "초기 분류 로그",
             "2025-05-10 09:35 - 티켓 접수. 결제 시스템 500 에러.\n2025-05-10 09:40 - 심각도: Critical 분류. 다수 고객 영향 확인.\n2025-05-10 09:45 - 결제 게이트웨이 로그 확인 시작.\n2025-05-10 10:00 - PG사 측 API 응답 지연 확인 (평균 30초 → 타임아웃)", "text/plain", "final")
    _ins_art("art_t003", "wi_sup_001", "t_invest", "log", "조사 로그",
             "2025-05-10 10:30 - PG사 API 엔드포인트 상태 확인\n2025-05-10 11:00 - PG사 측 서버 증설 작업 진행 중 확인\n2025-05-10 11:30 - 임시 조치: 타임아웃 값 60초로 상향\n2025-05-10 12:00 - 재시도 로직 추가 배포 검토 중", "text/plain", "draft")
    _ins_comment("art_t003", "최엔지니어", "PG사 측 이슈입니다. 임시로 타임아웃 늘렸고, 재시도 로직 추가 배포 예정입니다.")
    _ins_comment("art_t003", "박팀장", "고객사에 현재 상황 안내 이메일 보내주세요.")

    # 2) 로그인 이슈 - Triage 단계
    _ins_wf("wi_sup_002", "support_pipeline_v1", "support", "SSO 로그인 실패 #4523", "t_triage", "active", 1, "한주니어")
    _ins_art("art_t010", "wi_sup_002", "t_created", "ticket", "SSO 로그인 티켓",
             json.dumps({"customer": "TechStart", "issue": "Google SSO 로그인 시 리다이렉트 무한루프", "severity": "high", "category": "auth", "reported_at": "2025-05-10T14:00:00Z"}, ensure_ascii=False),
             "application/json", "final")

    # 3) 해결된 티켓
    _ins_wf("wi_sup_003", "support_pipeline_v1", "support", "데이터 내보내기 오류 #4510", "t_follow", "completed", 0, "최엔지니어")
    _ins_art("art_t020", "wi_sup_003", "t_resolve", "resolution_note", "데이터 내보내기 수정 완료",
             "## 근본 원인\nCSV 내보내기 시 한글 인코딩(UTF-8 BOM) 누락으로 Excel에서 깨짐 발생\n\n## 적용 수정\n- CSV 생성 시 UTF-8 BOM 헤더 추가\n- 인코딩 옵션 선택 UI 추가 (UTF-8 / EUC-KR)\n\n## 검증\n- QA 테스트 통과\n- 고객 확인 완료", "text/markdown", "final")
    _ins_comment("art_t020", "최엔지니어", "v2.3.1 핫픽스로 배포 완료했습니다.")

    # 4) 새 티켓
    _ins_wf("wi_sup_004", "support_pipeline_v1", "support", "API 속도 저하 문의 #4525", "t_created", "active", 0, "")


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
        _run_migrations(conn)
        _seed_if_empty(conn)
        _upsert_bootstrap_admin(conn)


# Run on import
init_db()

# ---------------------------------------------------------------------------
# API: Auth
# ---------------------------------------------------------------------------

@router.post("/auth/login")
def login(body: LoginBody, response: Response):
    username = normalize_username(body.username)
    password = body.password.strip()
    if not username or not password:
        raise HTTPException(400, "Username and password are required")

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not user or not user["is_active"] or not verify_password(password, user["password_hash"]):
            raise HTTPException(401, "Invalid username or password")

        session = _create_auth_session(conn, user["id"])
        _record_user_activity(
            conn,
            user=user,
            action="auth.login",
            target_type="session",
            target_id=session["id"],
            metadata={"username": user["username"]},
        )

    response.set_cookie(
        key=AX_SESSION_COOKIE,
        value=session["token"],
        httponly=True,
        samesite="lax",
        secure=env_flag(AX_SESSION_COOKIE_SECURE_ENV, default=False),
        max_age=AUTH_SESSION_TTL_SECONDS,
        path="/",
    )
    return {
        "ok": True,
        "token": session["token"],
        "expires_at": session["expires_at"],
        "user": serialize_user(user),
    }


@router.get("/auth/session")
def get_auth_session(request: Request, response: Response):
    token = _get_request_session_token(request)
    with get_db() as conn:
        auth = _get_authenticated_session(conn, token)

    if not auth:
        response.delete_cookie(key=AX_SESSION_COOKIE, path="/")
        return {"authenticated": False, "user": None, "expires_at": None}

    return {
        "authenticated": True,
        "user": auth["user"],
        "expires_at": auth["session"]["expires_at"],
    }


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    token = _get_request_session_token(request)
    with get_db() as conn:
        auth = _get_authenticated_session(conn, token) if token else None
        if token:
            conn.execute(
                "DELETE FROM auth_sessions WHERE session_token_hash=?",
                (hash_session_token(token),),
            )
        if auth:
            _record_user_activity(
                conn,
                user=auth["user"],
                action="auth.logout",
                target_type="session",
                target_id=auth["session"]["id"],
                metadata={"username": auth["user"]["username"]},
            )

    response.delete_cookie(key=AX_SESSION_COOKIE, path="/")
    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Agents
# ---------------------------------------------------------------------------

@router.get("/agents")
def list_agents():
    with get_db() as conn:
        agents = rows_to_list(conn.execute("SELECT * FROM agent_types ORDER BY id").fetchall())
        for agent in agents:
            templates = rows_to_list(
                conn.execute("SELECT * FROM workflow_templates WHERE agent_type_id=? AND is_active=1", (agent["id"],)).fetchall()
            )
            for tmpl in templates:
                tmpl["stages"] = rows_to_list(
                    conn.execute("SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order", (tmpl["id"],)).fetchall()
                )
            agent["templates"] = templates
    return agents


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    with get_db() as conn:
        agent = row_to_dict(conn.execute("SELECT * FROM agent_types WHERE id=?", (agent_id,)).fetchone())
        if not agent:
            raise HTTPException(404, "Agent not found")
        templates = rows_to_list(
            conn.execute("SELECT * FROM workflow_templates WHERE agent_type_id=? AND is_active=1", (agent_id,)).fetchall()
        )
        stages = []
        for tmpl in templates:
            tmpl["stages"] = rows_to_list(
                conn.execute("SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order", (tmpl["id"],)).fetchall()
            )
            stages.extend(tmpl["stages"])
        agent["templates"] = templates
        agent["stages"] = stages
    return agent


# ---------------------------------------------------------------------------
# API: Templates
# ---------------------------------------------------------------------------

@router.post("/templates")
def create_template(body: CreateTemplateBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        agent = conn.execute("SELECT * FROM agent_types WHERE id=?", (body.agent_type_id,)).fetchone()
        if not agent:
            raise HTTPException(404, "Agent not found")

        now = _now()
        tmpl_id = _uuid("tmpl_")
        conn.execute(
            "INSERT INTO workflow_templates (id, agent_type_id, name, is_active, version, created_at) VALUES (?,?,?,1,1,?)",
            (tmpl_id, body.agent_type_id, body.name, now),
        )

        for i, stage in enumerate(body.stages):
            stage_id = _uuid("stg_")
            slug = stage.slug or stage.name.lower().replace(" ", "-")
            conn.execute(
                "INSERT INTO stage_definitions (id, template_id, name, slug, stage_order, expected_artifacts, trigger_conditions, transition_mode, approval_roles, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (stage_id, tmpl_id, stage.name, slug, i, "[]", "{}", "auto", "[]", now),
            )

        _emit_event(conn, "template_created", payload={"template_id": tmpl_id})
        _record_user_activity(
            conn,
            user=user,
            action="template.create",
            target_type="template",
            target_id=tmpl_id,
            metadata={"agent_type_id": body.agent_type_id, "stage_count": len(body.stages), "name": body.name},
        )

    return {"id": tmpl_id}


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        tmpl = conn.execute("SELECT * FROM workflow_templates WHERE id=?", (template_id,)).fetchone()
        if not tmpl:
            raise HTTPException(404, "Template not found")
        active_count = conn.execute(
            "SELECT count(*) as c FROM workflow_instances WHERE template_id=? AND status IN ('active','pending_approval')",
            (template_id,),
        ).fetchone()["c"]
        if active_count > 0:
            raise HTTPException(400, f"활성 워크플로우 {active_count}개가 있어 삭제할 수 없습니다. 먼저 워크플로우를 완료하거나 삭제하세요.")
        wf_ids = [r["id"] for r in conn.execute("SELECT id FROM workflow_instances WHERE template_id=?", (template_id,)).fetchall()]
        for wid in wf_ids:
            art_ids = [r["id"] for r in conn.execute("SELECT id FROM artifacts WHERE workflow_id=?", (wid,)).fetchall()]
            for aid in art_ids:
                conn.execute("DELETE FROM comments WHERE artifact_id=?", (aid,))
            conn.execute("DELETE FROM artifacts WHERE workflow_id=?", (wid,))
            conn.execute("DELETE FROM stage_transitions WHERE workflow_id=?", (wid,))
            conn.execute("DELETE FROM approval_requests WHERE workflow_id=?", (wid,))
        conn.execute("DELETE FROM workflow_instances WHERE template_id=?", (template_id,))
        conn.execute("DELETE FROM workflow_skill_bindings WHERE template_id=?", (template_id,))
        conn.execute("DELETE FROM workflow_definitions WHERE template_id=?", (template_id,))
        conn.execute("DELETE FROM stage_definitions WHERE template_id=?", (template_id,))
        conn.execute("DELETE FROM workflow_templates WHERE id=?", (template_id,))
        _emit_event(conn, "template_deleted", payload={"template_id": template_id})
        _record_user_activity(
            conn,
            user=user,
            action="template.delete",
            target_type="template",
            target_id=template_id,
            metadata={"name": tmpl["name"]},
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Board (Kanban)
# ---------------------------------------------------------------------------

@router.get("/board/{agent_id}")
def get_board(agent_id: str, template_id: str | None = Query(None)):
    with get_db() as conn:
        agent = conn.execute("SELECT * FROM agent_types WHERE id=?", (agent_id,)).fetchone()
        if not agent:
            raise HTTPException(404, "Agent not found")

        # Get template: specified or first active
        if template_id:
            tmpl = conn.execute(
                "SELECT * FROM workflow_templates WHERE id=? AND agent_type_id=? AND is_active=1", (template_id, agent_id)
            ).fetchone()
        else:
            tmpl = conn.execute(
                "SELECT * FROM workflow_templates WHERE agent_type_id=? AND is_active=1 ORDER BY created_at LIMIT 1", (agent_id,)
            ).fetchone()
        if not tmpl:
            return {"agent_type_id": agent_id, "template_id": None, "columns": [], "completed": []}

        stages = rows_to_list(
            conn.execute("SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order", (tmpl["id"],)).fetchall()
        )

        columns = []
        for stage in stages:
            workflows = rows_to_list(conn.execute(
                """SELECT wi.*, sd.name as current_stage_name, sd.stage_order as current_stage_order,
                          (SELECT count(*) FROM artifacts WHERE workflow_id=wi.id) as artifact_count
                   FROM workflow_instances wi
                   JOIN stage_definitions sd ON wi.current_stage_id = sd.id
                   WHERE wi.template_id=? AND wi.current_stage_id=? AND wi.status IN ('active','pending_approval')
                   ORDER BY wi.priority DESC, wi.updated_at DESC""",
                (tmpl["id"], stage["id"]),
            ).fetchall())
            columns.append({"stage": stage, "workflows": workflows})

        completed = rows_to_list(conn.execute(
            """SELECT wi.*, sd.name as current_stage_name, sd.stage_order as current_stage_order,
                      (SELECT count(*) FROM artifacts WHERE workflow_id=wi.id) as artifact_count
               FROM workflow_instances wi
               JOIN stage_definitions sd ON wi.current_stage_id = sd.id
               WHERE wi.template_id=? AND wi.status IN ('completed','failed','cancelled')
               ORDER BY wi.updated_at DESC LIMIT 20""",
            (tmpl["id"],),
        ).fetchall())

    return {"agent_type_id": agent_id, "template_id": tmpl["id"], "columns": columns, "completed": completed}


# ---------------------------------------------------------------------------
# API: Stats
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats():
    with get_db() as conn:
        active = conn.execute("SELECT count(*) as c FROM workflow_instances WHERE status='active'").fetchone()["c"]
        completed = conn.execute("SELECT count(*) as c FROM workflow_instances WHERE status='completed'").fetchone()["c"]
        failed = conn.execute("SELECT count(*) as c FROM workflow_instances WHERE status='failed'").fetchone()["c"]
        pending_approvals = conn.execute("SELECT count(*) as c FROM approval_requests WHERE status='pending'").fetchone()["c"]

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        artifacts_today = conn.execute(
            "SELECT count(*) as c FROM artifacts WHERE created_at >= ?", (today,)
        ).fetchone()["c"]

        by_agent: dict[str, dict] = {}
        for row in conn.execute(
            "SELECT agent_type_id, status, count(*) as c FROM workflow_instances GROUP BY agent_type_id, status"
        ).fetchall():
            aid = row["agent_type_id"]
            if aid not in by_agent:
                by_agent[aid] = {"active": 0, "completed": 0, "failed": 0}
            s = row["status"]
            if s in by_agent[aid]:
                by_agent[aid][s] = row["c"]

    return {
        "active": active,
        "completed": completed,
        "failed": failed,
        "pending_approvals": pending_approvals,
        "artifacts_today": artifacts_today,
        "by_agent": by_agent,
    }


# ---------------------------------------------------------------------------
# API: Workflows
# ---------------------------------------------------------------------------

@router.post("/workflows")
def create_workflow(body: CreateWorkflowBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        tmpl = row_to_dict(conn.execute("SELECT * FROM workflow_templates WHERE id=?", (body.template_id,)).fetchone())
        if not tmpl:
            raise HTTPException(404, "Template not found")

        first_stage = conn.execute(
            "SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order LIMIT 1", (body.template_id,)
        ).fetchone()
        if not first_stage:
            raise HTTPException(400, "Template has no stages")

        now = _now()
        wf_id = _uuid("wi_")
        conn.execute(
            """INSERT INTO workflow_instances
               (id, template_id, agent_type_id, title, current_stage_id, status, priority, assignee, metadata_json, created_at, updated_at, created_by_user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (wf_id, body.template_id, tmpl["agent_type_id"], body.title, first_stage["id"], "active", body.priority, body.assignee, body.metadata_json, now, now, user["id"]),
        )
        conn.execute(
            "INSERT INTO stage_transitions (workflow_id, from_stage_id, to_stage_id, triggered_by, note, created_at, triggered_by_user_id) VALUES (?,?,?,?,?,?,?)",
            (wf_id, None, first_stage["id"], user["display_name"], "Workflow created", now, user["id"]),
        )
        _emit_event(conn, "workflow_created", wf_id)
        _record_user_activity(
            conn,
            user=user,
            action="workflow.create",
            target_type="workflow",
            workflow_id=wf_id,
            target_id=wf_id,
            metadata={"template_id": body.template_id, "initial_stage_id": first_stage["id"]},
        )

    return {"id": wf_id, "status": "active", "current_stage_id": first_stage["id"]}


@router.get("/workflows/{wf_id}")
def get_workflow(wf_id: str):
    with get_db() as conn:
        wf = row_to_dict(conn.execute("SELECT * FROM workflow_instances WHERE id=?", (wf_id,)).fetchone())
        if not wf:
            raise HTTPException(404, "Workflow not found")

        all_stages = rows_to_list(conn.execute(
            "SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order", (wf["template_id"],)
        ).fetchall())

        current_order = 0
        for s in all_stages:
            if s["id"] == wf["current_stage_id"]:
                current_order = s["stage_order"]
                break

        stages_with_status = []
        for s in all_stages:
            s["is_completed"] = s["stage_order"] < current_order
            s["is_current"] = s["id"] == wf["current_stage_id"]
            stages_with_status.append(s)

        artifacts = rows_to_list(conn.execute(
            "SELECT * FROM artifacts WHERE workflow_id=? ORDER BY created_at", (wf_id,)
        ).fetchall())

        transitions = rows_to_list(conn.execute(
            "SELECT * FROM stage_transitions WHERE workflow_id=? ORDER BY created_at", (wf_id,)
        ).fetchall())

        pending_approval = row_to_dict(conn.execute(
            "SELECT * FROM approval_requests WHERE workflow_id=? AND status='pending' LIMIT 1", (wf_id,)
        ).fetchone())

        activity_logs = rows_to_list(conn.execute(
            "SELECT * FROM activity_logs WHERE workflow_id=? ORDER BY created_at DESC, id DESC LIMIT 100", (wf_id,)
        ).fetchall())

        wf["stages"] = stages_with_status
        wf["artifacts"] = artifacts
        wf["transitions"] = transitions
        wf["pending_approval"] = pending_approval
        wf["activity_logs"] = activity_logs

    return wf


@router.patch("/workflows/{wf_id}")
def update_workflow(wf_id: str, body: UpdateWorkflowBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (wf_id,)).fetchone()
        if not wf:
            raise HTTPException(404, "Workflow not found")

        updates = []
        params = []
        changed_fields: dict[str, Any] = {}
        for field in ("title", "status", "priority", "assignee", "metadata_json"):
            val = getattr(body, field, None)
            if val is not None:
                updates.append(f"{field}=?")
                params.append(val)
                changed_fields[field] = val

        if updates:
            updates.append("updated_at=?")
            params.append(_now())
            params.append(wf_id)
            conn.execute(f"UPDATE workflow_instances SET {','.join(updates)} WHERE id=?", params)
            _emit_event(conn, "workflow_updated", wf_id)
            _record_user_activity(
                conn,
                user=user,
                action="workflow.update",
                target_type="workflow",
                workflow_id=wf_id,
                target_id=wf_id,
                metadata={"changes": changed_fields},
            )

    return {"ok": True}


@router.delete("/workflows/{wf_id}")
def delete_workflow(wf_id: str, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (wf_id,)).fetchone()
        if not wf:
            raise HTTPException(404, "Workflow not found")
        art_ids = [r["id"] for r in conn.execute("SELECT id FROM artifacts WHERE workflow_id=?", (wf_id,)).fetchall()]
        for aid in art_ids:
            conn.execute("DELETE FROM comments WHERE artifact_id=?", (aid,))
        conn.execute("DELETE FROM artifacts WHERE workflow_id=?", (wf_id,))
        conn.execute("DELETE FROM stage_transitions WHERE workflow_id=?", (wf_id,))
        conn.execute("DELETE FROM approval_requests WHERE workflow_id=?", (wf_id,))
        conn.execute("DELETE FROM workflow_instances WHERE id=?", (wf_id,))
        _emit_event(conn, "workflow_deleted", wf_id)
        _record_user_activity(
            conn,
            user=user,
            action="workflow.delete",
            target_type="workflow",
            workflow_id=wf_id,
            target_id=wf_id,
            metadata={"title": wf["title"]},
        )
    return {"ok": True}


@router.post("/workflows/{wf_id}/transition")
def transition_workflow(wf_id: str, body: TransitionBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        wf = row_to_dict(conn.execute("SELECT * FROM workflow_instances WHERE id=?", (wf_id,)).fetchone())
        if not wf:
            raise HTTPException(404, "Workflow not found")

        target = row_to_dict(conn.execute("SELECT * FROM stage_definitions WHERE id=?", (body.to_stage_id,)).fetchone())
        if not target:
            raise HTTPException(400, "Invalid target stage")

        if target["transition_mode"] == "approval_required":
            now = _now()
            apr_id = _uuid("apr_")
            conn.execute(
                "INSERT INTO approval_requests (id, workflow_id, stage_id, status, requested_at, decided_by, note, requested_by_user_id) VALUES (?,?,?,?,?,?,?,?)",
                (apr_id, wf_id, body.to_stage_id, "pending", now, "", body.note, user["id"]),
            )
            conn.execute(
                "UPDATE workflow_instances SET status='pending_approval', updated_at=? WHERE id=?",
                (now, wf_id),
            )
            _emit_event(conn, "approval_requested", wf_id, payload={"approval_id": apr_id, "target_stage": body.to_stage_id})
            _record_user_activity(
                conn,
                user=user,
                action="workflow.request_approval",
                target_type="approval_request",
                workflow_id=wf_id,
                target_id=apr_id,
                metadata={"from_stage_id": wf["current_stage_id"], "to_stage_id": body.to_stage_id, "note": body.note},
            )
            return {"ok": True, "pending_approval": True, "approval_id": apr_id}

        now = _now()
        conn.execute(
            "UPDATE workflow_instances SET current_stage_id=?, updated_at=? WHERE id=?",
            (body.to_stage_id, now, wf_id),
        )
        conn.execute(
            "INSERT INTO stage_transitions (workflow_id, from_stage_id, to_stage_id, triggered_by, note, created_at, triggered_by_user_id) VALUES (?,?,?,?,?,?,?)",
            (wf_id, wf["current_stage_id"], body.to_stage_id, user["display_name"], body.note, now, user["id"]),
        )
        _emit_event(conn, "stage_changed", wf_id, payload={"from": wf["current_stage_id"], "to": body.to_stage_id})
        _record_user_activity(
            conn,
            user=user,
            action="workflow.transition",
            target_type="workflow",
            workflow_id=wf_id,
            target_id=wf_id,
            metadata={"from_stage_id": wf["current_stage_id"], "to_stage_id": body.to_stage_id, "note": body.note},
        )

    return {"ok": True, "current_stage_id": body.to_stage_id}


# ---------------------------------------------------------------------------
# API: Artifacts
# ---------------------------------------------------------------------------

def _get_artifact_file_path(workflow_id: str, stage_id: str, art_id: str, ext: str) -> Path:
    """Get the filesystem path for an artifact file."""
    return ARTIFACTS_DIR / workflow_id / stage_id / f"{art_id}.{ext}"


def _write_artifact_to_disk(workflow_id: str, stage_id: str, art_id: str, content: bytes, ext: str) -> tuple[str, int]:
    """Write artifact content to disk. Returns (relative_path, file_size)."""
    file_path = _get_artifact_file_path(workflow_id, stage_id, art_id, ext)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)
    relative = f"{workflow_id}/{stage_id}/{art_id}.{ext}"
    return relative, len(content)


def _ext_from_mime(mime_type: str) -> str:
    """Get file extension from mime type."""
    ext = mimetypes.guess_extension(mime_type) or ".bin"
    if ext.startswith("."):
        ext = ext[1:]
    # Common overrides
    if mime_type == "text/markdown":
        ext = "md"
    elif mime_type == "text/plain":
        ext = "txt"
    elif mime_type == "application/json":
        ext = "json"
    return ext


@router.post("/artifacts")
def create_artifact(body: CreateArtifactBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (body.workflow_id,)).fetchone()
        if not wf:
            raise HTTPException(404, "Workflow not found")

        now = _now()
        art_id = _uuid("art_")
        mime_type = body.content_type

        ext = _ext_from_mime(mime_type)
        content_bytes = body.content.encode("utf-8")
        file_path, file_size = _write_artifact_to_disk(body.workflow_id, body.stage_id, art_id, content_bytes, ext)

        conn.execute(
            """INSERT INTO artifacts
               (id, workflow_id, stage_id, artifact_type, title, content, content_type, status, file_path, file_size, mime_type, created_at, updated_at, created_by_user_id, updated_by_user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (art_id, body.workflow_id, body.stage_id, body.artifact_type, body.title, body.content, body.content_type, body.status, file_path, file_size, mime_type, now, now, user["id"], user["id"]),
        )
        _emit_event(conn, "artifact_added", body.workflow_id, art_id)
        _record_user_activity(
            conn,
            user=user,
            action="artifact.create",
            target_type="artifact",
            workflow_id=body.workflow_id,
            artifact_id=art_id,
            target_id=art_id,
            metadata={"stage_id": body.stage_id, "artifact_type": body.artifact_type, "title": body.title},
        )

    return {"id": art_id}


@router.post("/artifacts/upload")
async def upload_artifact(
    request: Request,
    workflow_id: str = Form(...),
    stage_id: str = Form(...),
    artifact_type: str = Form(...),
    title: str = Form(...),
    status: str = Form("draft"),
    file: UploadFile = File(...),
):
    """Upload a file as an artifact."""
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone()
        if not wf:
            raise HTTPException(404, "Workflow not found")

        now = _now()
        art_id = _uuid("art_")

        mime_type = file.content_type or "application/octet-stream"
        ext = _ext_from_mime(mime_type)
        if file.filename:
            parts = file.filename.rsplit(".", 1)
            if len(parts) > 1:
                ext = parts[1].lower()

        content_bytes = await file.read()
        file_path, file_size = _write_artifact_to_disk(workflow_id, stage_id, art_id, content_bytes, ext)

        content_text = ""
        if mime_type.startswith("text/") or mime_type == "application/json":
            try:
                content_text = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                pass

        conn.execute(
            """INSERT INTO artifacts
               (id, workflow_id, stage_id, artifact_type, title, content, content_type, status, file_path, file_size, mime_type, created_at, updated_at, created_by_user_id, updated_by_user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (art_id, workflow_id, stage_id, artifact_type, title, content_text, mime_type, status, file_path, file_size, mime_type, now, now, user["id"], user["id"]),
        )
        _emit_event(conn, "artifact_added", workflow_id, art_id)
        _record_user_activity(
            conn,
            user=user,
            action="artifact.upload",
            target_type="artifact",
            workflow_id=workflow_id,
            artifact_id=art_id,
            target_id=art_id,
            metadata={"stage_id": stage_id, "artifact_type": artifact_type, "title": title, "mime_type": mime_type, "file_size": file_size},
        )

    return {"id": art_id, "file_path": file_path, "file_size": file_size, "mime_type": mime_type}


@router.get("/artifacts/{art_id}")
def get_artifact(art_id: str):
    with get_db() as conn:
        art = row_to_dict(conn.execute("SELECT * FROM artifacts WHERE id=?", (art_id,)).fetchone())
        if not art:
            raise HTTPException(404, "Artifact not found")
        art["comments"] = rows_to_list(
            conn.execute("SELECT * FROM comments WHERE artifact_id=? ORDER BY created_at", (art_id,)).fetchall()
        )
    return art


@router.get("/artifacts/{art_id}/file")
def get_artifact_file(art_id: str):
    """Serve artifact file from disk."""
    with get_db() as conn:
        art = row_to_dict(conn.execute("SELECT * FROM artifacts WHERE id=?", (art_id,)).fetchone())
        if not art:
            raise HTTPException(404, "Artifact not found")

    file_path = art.get("file_path", "")
    if not file_path:
        if art["content"]:
            ext = _ext_from_mime(art.get("mime_type") or art["content_type"])
            content_bytes = art["content"].encode("utf-8")
            rel_path, file_size = _write_artifact_to_disk(art["workflow_id"], art["stage_id"], art_id, content_bytes, ext)
            with get_db() as conn:
                conn.execute(
                    "UPDATE artifacts SET file_path=?, file_size=?, mime_type=? WHERE id=?",
                    (rel_path, file_size, art.get("mime_type") or art["content_type"], art_id),
                )
            file_path = rel_path
        else:
            raise HTTPException(404, "No file content")

    full_path = ARTIFACTS_DIR / file_path
    if not full_path.exists():
        raise HTTPException(404, "File not found on disk")

    mime = art.get("mime_type") or art["content_type"]
    return FileResponse(str(full_path), media_type=mime)


@router.patch("/artifacts/{art_id}")
def update_artifact(art_id: str, body: UpdateArtifactBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        art = row_to_dict(conn.execute("SELECT * FROM artifacts WHERE id=?", (art_id,)).fetchone())
        if not art:
            raise HTTPException(404, "Artifact not found")

        updates = []
        params = []
        changed_fields: dict[str, Any] = {}
        for field in ("title", "content", "content_type", "status"):
            val = getattr(body, field, None)
            if val is not None:
                updates.append(f"{field}=?")
                params.append(val)
                changed_fields[field] = val

        if body.content is not None:
            mime = body.content_type or art["content_type"]
            ext = _ext_from_mime(mime)
            content_bytes = body.content.encode("utf-8")
            file_path, file_size = _write_artifact_to_disk(art["workflow_id"], art["stage_id"], art_id, content_bytes, ext)
            updates.extend(["file_path=?", "file_size=?", "mime_type=?"])
            params.extend([file_path, file_size, mime])
            changed_fields["file_path"] = file_path
            changed_fields["file_size"] = file_size
            changed_fields["mime_type"] = mime

        if updates:
            updates.extend(["updated_at=?", "updated_by_user_id=?"])
            params.extend([_now(), user["id"], art_id])
            conn.execute(f"UPDATE artifacts SET {','.join(updates)} WHERE id=?", params)
            _emit_event(conn, "artifact_updated", art["workflow_id"], art_id)
            _record_user_activity(
                conn,
                user=user,
                action="artifact.update",
                target_type="artifact",
                workflow_id=art["workflow_id"],
                artifact_id=art_id,
                target_id=art_id,
                metadata={"changes": changed_fields},
            )

    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Comments
# ---------------------------------------------------------------------------

@router.post("/artifacts/{art_id}/comments")
def create_comment(art_id: str, body: CreateCommentBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        art = conn.execute("SELECT * FROM artifacts WHERE id=?", (art_id,)).fetchone()
        if not art:
            raise HTTPException(404, "Artifact not found")

        now = _now()
        author = body.author.strip() or _actor_label(user, fallback=user["username"])
        cur = conn.execute(
            "INSERT INTO comments (artifact_id, author, author_user_id, body, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (art_id, author, user["id"], body.body, now, now),
        )
        comment_id = cur.lastrowid
        _emit_event(conn, "comment_added", art["workflow_id"], art_id, {"comment_id": comment_id})
        _record_user_activity(
            conn,
            user=user,
            action="comment.create",
            target_type="comment",
            workflow_id=art["workflow_id"],
            artifact_id=art_id,
            target_id=str(comment_id),
            metadata={"artifact_id": art_id},
        )

    return {"id": comment_id}


@router.patch("/comments/{comment_id}")
def update_comment(comment_id: int, body: UpdateCommentBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        comment = conn.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
        if not comment:
            raise HTTPException(404, "Comment not found")
        conn.execute(
            "UPDATE comments SET body=?, updated_at=? WHERE id=?",
            (body.body, _now(), comment_id),
        )
        art = conn.execute("SELECT workflow_id FROM artifacts WHERE id=?", (comment["artifact_id"],)).fetchone()
        if art:
            _emit_event(conn, "comment_updated", art["workflow_id"], comment["artifact_id"], {"comment_id": comment_id})
            _record_user_activity(
                conn,
                user=user,
                action="comment.update",
                target_type="comment",
                workflow_id=art["workflow_id"],
                artifact_id=comment["artifact_id"],
                target_id=str(comment_id),
                metadata={"artifact_id": comment["artifact_id"]},
            )

    return {"ok": True}


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        comment = conn.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
        if not comment:
            raise HTTPException(404, "Comment not found")
        art = conn.execute("SELECT workflow_id FROM artifacts WHERE id=?", (comment["artifact_id"],)).fetchone()
        conn.execute("DELETE FROM comments WHERE id=?", (comment_id,))
        if art:
            _emit_event(conn, "comment_deleted", art["workflow_id"], comment["artifact_id"], {"comment_id": comment_id})
            _record_user_activity(
                conn,
                user=user,
                action="comment.delete",
                target_type="comment",
                workflow_id=art["workflow_id"],
                artifact_id=comment["artifact_id"],
                target_id=str(comment_id),
                metadata={"artifact_id": comment["artifact_id"]},
            )

    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Skills
# ---------------------------------------------------------------------------

@router.get("/skills")
def list_skills(agent_type_id: str | None = Query(None)):
    with get_db() as conn:
        if agent_type_id:
            skills = rows_to_list(conn.execute(
                "SELECT * FROM skills WHERE agent_type_id=? OR agent_type_id IS NULL ORDER BY name",
                (agent_type_id,),
            ).fetchall())
        else:
            skills = rows_to_list(conn.execute("SELECT * FROM skills ORDER BY name").fetchall())
    return skills


@router.post("/skills")
def create_skill(body: CreateSkillBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        now = _now()
        skill_id = _uuid("skill_")
        conn.execute(
            "INSERT INTO skills (id, name, description, content, agent_type_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (skill_id, body.name, body.description, body.content, body.agent_type_id, now, now),
        )
        _emit_event(conn, "skill_created", payload={"skill_id": skill_id})
        _record_user_activity(
            conn,
            user=user,
            action="skill.create",
            target_type="skill",
            target_id=skill_id,
            metadata={"name": body.name, "agent_type_id": body.agent_type_id},
        )
    return {"id": skill_id}


@router.get("/skills/{skill_id}")
def get_skill(skill_id: str):
    with get_db() as conn:
        skill = row_to_dict(conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone())
        if not skill:
            raise HTTPException(404, "Skill not found")
    return skill


@router.patch("/skills/{skill_id}")
def update_skill(skill_id: str, body: UpdateSkillBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        skill = conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
        if not skill:
            raise HTTPException(404, "Skill not found")

        updates = []
        params = []
        changed_fields: dict[str, Any] = {}
        for field in ("name", "description", "content", "agent_type_id"):
            val = getattr(body, field, None)
            if val is not None:
                updates.append(f"{field}=?")
                params.append(val)
                changed_fields[field] = val

        if updates:
            updates.append("updated_at=?")
            params.append(_now())
            params.append(skill_id)
            conn.execute(f"UPDATE skills SET {','.join(updates)} WHERE id=?", params)
            _emit_event(conn, "skill_updated", payload={"skill_id": skill_id})
            _record_user_activity(
                conn,
                user=user,
                action="skill.update",
                target_type="skill",
                target_id=skill_id,
                metadata={"changes": changed_fields},
            )

    return {"ok": True}


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        skill = conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
        if not skill:
            raise HTTPException(404, "Skill not found")
        conn.execute("DELETE FROM workflow_skill_bindings WHERE skill_id=?", (skill_id,))
        conn.execute("DELETE FROM skills WHERE id=?", (skill_id,))
        _emit_event(conn, "skill_deleted", payload={"skill_id": skill_id})
        _record_user_activity(
            conn,
            user=user,
            action="skill.delete",
            target_type="skill",
            target_id=skill_id,
            metadata={"name": skill["name"]},
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Workflow Definitions
# ---------------------------------------------------------------------------

@router.get("/templates/{template_id}/definition")
def get_definition(template_id: str):
    with get_db() as conn:
        tmpl = conn.execute("SELECT * FROM workflow_templates WHERE id=?", (template_id,)).fetchone()
        if not tmpl:
            raise HTTPException(404, "Template not found")

        defn = row_to_dict(conn.execute(
            "SELECT * FROM workflow_definitions WHERE template_id=?", (template_id,)
        ).fetchone())

    return defn or {"id": None, "template_id": template_id, "content": "", "created_at": None, "updated_at": None}


@router.put("/templates/{template_id}/definition")
def upsert_definition(template_id: str, body: UpdateDefinitionBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        tmpl = conn.execute("SELECT * FROM workflow_templates WHERE id=?", (template_id,)).fetchone()
        if not tmpl:
            raise HTTPException(404, "Template not found")

        now = _now()
        existing = conn.execute("SELECT * FROM workflow_definitions WHERE template_id=?", (template_id,)).fetchone()

        if existing:
            conn.execute(
                "UPDATE workflow_definitions SET content=?, updated_at=? WHERE template_id=?",
                (body.content, now, template_id),
            )
        else:
            def_id = _uuid("wdef_")
            conn.execute(
                "INSERT INTO workflow_definitions (id, template_id, content, created_at, updated_at) VALUES (?,?,?,?,?)",
                (def_id, template_id, body.content, now, now),
            )

        _emit_event(conn, "definition_updated", payload={"template_id": template_id})
        _record_user_activity(
            conn,
            user=user,
            action="template.definition_upsert",
            target_type="workflow_definition",
            target_id=template_id,
            metadata={"template_id": template_id, "content_length": len(body.content)},
        )

    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Skill Bindings
# ---------------------------------------------------------------------------

@router.get("/templates/{template_id}/skills")
def list_skill_bindings(template_id: str):
    with get_db() as conn:
        bindings = rows_to_list(conn.execute(
            """SELECT wsb.*, s.name as skill_name, s.description as skill_description
               FROM workflow_skill_bindings wsb
               JOIN skills s ON wsb.skill_id = s.id
               WHERE wsb.template_id=?
               ORDER BY wsb.execution_order""",
            (template_id,),
        ).fetchall())
    return bindings


@router.post("/templates/{template_id}/skills")
def create_skill_binding(template_id: str, body: CreateSkillBindingBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        tmpl = conn.execute("SELECT * FROM workflow_templates WHERE id=?", (template_id,)).fetchone()
        if not tmpl:
            raise HTTPException(404, "Template not found")
        skill = conn.execute("SELECT * FROM skills WHERE id=?", (body.skill_id,)).fetchone()
        if not skill:
            raise HTTPException(404, "Skill not found")

        try:
            cur = conn.execute(
                "INSERT INTO workflow_skill_bindings (template_id, skill_id, stage_id, execution_order) VALUES (?,?,?,?)",
                (template_id, body.skill_id, body.stage_id, body.execution_order),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Binding already exists")

        _emit_event(conn, "binding_created", payload={"template_id": template_id, "skill_id": body.skill_id})
        _record_user_activity(
            conn,
            user=user,
            action="template.skill_binding_create",
            target_type="workflow_skill_binding",
            target_id=str(cur.lastrowid),
            metadata={"template_id": template_id, "skill_id": body.skill_id, "stage_id": body.stage_id},
        )

    return {"id": cur.lastrowid}


@router.delete("/templates/{template_id}/skills/{binding_id}")
def delete_skill_binding(template_id: str, binding_id: int, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        binding = conn.execute(
            "SELECT * FROM workflow_skill_bindings WHERE id=? AND template_id=?", (binding_id, template_id)
        ).fetchone()
        if not binding:
            raise HTTPException(404, "Binding not found")
        conn.execute("DELETE FROM workflow_skill_bindings WHERE id=?", (binding_id,))
        _emit_event(conn, "binding_deleted", payload={"template_id": template_id, "binding_id": binding_id})
        _record_user_activity(
            conn,
            user=user,
            action="template.skill_binding_delete",
            target_type="workflow_skill_binding",
            target_id=str(binding_id),
            metadata={"template_id": template_id, "skill_id": binding["skill_id"], "stage_id": binding["stage_id"]},
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Stage HITL Settings
# ---------------------------------------------------------------------------

@router.patch("/stages/{stage_id}")
def update_stage(stage_id: str, body: UpdateStageBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        stage = conn.execute("SELECT * FROM stage_definitions WHERE id=?", (stage_id,)).fetchone()
        if not stage:
            raise HTTPException(404, "Stage not found")

        updates = []
        params = []
        changed_fields: dict[str, Any] = {}
        if body.transition_mode is not None:
            if body.transition_mode not in ("auto", "approval_required"):
                raise HTTPException(400, "transition_mode must be 'auto' or 'approval_required'")
            updates.append("transition_mode=?")
            params.append(body.transition_mode)
            changed_fields["transition_mode"] = body.transition_mode
        if body.approval_roles is not None:
            updates.append("approval_roles=?")
            params.append(body.approval_roles)
            changed_fields["approval_roles"] = body.approval_roles

        if updates:
            params.append(stage_id)
            conn.execute(f"UPDATE stage_definitions SET {','.join(updates)} WHERE id=?", params)
            _emit_event(conn, "stage_updated", payload={"stage_id": stage_id})
            _record_user_activity(
                conn,
                user=user,
                action="stage.update",
                target_type="stage",
                target_id=stage_id,
                metadata={"changes": changed_fields},
            )

    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Approval System
# ---------------------------------------------------------------------------

@router.get("/approvals")
def list_approvals(workflow_id: str | None = Query(None), status: str | None = Query(None)):
    with get_db() as conn:
        query = """
            SELECT ar.*, wi.title as workflow_title, sd.name as stage_name
            FROM approval_requests ar
            JOIN workflow_instances wi ON ar.workflow_id = wi.id
            JOIN stage_definitions sd ON ar.stage_id = sd.id
        """
        conditions = []
        params = []
        if workflow_id:
            conditions.append("ar.workflow_id=?")
            params.append(workflow_id)
        if status:
            conditions.append("ar.status=?")
            params.append(status)
        else:
            conditions.append("ar.status='pending'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY ar.requested_at DESC"

        approvals = rows_to_list(conn.execute(query, params).fetchall())
    return approvals


@router.post("/approvals/{approval_id}/decide")
def decide_approval(approval_id: str, body: DecideApprovalBody, request: Request):
    if body.status not in ("approved", "rejected"):
        raise HTTPException(400, "Status must be 'approved' or 'rejected'")

    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        apr = row_to_dict(conn.execute("SELECT * FROM approval_requests WHERE id=?", (approval_id,)).fetchone())
        if not apr:
            raise HTTPException(404, "Approval request not found")
        if apr["status"] != "pending":
            raise HTTPException(400, "Approval already decided")

        now = _now()
        decided_by = body.decided_by.strip() or _actor_label(user, fallback=user["username"])
        conn.execute(
            "UPDATE approval_requests SET status=?, decided_by=?, decided_at=?, note=?, decided_by_user_id=? WHERE id=?",
            (body.status, decided_by, now, body.note, user["id"], approval_id),
        )

        wf = row_to_dict(conn.execute("SELECT * FROM workflow_instances WHERE id=?", (apr["workflow_id"],)).fetchone())

        if body.status == "approved":
            conn.execute(
                "UPDATE workflow_instances SET current_stage_id=?, status='active', updated_at=? WHERE id=?",
                (apr["stage_id"], now, apr["workflow_id"]),
            )
            conn.execute(
                "INSERT INTO stage_transitions (workflow_id, from_stage_id, to_stage_id, triggered_by, note, created_at, triggered_by_user_id) VALUES (?,?,?,?,?,?,?)",
                (apr["workflow_id"], wf["current_stage_id"], apr["stage_id"], decided_by, f"승인: {body.note}" if body.note else "승인됨", now, user["id"]),
            )
            _emit_event(conn, "approval_approved", apr["workflow_id"], payload={"approval_id": approval_id, "trigger_next": True})
            _emit_event(conn, "stage_changed", apr["workflow_id"], payload={"from": wf["current_stage_id"], "to": apr["stage_id"], "trigger_next": True})
        else:
            conn.execute(
                "UPDATE workflow_instances SET status='active', updated_at=? WHERE id=?",
                (now, apr["workflow_id"]),
            )
            _emit_event(conn, "approval_rejected", apr["workflow_id"], payload={"approval_id": approval_id})

        _record_user_activity(
            conn,
            user=user,
            action=f"approval.{body.status}",
            target_type="approval_request",
            workflow_id=apr["workflow_id"],
            target_id=approval_id,
            metadata={"stage_id": apr["stage_id"], "note": body.note},
        )

    return {"ok": True, "status": body.status}


# ---------------------------------------------------------------------------
# API: Events (polling)
# ---------------------------------------------------------------------------

@router.get("/events")
def get_events(since: int = Query(0), limit: int = Query(200)):
    with get_db() as conn:
        events = rows_to_list(
            conn.execute(
                "SELECT * FROM ax_events WHERE id > ? ORDER BY id LIMIT ?", (since, limit)
            ).fetchall()
        )
        cursor = events[-1]["id"] if events else since

    return {"events": events, "cursor": cursor}
