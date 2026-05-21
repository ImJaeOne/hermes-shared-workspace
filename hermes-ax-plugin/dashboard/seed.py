from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

SEED_DATA: dict[str, Any] = {
    "agents": [
        {
            "id": "planning",
            "name": "Planning Agent",
            "description": "기획 파이프라인 — 리서치부터 최종 브리핑까지",
            "icon": "ClipboardList",
            "color": "#3b82f6",
        },
        {
            "id": "design",
            "name": "Design Agent",
            "description": "디자인 파이프라인 — 탐색부터 핸드오프까지",
            "icon": "PenTool",
            "color": "#ec4899",
        },
    ],
    "templates": [
        {"id": "planning_pipeline_v1", "agent_type_id": "planning", "name": "Planning Pipeline v1"},
        {"id": "design_pipeline_v1", "agent_type_id": "design", "name": "Design Pipeline v1"},
    ],
    "stages": [
        {
            "id": "p_discovery",
            "template_id": "planning_pipeline_v1",
            "name": "Discovery",
            "slug": "discovery",
            "stage_order": 0,
            "expected_artifacts": '["brief","meeting_notes"]',
        },
        {
            "id": "p_brief",
            "template_id": "planning_pipeline_v1",
            "name": "Brief Draft",
            "slug": "brief-draft",
            "stage_order": 1,
            "expected_artifacts": '["brief"]',
        },
        {
            "id": "p_review",
            "template_id": "planning_pipeline_v1",
            "name": "Stakeholder Review",
            "slug": "review",
            "stage_order": 2,
            "expected_artifacts": '["meeting_notes","email"]',
            "transition_mode": "approval_required",
            "approval_roles": '["manager"]',
        },
        {
            "id": "p_handoff",
            "template_id": "planning_pipeline_v1",
            "name": "Handoff",
            "slug": "handoff",
            "stage_order": 3,
            "expected_artifacts": '["report"]',
        },
        {
            "id": "d_research",
            "template_id": "design_pipeline_v1",
            "name": "Research",
            "slug": "research",
            "stage_order": 0,
            "expected_artifacts": '["brief","meeting_notes"]',
        },
        {
            "id": "d_concept",
            "template_id": "design_pipeline_v1",
            "name": "Concept Sketch",
            "slug": "concept-sketch",
            "stage_order": 1,
            "expected_artifacts": '["brief","content_draft"]',
        },
        {
            "id": "d_review",
            "template_id": "design_pipeline_v1",
            "name": "Design Review",
            "slug": "review",
            "stage_order": 2,
            "expected_artifacts": '["content_draft"]',
            "transition_mode": "approval_required",
            "approval_roles": '["manager"]',
        },
        {
            "id": "d_handoff",
            "template_id": "design_pipeline_v1",
            "name": "Handoff",
            "slug": "handoff",
            "stage_order": 3,
            "expected_artifacts": '["content_draft","report"]',
        },
    ],
    "skills": [
        {
            "id": "skill_001",
            "name": "기획 브리프 작성",
            "description": "리서치 내용을 바탕으로 기획 브리프를 정리합니다.",
            "content": "# 기획 브리프 작성\n\n## 목적\n리서치 결과를 구조화하여 이해관계자와 공유할 수 있는 기획 브리프를 작성합니다.\n\n## 입력\n- 프로젝트 목표\n- 사용자/시장 인사이트\n- 제약사항\n- 참고 자료\n\n## 출력 형식\n- 요약\n- 핵심 문제\n- 제안 방향\n- 다음 단계\n\n## 작성 원칙\n- 문장은 짧고 명확하게\n- 의사결정에 필요한 정보만 남기기\n- 액션 아이템은 담당자와 기한을 포함하기",
            "agent_type_id": "planning",
        },
        {
            "id": "skill_002",
            "name": "스테이크홀더 미팅 노트 정리",
            "description": "회의 내용을 기획 관점으로 정리합니다.",
            "content": "# 스테이크홀더 미팅 노트 정리\n\n## 목적\n회의에서 나온 의견, 결정 사항, 후속 액션을 정리합니다.\n\n## 구조\n1. 회의 정보\n2. 핵심 논의 사항\n3. 결정 사항\n4. 액션 아이템\n5. 후속 일정\n\n## 작성 규칙\n- 발언보다 결정과 합의에 집중\n- 액션은 체크리스트로 명시\n- 다음 단계가 분명해야 함",
            "agent_type_id": "planning",
        },
        {
            "id": "skill_003",
            "name": "디자인 콘셉트 설명서 작성",
            "description": "디자인 방향과 화면 구성을 설명합니다.",
            "content": "# 디자인 콘셉트 설명서 작성\n\n## 목적\n화면 구조, 비주얼 방향, 인터랙션 의도를 간결하게 설명합니다.\n\n## 필수 항목\n- 문제 정의\n- 참고 레퍼런스\n- 레이아웃 방향\n- 시각적 톤앤매너\n- 주요 인터랙션\n\n## 작성 팁\n- 화면 단위로 구분해서 설명\n- 와이어프레임과 시안의 차이를 명확히\n- 개발/기획이 이해할 수 있는 언어 사용",
            "agent_type_id": "design",
        },
        {
            "id": "skill_004",
            "name": "디자인 리뷰 피드백 정리",
            "description": "디자인 리뷰 의견을 구조화하여 정리합니다.",
            "content": "# 디자인 리뷰 피드백 정리\n\n## 목적\n리뷰 코멘트를 실행 가능한 피드백으로 정리합니다.\n\n## 정리 항목\n- 개선 포인트\n- 우선순위\n- 영향 범위\n- 담당자\n- 반영 기한\n\n## 작성 규칙\n- 주관적 표현보다 관찰 가능한 사실을 먼저 적기\n- 변경 요청과 이유를 분리하기\n- 수정 후 재검토가 필요한 항목을 표시하기",
            "agent_type_id": "design",
        },
        {
            "id": "skill_005",
            "name": "협업 회의 요약 템플릿",
            "description": "기획과 디자인 공통으로 사용하는 회의 요약 템플릿입니다.",
            "content": "# 협업 회의 요약 템플릿\n\n## 회의 정보\n- 일시\n- 참석자\n- 목적\n\n## 요약\n- 핵심 논의\n- 합의 사항\n- 보류 사항\n\n## 액션\n- 담당자\n- 기한\n- 후속 확인 포인트",
            "agent_type_id": None,
        },
    ],
}


