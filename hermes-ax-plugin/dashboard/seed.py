from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

SEED_DATA: dict[str, Any] = {
    "agents": [
        {
            "id": "planning",
            "name": "Planning Agent",
            "description": "기획 자료조사 MVP — Slack 회사 채널 자료 확인부터 조사 결과 확정까지",
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
        {"id": "planning_research_mvp_v1", "agent_type_id": "planning", "name": "Planning Research MVP v1"},
        {"id": "design_pipeline_v1", "agent_type_id": "design", "name": "Design Pipeline v1"},
    ],
    "stages": [
        {
            "id": "p_material_requesting",
            "template_id": "planning_research_mvp_v1",
            "name": "자료 요청 중",
            "slug": "material-requesting",
            "stage_order": 0,
            "expected_artifacts": '["source_material"]',
        },
        {
            "id": "p_material_waiting",
            "template_id": "planning_research_mvp_v1",
            "name": "자료 확인 대기",
            "slug": "material-waiting",
            "stage_order": 1,
            "expected_artifacts": '["source_material"]',
        },
        {
            "id": "p_research_running",
            "template_id": "planning_research_mvp_v1",
            "name": "자료조사 실행 중",
            "slug": "research-running",
            "stage_order": 2,
            "expected_artifacts": '["source_material","research_report"]',
        },
        {
            "id": "p_user_review_waiting",
            "template_id": "planning_research_mvp_v1",
            "name": "사용자 검토 대기",
            "slug": "user-review-waiting",
            "stage_order": 3,
            "expected_artifacts": '["research_report"]',
        },
        {
            "id": "p_revision_running",
            "template_id": "planning_research_mvp_v1",
            "name": "수정 요청 처리 중",
            "slug": "revision-running",
            "stage_order": 4,
            "expected_artifacts": '["research_report"]',
        },
        {
            "id": "p_research_confirmed",
            "template_id": "planning_research_mvp_v1",
            "name": "자료조사 확정",
            "slug": "research-confirmed",
            "stage_order": 5,
            "expected_artifacts": '["research_report"]',
            "transition_mode": "approval_required",
            "approval_roles": '["human_user","planning_lead"]',
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
            "name": "기획 자료조사 결과 정리",
            "description": "회사 채널 자료와 외부 조사를 바탕으로 자료조사 결과를 정리합니다.",
            "content": "# 기획 자료조사 결과 정리\n\n## 목적\nSlack 회사 채널에 첨부된 자료와 보완 조사를 구조화하여 회사 담당자가 검토할 수 있는 자료조사 결과를 작성합니다.\n\n## 입력\n- 사용자가 첨부한 파일/링크/설명\n- 회사/제품/시장 관련 공개 자료\n- 기획팀 임팀장의 확인 메모\n\n## 출력 형식\n- 핵심 요약\n- 회사/제품 이해\n- 시장·고객 맥락\n- 콘텐츠 기획에 쓸 수 있는 포인트\n- 추가 확인이 필요한 질문\n\n## 작성 원칙\n- 확인된 사실과 추정을 구분하기\n- 출처가 있는 항목은 자료명을 남기기\n- 시놉시스/스토리보드/원고는 후속 placeholder로만 언급하기",
            "agent_type_id": "planning",
        },
        {
            "id": "skill_002",
            "name": "Slack 회사 채널 자료 확인",
            "description": "회사 채널에 전달된 파일 목록과 추가 필요 자료를 확인합니다.",
            "content": "# Slack 회사 채널 자료 확인\n\n## 목적\n`#회사명` Slack 채널에서 사용자가 전달한 자료를 확인하고 자료조사 실행 가능 여부를 판단합니다.\n\n## 확인 항목\n1. 회사명과 프로젝트명 매핑\n2. 첨부 파일/링크/설명 목록\n3. 열람 권한과 누락 자료\n4. 자료조사 worker에게 전달할 실행 메모\n\n## 작성 규칙\n- 사용자에게 보이는 용어는 회사 프로젝트, 자료, 자료조사 결과로 정리\n- 부족한 자료는 기획팀 임팀장이 요청할 수 있게 질문 형태로 남기기\n- 실행 가능 상태가 되면 담당자를 기획팀 임사원으로 넘기기",
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
    def _planning_metadata(company_name: str, channel_id: str) -> str:
        return json.dumps(
            {
                "company_name": company_name,
                "project_key": f"planning-research:{company_name}",
                "source": "slack",
                "slack": {
                    "channel_name": company_name,
                    "channel_id": channel_id,
                },
                "mvp_scope": "research_only",
                "future_placeholders": ["synopsis", "storyboard", "script"],
            },
            ensure_ascii=False,
        )

    def _ins_wf(wid, tmpl, agent, title, stage, status, priority, assignee, metadata_json="{}"):
        conn.execute(
            "INSERT INTO workflow_instances (id,template_id,agent_type_id,title,current_stage_id,status,priority,assignee,metadata_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (wid, tmpl, agent, title, stage, status, priority, assignee, metadata_json, now, now),
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

    _ins_wf(
        "wi_plan_001",
        "planning_research_mvp_v1",
        "planning",
        "[덕우전자] 기획 자료조사",
        "p_user_review_waiting",
        "active",
        1,
        "회사 담당자 확인 대기",
        _planning_metadata("덕우전자", "C025DUKWOO"),
    )
    _ins_art(
        "art_p001",
        "wi_plan_001",
        "p_material_waiting",
        "source_material",
        "덕우전자 전달 자료 목록",
        "## Slack #덕우전자 전달 자료\n\n- `덕우전자_회사소개서_2026.pdf`\n- `제품군_요약_카메라모듈_부품.xlsx`\n- 기존 홍보 영상 링크 2건\n- 담당자 메모: 자동차 전장 부품과 스마트폰 부품을 함께 다루되 최근 전장 비중을 강조\n\n## 추가자료 확인\n- 해외 매출 비중 표 열람 권한 확인 완료\n- 수상/인증 자료는 공개 자료로 보완 조사 예정\n\n## 다음 처리\n기획팀 임팀장이 자료 목록을 확인했고, 기획팀 임사원이 자료조사 결과 초안을 작성했습니다.",
        "text/markdown",
        "final",
    )
    _ins_comment("art_p001", "덕우전자 담당자", "첨부한 제품군 요약 파일의 전장 부품 탭을 우선 참고해주세요.")
    _ins_art(
        "art_p002",
        "wi_plan_001",
        "p_user_review_waiting",
        "research_report",
        "덕우전자 자료조사 결과 초안",
        "## 덕우전자 자료조사 결과 초안\n\n### 핵심 요약\n- 덕우전자는 전자부품 제조 기반을 바탕으로 모바일·자동차 전장 부품을 공급하는 회사입니다.\n- 최근 콘텐츠에서는 정밀 제조 역량, 품질 관리, 전장 분야 확장성을 함께 보여주는 방향이 적합합니다.\n\n### 콘텐츠 기획 포인트\n1. 회사 신뢰도: 주요 생산 역량과 품질 인증을 시각 자료로 정리\n2. 제품 이해: 스마트폰 부품과 전장 부품을 구분해 적용 사례 중심으로 설명\n3. 미래 방향: 전장 부품 비중 확대와 고객사 요구 대응력을 강조\n\n### 사용자 확인 필요\n- 전장 부품 매출 비중을 공개 가능한 범위로 표현해도 되는지 확인 필요\n- 대표 제품 이미지는 첨부 자료 기준 사용 가능 여부 확인 필요\n\n### 후속 placeholder\n시놉시스, 스토리보드, 원고는 자료조사 확정 후 후속 단계에서 preview로 다룹니다.",
        "text/markdown",
        "draft",
    )
    _ins_comment("art_p002", "덕우전자 담당자", "스마트폰 부품보다 전장 부품 확장 흐름이 더 잘 보이도록 요약 순서를 바꿔주세요.")

    _ins_wf(
        "wi_plan_002",
        "planning_research_mvp_v1",
        "planning",
        "[한빛식품] 기획 자료조사",
        "p_research_running",
        "active",
        2,
        "기획팀 임사원",
        _planning_metadata("한빛식품", "C026HANBIT"),
    )
    _ins_art(
        "art_p010",
        "wi_plan_002",
        "p_material_waiting",
        "source_material",
        "한빛식품 전달 자료 목록",
        "## Slack #한빛식품 전달 자료\n\n- 브랜드 소개서 PDF\n- 신제품 패키지 이미지 6종\n- 온라인몰 상세페이지 링크\n- 담당자 요청: 건강 간편식 카테고리에서 차별화 포인트 조사\n\n## 추가자료 확인\n- 원재료 원산지 표기는 공개 범위 확인 대기\n- 경쟁 제품 가격대는 worker가 공개 자료로 보완 조사",
        "text/markdown",
        "final",
    )
    _ins_art(
        "art_p011",
        "wi_plan_002",
        "p_research_running",
        "research_report",
        "한빛식품 자료조사 실행 메모",
        "## 실행 중 메모\n\n기획팀 임사원이 전달 자료와 공개 자료를 함께 확인 중입니다.\n\n- 브랜드 톤: 건강함, 간편함, 가족 식탁\n- 우선 조사: 간편식 시장 트렌드, 경쟁 제품 메시지, 온라인몰 리뷰 키워드\n- 결과 전달 예정: 핵심 요약과 콘텐츠 기획 포인트 중심 초안",
        "text/markdown",
        "draft",
    )

    _ins_wf(
        "wi_plan_003",
        "planning_research_mvp_v1",
        "planning",
        "[에코모빌리티] 기획 자료조사",
        "p_research_confirmed",
        "completed",
        0,
        "기획팀 임팀장",
        _planning_metadata("에코모빌리티", "C027ECOMOB"),
    )
    _ins_art(
        "art_p020",
        "wi_plan_003",
        "p_material_waiting",
        "source_material",
        "에코모빌리티 전달 자료 목록",
        "## Slack #에코모빌리티 전달 자료\n\n- 기업 소개서\n- 전기 배송차 제품 브로슈어\n- 충전 인프라 구축 사례 링크\n\n자료 확인 후 자료조사 worker에게 전달 완료했습니다.",
        "text/markdown",
        "final",
    )
    _ins_art(
        "art_p021",
        "wi_plan_003",
        "p_research_confirmed",
        "research_report",
        "에코모빌리티 자료조사 최종본",
        "## 에코모빌리티 자료조사 최종본\n\n### 핵심 요약\n- 전기 배송차와 충전 인프라 운영 경험을 함께 제시하는 것이 회사 신뢰도를 높입니다.\n- B2B 고객에게는 총소유비용 절감, 운영 안정성, ESG 대응 메시지가 중요합니다.\n\n### 확정된 기획 포인트\n1. 실제 배송 운영 사례를 중심으로 제품 효용 설명\n2. 충전 인프라 구축 경험을 별도 신뢰 요소로 배치\n3. 후속 시놉시스/스토리보드/원고에서는 ESG와 비용 절감 메시지를 preview로 확장\n\n사용자 확인을 거쳐 자료조사 단계가 확정되었습니다.",
        "text/markdown",
        "final",
    )
    _ins_comment("art_p021", "에코모빌리티 담당자", "최종본 내용으로 확정합니다. 후속 시놉시스 preview에서 ESG 메시지를 유지해주세요.")

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
