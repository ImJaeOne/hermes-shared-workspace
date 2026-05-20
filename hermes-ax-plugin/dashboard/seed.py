from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

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
        {"id": "s_lead", "template_id": "sales_pipeline_v1", "name": "Lead In", "slug": "lead-in", "stage_order": 0, "expected_artifacts": '["contact_info"]'},
        {"id": "s_qual", "template_id": "sales_pipeline_v1", "name": "Qualification", "slug": "qualification", "stage_order": 1, "expected_artifacts": '["email","meeting_notes"]'},
        {"id": "s_prop", "template_id": "sales_pipeline_v1", "name": "Proposal", "slug": "proposal", "stage_order": 2, "expected_artifacts": '["proposal","email"]', "transition_mode": "approval_required", "approval_roles": '["manager"]'},
        {"id": "s_nego", "template_id": "sales_pipeline_v1", "name": "Negotiation", "slug": "negotiation", "stage_order": 3, "expected_artifacts": '["contract","email"]'},
        {"id": "s_close", "template_id": "sales_pipeline_v1", "name": "Close", "slug": "close", "stage_order": 4, "expected_artifacts": '["contract","report"]', "transition_mode": "approval_required", "approval_roles": '["manager","director"]'},
        {"id": "mb_topic", "template_id": "mktg_blog", "name": "주제 선정", "slug": "topic", "stage_order": 0, "expected_artifacts": '["brief"]'},
        {"id": "mb_draft", "template_id": "mktg_blog", "name": "초안 작성", "slug": "draft", "stage_order": 1, "expected_artifacts": '["content_draft"]'},
        {"id": "mb_review", "template_id": "mktg_blog", "name": "리뷰", "slug": "review", "stage_order": 2, "expected_artifacts": '["content_draft"]', "transition_mode": "approval_required", "approval_roles": '["manager"]'},
        {"id": "mb_publish", "template_id": "mktg_blog", "name": "발행", "slug": "publish", "stage_order": 3, "expected_artifacts": '["report"]'},
        {"id": "mc_plan", "template_id": "mktg_cardnews", "name": "기획", "slug": "plan", "stage_order": 0, "expected_artifacts": '["brief"]'},
        {"id": "mc_design", "template_id": "mktg_cardnews", "name": "디자인", "slug": "design", "stage_order": 1, "expected_artifacts": '["content_draft"]'},
        {"id": "mc_copy", "template_id": "mktg_cardnews", "name": "카피 작성", "slug": "copy", "stage_order": 2, "expected_artifacts": '["content_draft"]'},
        {"id": "mc_approve", "template_id": "mktg_cardnews", "name": "승인", "slug": "approve", "stage_order": 3, "expected_artifacts": '["report"]', "transition_mode": "approval_required", "approval_roles": '["manager"]'},
        {"id": "mc_dist", "template_id": "mktg_cardnews", "name": "배포", "slug": "distribute", "stage_order": 4, "expected_artifacts": '["report"]'},
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
        transition_mode = s.get("transition_mode", "auto")
        approval_roles = s.get("approval_roles", "[]")
        conn.execute(
            "INSERT INTO stage_definitions (id, template_id, name, slug, stage_order, expected_artifacts, trigger_conditions, transition_mode, approval_roles, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (s["id"], s["template_id"], s["name"], s["slug"], s["stage_order"], s["expected_artifacts"], "{}", transition_mode, approval_roles, now),
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
    _ins_wf("wi_sales_002", "sales_pipeline_v1", "sales", "Beta Inc 스타트업 패키지", "s_lead", "active", 0, "이대리")
    _ins_art("art_s010", "wi_sales_002", "s_lead", "contact_info", "Beta Inc 연락처",
             json.dumps({"name": "최민수", "company": "Beta Inc", "email": "ms.choi@betainc.kr", "phone": "+82-10-9876-5432", "source": "웹사이트 문의"}, ensure_ascii=False),
             "application/json", "final")
    _ins_wf("wi_sales_003", "sales_pipeline_v1", "sales", "Gamma Ltd 글로벌 계약", "s_nego", "active", 2, "김영업")
    _ins_art("art_s020", "wi_sales_003", "s_nego", "contract", "계약서 초안 v2",
             "## 계약서 초안\n\n**계약 당사자**: Hermes Inc ↔ Gamma Ltd\n\n### 주요 조건\n- 계약 기간: 24개월\n- 총 계약 금액: $500,000\n- 지불 조건: 분기별 균등 분할\n- SLA: 99.9% 가용성 보장\n\n### 특이 사항\n- 아시아 태평양 지역 독점 조항 요청 중\n- 법무팀 검토 필요", "text/markdown", "draft")
    _ins_comment("art_s020", "김영업", "법무팀에 독점 조항 관련 검토 요청했습니다.")
    _ins_comment("art_s020", "박팀장", "독점 조항은 리스크가 있어요. 지역 제한 범위를 좁히는 방향으로 협의하세요.")
    _ins_wf("wi_sales_004", "sales_pipeline_v1", "sales", "Delta Corp 연간 계약", "s_close", "completed", 0, "이대리")
    _ins_wf("wi_mktg_001", "mktg_blog", "marketing", "Q3 제품 런칭 블로그 포스트", "mb_draft", "active", 1, "정마케터")
    _ins_art("art_m001", "wi_mktg_001", "mb_topic", "brief", "Q3 블로그 주제 기획",
             "## Q3 블로그 주제\n\n### 주제\nAI 워크플로우 자동화로 팀 생산성 높이기\n\n### 타겟 독자\n- B2B SaaS 의사결정자 (CTO, VP Eng)\n- IT/테크 산업 종사자\n\n### 핵심 메시지\n- 복잡한 워크플로우를 AI로 간소화\n- 실제 고객 사례로 효과 입증", "text/markdown", "final")
    _ins_comment("art_m001", "정마케터", "CMO 승인 완료. 초안 작성 착수합니다.")
    _ins_art("art_m002", "wi_mktg_001", "mb_draft", "content_draft", "블로그 초안",
             "## 혁신을 가속화하는 차세대 플랫폼\n\n### 헤드라인 A\n\"복잡한 워크플로우, 이제 AI가 알아서 처리합니다\"\n\n### 헤드라인 B\n\"팀 생산성 300% 향상 — 실제 고객 사례로 검증\"\n\n### 본문\n- 5분 만에 설정, 즉시 효과\n- 50+ 통합 지원\n- 엔터프라이즈급 보안\n\n### CTA\n\"무료 체험 시작하기\" / \"데모 신청\"", "text/markdown", "draft")
    _ins_comment("art_m002", "이디자이너", "헤드라인 B가 더 임팩트 있는 것 같아요. 숫자가 눈에 들어옵니다.")
    _ins_wf("wi_mktg_003", "mktg_blog", "marketing", "Q2 브랜드 인지도 블로그", "mb_publish", "completed", 0, "정마케터")
    _ins_art("art_m020", "wi_mktg_003", "mb_publish", "report", "Q2 블로그 성과 보고서",
             "## Q2 블로그 성과 요약\n\n### 주요 지표\n- 조회수: 85,000\n- 전환율: 2.8%\n- 공유: 420건\n\n### 인사이트\n- LinkedIn 공유가 가장 높은 유입 채널\n- 웨비나 참석자의 리드 전환율이 일반 대비 3배", "text/markdown", "final")
    _ins_comment("art_m020", "CMO", "좋은 결과네요. Q3에는 블로그 발행 빈도를 늘려보겠습니다.")
    _ins_wf("wi_mktg_002", "mktg_cardnews", "marketing", "5월 제품 업데이트 카드뉴스", "mc_copy", "active", 0, "정마케터")
    _ins_art("art_m010", "wi_mktg_002", "mc_plan", "brief", "5월 카드뉴스 기획",
             "## 5월 카드뉴스 기획\n\n### 주제\nHermes 5월 주요 업데이트 안내\n\n### 내용 요소\n1. AI 워크플로우 자동화 기능 출시\n2. 대시보드 플러그인 시스템 오픈\n3. 고객 사례: Beta Inc의 업무 효율 200% 향상기", "text/markdown", "final")
    _ins_art("art_m011", "wi_mktg_002", "mc_copy", "content_draft", "5월 카드뉴스 카피",
             "## Hermes 5월 업데이트\n\n**슬라이드 1**: AI 워크플로우 자동화 출시!\n**슬라이드 2**: 대시보드 플러그인으로 확장하세요\n**슬라이드 3**: Beta Inc 성공 사례\n**슬라이드 4**: 지금 무료 체험 시작하기", "text/markdown", "draft")
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
    _ins_wf("wi_sup_002", "support_pipeline_v1", "support", "SSO 로그인 실패 #4523", "t_triage", "active", 1, "한주니어")
    _ins_art("art_t010", "wi_sup_002", "t_created", "ticket", "SSO 로그인 티켓",
             json.dumps({"customer": "TechStart", "issue": "Google SSO 로그인 시 리다이렉트 무한루프", "severity": "high", "category": "auth", "reported_at": "2025-05-10T14:00:00Z"}, ensure_ascii=False),
             "application/json", "final")
    _ins_wf("wi_sup_003", "support_pipeline_v1", "support", "데이터 내보내기 오류 #4510", "t_follow", "completed", 0, "최엔지니어")
    _ins_art("art_t020", "wi_sup_003", "t_resolve", "resolution_note", "데이터 내보내기 수정 완료",
             "## 근본 원인\nCSV 내보내기 시 한글 인코딩(UTF-8 BOM) 누락으로 Excel에서 깨짐 발생\n\n## 적용 수정\n- CSV 생성 시 UTF-8 BOM 헤더 추가\n- 인코딩 옵션 선택 UI 추가 (UTF-8 / EUC-KR)\n\n## 검증\n- QA 테스트 통과\n- 고객 확인 완료", "text/markdown", "final")
    _ins_comment("art_t020", "최엔지니어", "v2.3.1 핫픽스로 배포 완료했습니다.")
    _ins_wf("wi_sup_004", "support_pipeline_v1", "support", "API 속도 저하 문의 #4525", "t_created", "active", 0, "")