def seed_if_empty(conn: sqlite3.Connection, now_fn: Callable[[], str], emit_event: Callable[..., None]):
    row = conn.execute("SELECT count(*) as c FROM agent_types").fetchone()
    if row["c"] > 0:
        return

    now = now_fn()
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
        conn.execute(
            "INSERT INTO stage_definitions (id, template_id, name, slug, stage_order, expected_artifacts, trigger_conditions, transition_mode, approval_roles, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                s["id"],
                s["template_id"],
                s["name"],
                s["slug"],
                s["stage_order"],
                s["expected_artifacts"],
                "{}",
                s.get("transition_mode", "auto"),
                s.get("approval_roles", "[]"),
                now,
            ),
        )

    for sk in SEED_DATA.get("skills", []):
        conn.execute(
            "INSERT INTO skills (id, name, description, content, agent_type_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (sk["id"], sk["name"], sk["description"], sk["content"], sk["agent_type_id"], now, now),
        )

    seed_sample_data(conn, now, emit_event)


def seed_sample_data(conn: sqlite3.Connection, now: str, emit_event: Callable[..., None]):
    def _ins_wf(wid, tmpl, agent, title, stage, status, priority, assignee):
        conn.execute(
            "INSERT INTO workflow_instances (id,template_id,agent_type_id,title,current_stage_id,status,priority,assignee,metadata_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (wid, tmpl, agent, title, stage, status, priority, assignee, "{}", now, now),
        )
        conn.execute(
            "INSERT INTO stage_transitions (workflow_id,from_stage_id,to_stage_id,triggered_by,note,created_at) VALUES (?,?,?,?,?,?)",
            (wid, None, stage, "system", "워크플로우 생성", now),
        )
        emit_event(conn, "workflow_created", wid)

    def _ins_art(aid, wid, stage, atype, title, content, ctype="text/markdown", status="draft"):
        conn.execute(
            "INSERT INTO artifacts (id,workflow_id,stage_id,artifact_type,title,content,content_type,status,file_path,file_size,mime_type,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, wid, stage, atype, title, content, ctype, status, "", 0, ctype, now, now),
        )
        emit_event(conn, "artifact_added", wid, aid)

    def _ins_comment(aid, author, body):
        conn.execute(
            "INSERT INTO comments (artifact_id,author,body,created_at,updated_at) VALUES (?,?,?,?,?)",
            (aid, author, body, now, now),
        )

    _ins_wf("wi_plan_001", "planning_pipeline_v1", "planning", "Q4 제품 로드맵 정리", "p_review", "active", 1, "김기획")
    _ins_art(
        "art_p001",
        "wi_plan_001",
        "p_discovery",
        "brief",
        "리서치 인사이트 초안",
        "## 리서치 요약\n\n- 사용자 인터뷰 8건 완료\n- 주요 요구: 빠른 검토 흐름과 명확한 우선순위\n- 개선 포인트: 승인 단계의 맥락 부족\n\n## 다음 단계\n- 이해관계자별 우선순위 정리\n- 브리프 초안 작성",
        "text/markdown",
        "final",
    )
    _ins_comment("art_p001", "김기획", "핵심 문제는 승인 기준이 모호하다는 점입니다. 리뷰 단계에서 정리하겠습니다.")
    _ins_art(
        "art_p002",
        "wi_plan_001",
        "p_brief",
        "brief",
        "Q4 기획 브리프",
        "## Q4 기획 브리프\n\n### 목표\n- 승인 대기 시간을 줄이고 협업 맥락을 명확히 한다.\n\n### 범위\n- 기획 브리프 템플릿 정리\n- 의사결정 기준 명시\n- 디자인 팀 인수인계 포인트 정리",
        "text/markdown",
        "draft",
    )
    _ins_art(
        "art_p003",
        "wi_plan_001",
        "p_review",
        "meeting_notes",
        "스테이크홀더 리뷰 노트",
        "## 리뷰 회의 (2026-05-18)\n\n**참석자**: 김기획, 박디자이너, 제품팀 리더\n\n### 결정 사항\n- 브리프는 3가지 핵심 질문으로 축약\n- 디자인 핸드오프에 필요한 체크리스트 추가\n\n### 액션 아이템\n- [ ] 브리프 초안 재정리\n- [ ] 디자인 팀 의견 반영\n- [ ] 다음 회의 전 공유",
        "text/markdown",
        "final",
    )
    _ins_comment("art_p003", "제품팀 리더", "기획안이 훨씬 명확해졌습니다. 승인 기준을 한 페이지로 정리해주세요.")
    _ins_wf("wi_plan_002", "planning_pipeline_v1", "planning", "신규 기능 우선순위 워크숍", "p_handoff", "completed", 0, "이기획")
    _ins_art(
        "art_p010",
        "wi_plan_002",
        "p_handoff",
        "report",
        "우선순위 정리 결과",
        "## 우선순위 정리 결과\n\n- 상위 과제 3건 확정\n- 분기별 로드맵 초안 공유 완료\n- 디자인 리소스 요청 범위 합의",
        "text/markdown",
        "final",
    )

    _ins_wf("wi_des_001", "design_pipeline_v1", "design", "모바일 앱 홈 개편", "d_review", "active", 2, "박디자이너")
    _ins_art(
        "art_d001",
        "wi_des_001",
        "d_research",
        "brief",
        "UX 리서치 요약",
        "## 리서치 요약\n\n- 홈 화면 진입 후 주요 CTA 인지가 낮음\n- 정보 밀도가 높아 첫 화면 피로도가 큼\n- 우선 개선 포인트는 섹션 구조와 시각적 위계",
        "text/markdown",
        "final",
    )
    _ins_comment("art_d001", "박디자이너", "기획 단계에서 정리된 우선순위와 맞춰서 구조를 단순화하겠습니다.")
    _ins_art(
        "art_d002",
        "wi_des_001",
        "d_concept",
        "content_draft",
        "홈 화면 와이어프레임 초안",
        "## 화면 구조\n\n- 상단: 핵심 CTA\n- 중단: 최근 작업 카드\n- 하단: 추천 액션\n\n### 의도\n첫 진입 시 사용자가 다음 행동을 쉽게 선택하도록 화면을 단순화한다.",
        "text/markdown",
        "draft",
    )
    _ins_comment("art_d002", "김기획", "중단 카드의 우선순위를 조금 더 낮추면 좋겠습니다.")
    _ins_art(
        "art_d003",
        "wi_des_001",
        "d_review",
        "content_draft",
        "디자인 리뷰 반영본",
        "## 반영 포인트\n\n- CTA 크기 확대\n- 섹션 간 간격 조정\n- 상태 메시지 추가\n\n## 남은 확인 사항\n- 모바일 대응\n- 빈 상태 처리",
        "text/markdown",
        "draft",
    )
    _ins_wf("wi_des_002", "design_pipeline_v1", "design", "온보딩 랜딩 페이지 시안", "d_handoff", "completed", 0, "최디자이너")
    _ins_art(
        "art_d010",
        "wi_des_002",
        "d_concept",
        "content_draft",
        "랜딩 페이지 콘셉트",
        "## 랜딩 페이지 콘셉트\n\n- 첫 화면에서 가치 제안이 바로 보이도록 구성\n- 핵심 혜택과 사회적 증거를 상단에 배치\n- 전환 버튼은 한 가지 행동으로 통일",
        "text/markdown",
        "draft",
    )
    _ins_art(
        "art_d011",
        "wi_des_002",
        "d_handoff",
        "report",
        "디자인 핸드오프 요약",
        "## 핸드오프 요약\n\n- 최종 컴포넌트 규칙 공유\n- 스타일 가이드 반영 완료\n- 개발 전달용 주석 정리",
        "text/markdown",
        "final",
    )
    _ins_comment("art_d011", "최디자이너", "개발팀 전달용 메모까지 포함했습니다. 바로 구현 가능합니다.")
