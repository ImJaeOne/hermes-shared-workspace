"""Quick integration test for plugin_api.py — runs without a live server."""
import hashlib
import hmac
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import time

# Ensure we use the dashboard package directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "dashboard"))

# Override HOME and bootstrap admin before plugin import so the temp DB is used
_tmp = tempfile.mkdtemp()
os.environ["HOME"] = _tmp
os.environ["HERMES_AX_BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["HERMES_AX_BOOTSTRAP_ADMIN_PASSWORD"] = "testpass123"
os.environ["HERMES_AX_BOOTSTRAP_ADMIN_DISPLAY_NAME"] = "테스트 관리자"
os.environ["HERMES_AX_SLACK_SIGNING_SECRET"] = "test-slack-signing-secret"
os.environ["HERMES_AX_SLACK_BOT_USER_ID"] = "UBOTLEAD"
os.environ["HERMES_AX_SLACK_DRY_RUN"] = "true"

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.patch_hermes_dashboard_public_api import (
    SLACK_EVENTS_PUBLIC_PATH,
    patch_public_api_allowlist_text,
)

import db_schema
import plugin_api
import slack_onboarding_api
importlib.reload(plugin_api)

app = FastAPI()
app.include_router(plugin_api.router)
client = TestClient(app)
anon = TestClient(app)
PARENT_GATE_HEADERS = {"X-Hermes-Session-Token": "parent-dashboard-token"}
client.headers.update(PARENT_GATE_HEADERS)

passed = 0
failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label} — {detail}")


def fetch_worker_request(conn, workflow_id: str, request_type: str, latest: bool = True):
    try:
        order = "DESC" if latest else "ASC"
        return conn.execute(
            f"""SELECT * FROM planning_worker_requests
               WHERE workflow_id=? AND request_type=?
               ORDER BY created_at {order}, id {order} LIMIT 1""",
            (workflow_id, request_type),
        ).fetchone()
    except sqlite3.OperationalError:
        return None


def slack_headers(payload: dict, signing_key: str = "test-slack-signing-secret") -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ts = str(int(time.time()))
    base = b"v0:" + ts.encode("ascii") + b":" + body
    signature = "v0=" + hmac.new(signing_key.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": signature,
    }


def slack_event_payload(event_id: str = "EvONBOARD1", channel_id: str = "CLOCALTEST", channel_name: str = "테스트전자") -> dict:
    return {
        "type": "event_callback",
        "team_id": "TLOCAL",
        "api_app_id": "AAXLOCAL",
        "event_id": event_id,
        "event_time": int(time.time()),
        "event": {
            "type": "channel_joined",
            "channel": {
                "id": channel_id,
                "name": channel_name,
            },
        },
    }


def slack_member_joined_payload(event_id: str, user_id: str, channel_id: str, channel_name: str) -> dict:
    return {
        "type": "event_callback",
        "team_id": "TLOCAL",
        "api_app_id": "AAXLOCAL",
        "event_id": event_id,
        "event_time": int(time.time()),
        "event": {
            "type": "member_joined_channel",
            "user": user_id,
            "channel": channel_id,
            "channel_name": channel_name,
        },
    }


def slack_message_files_payload(event_id: str, channel_id: str = "CLOCALTEST") -> dict:
    return {
        "type": "event_callback",
        "team_id": "TLOCAL",
        "api_app_id": "AAXLOCAL",
        "event_id": event_id,
        "event_time": int(time.time()),
        "event": {
            "type": "message",
            "channel": channel_id,
            "user": "UCLIENT1",
            "ts": "1710000000.000200",
            "text": "자료 첨부드립니다.",
            "files": [
                {
                    "id": "FINTROPDF",
                    "name": "intro.pdf",
                    "title": "회사 소개서",
                    "mimetype": "application/pdf",
                    "size": 29,
                    "url_private": "https://slack.example/files/FINTROPDF",
                    "url_private_download": "https://slack.example/files/FINTROPDF/download",
                    "user": "UCLIENT1",
                    "created": 1710000000,
                    "content": "%PDF-1.4 test source material",
                },
                {
                    "id": "FNOTESMD",
                    "name": "notes.md",
                    "title": "담당자 메모",
                    "mimetype": "text/markdown",
                    "size": 22,
                    "url_private": "https://slack.example/files/FNOTESMD",
                    "user": "UCLIENT2",
                    "timestamp": 1710000001,
                    "content_text": "# 메모\n- 핵심 자료입니다.",
                },
                {
                    "id": "FARCHIVEZIP",
                    "name": "archive.zip",
                    "title": "압축 파일",
                    "mimetype": "application/zip",
                    "size": 1024,
                    "url_private": "https://slack.example/files/FARCHIVEZIP",
                    "user": "UCLIENT3",
                    "created": 1710000002,
                },
                {
                    "id": "FHUGEPDF",
                    "name": "huge.pdf",
                    "title": "대용량 회사 소개서",
                    "mimetype": "application/pdf",
                    "size": 30 * 1024 * 1024,
                    "url_private": "https://slack.example/files/FHUGEPDF",
                    "user": "UCLIENT4",
                    "created": 1710000003,
                    "content": "%PDF-1.4 oversized test source material",
                },
            ],
        },
    }


def slack_message_text_payload(event_id: str, text: str, channel_id: str = "CLOCALTEST") -> dict:
    return {
        "type": "event_callback",
        "team_id": "TLOCAL",
        "api_app_id": "AAXLOCAL",
        "event_id": event_id,
        "event_time": int(time.time()),
        "event": {
            "type": "message",
            "channel": channel_id,
            "user": "UCLIENT1",
            "ts": "1710000000.000300",
            "text": text,
        },
    }


def slack_message_single_file_payload(
    event_id: str,
    *,
    channel_id: str = "CLOCALTEST",
    file_id: str = "FREVISIONDOC",
    filename: str = "revision-notes.md",
    title: str = "수정 요청 메모",
    text: str = "수정 요청 파일 첨부드립니다.",
    content_text: str = "# 수정 요청\n- 시장 규모와 경쟁사 비교를 보강해주세요.",
) -> dict:
    return {
        "type": "event_callback",
        "team_id": "TLOCAL",
        "api_app_id": "AAXLOCAL",
        "event_id": event_id,
        "event_time": int(time.time()),
        "event": {
            "type": "message",
            "channel": channel_id,
            "user": "UCLIENT1",
            "ts": "1710000000.000400",
            "text": text,
            "files": [
                {
                    "id": file_id,
                    "name": filename,
                    "title": title,
                    "mimetype": "text/markdown",
                    "size": len(content_text.encode("utf-8")),
                    "url_private": f"https://slack.example/files/{file_id}",
                    "user": "UCLIENT1",
                    "created": 1710000004,
                    "content_text": content_text,
                }
            ],
        },
    }


def check_parent_session():
    r = client.get("/auth/session")
    check("GET /auth/session status", r.status_code == 200, f"got {r.status_code}: {r.text}")
    data = r.json()
    user = data.get("user") or {}
    check("parent session authenticated", data.get("authenticated") is True, str(data))
    check("parent session user", user.get("username") == "parent-dashboard", str(data))
    check("parent session has no AX expiry", data.get("expires_at") is None, str(data))
    return data


print("\n=== Auth ===")
r = anon.post("/workflows", json={
    "template_id": "planning_research_mvp_v1",
    "title": "Unauthorized Workflow",
})
check("write without parent token blocked", r.status_code == 401, f"got {r.status_code}")
check_parent_session()
r = client.post("/auth/login", json={"username": "admin", "password": "testpass123"})
check("AX login endpoint disabled", r.status_code == 410, f"got {r.status_code}: {r.text}")

print("\n=== Docker Dashboard Public API Patch ===")
web_server_allowlist_sample = '''_PUBLIC_API_PATHS: frozenset = frozenset({
    "/api/status",
    "/api/dashboard/plugins",
})
'''
patched_allowlist = patch_public_api_allowlist_text(web_server_allowlist_sample)
check("Slack events path added to dashboard public allowlist", SLACK_EVENTS_PUBLIC_PATH in patched_allowlist, patched_allowlist)
check("Slack events path added once", patched_allowlist.count(SLACK_EVENTS_PUBLIC_PATH) == 1, patched_allowlist)
check("dashboard public allowlist patch idempotent", patch_public_api_allowlist_text(patched_allowlist) == patched_allowlist)
web_server_allowlist_with_extra_path = '''_PUBLIC_API_PATHS: frozenset = frozenset({
    "/api/status",
    "/api/dashboard/plugins",
    "/api/dashboard/health",
})
'''
try:
    patched_extra_path_allowlist = patch_public_api_allowlist_text(web_server_allowlist_with_extra_path)
except RuntimeError as exc:
    patched_extra_path_allowlist = str(exc)
check(
    "dashboard public allowlist patch tolerates additional public paths",
    SLACK_EVENTS_PUBLIC_PATH in patched_extra_path_allowlist,
    patched_extra_path_allowlist,
)
try:
    patch_public_api_allowlist_text('_PUBLIC_API_PATHS: frozenset = frozenset({"/api/status"})')
except RuntimeError:
    missing_anchor_failed = True
else:
    missing_anchor_failed = False
check("dashboard public allowlist patch fails fast when allowlist block changes", missing_anchor_failed)

print("\n=== Agents ===")
r = client.get("/agents")
check("GET /agents status", r.status_code == 200)
agents = r.json()
check("2 agent types seeded", len(agents) == 2, f"got {len(agents)}")
check("planning agent exists", any(a["id"] == "planning" for a in agents))
check("design agent exists", any(a["id"] == "design" for a in agents))
check("each agent has templates", all(len(a.get("templates", [])) > 0 for a in agents))

planning = client.get("/agents/planning")
check("GET /agents/planning status", planning.status_code == 200)
planning_detail = planning.json()
check("planning has 6 stages", len(planning_detail.get("stages", [])) == 6, f"got {len(planning_detail.get('stages', []))}")

print("\n=== Slack Channel Onboarding ===")
challenge_payload = {"type": "url_verification", "challenge": "challenge-token"}
body, headers = slack_headers(challenge_payload)
r = anon.post("/slack/events", content=body, headers=headers)
check("Slack url_verification status", r.status_code == 200, f"got {r.status_code}: {r.text}")
check("Slack url_verification challenge", r.json().get("challenge") == "challenge-token", str(r.text))

bad_body, bad_headers = slack_headers(slack_event_payload(event_id="EvBAD"), signing_key="wrong-value")
r = anon.post("/slack/events", content=bad_body, headers=bad_headers)
check("Slack invalid signature rejected", r.status_code == 401, f"got {r.status_code}: {r.text}")

saved_bot_user_id = os.environ.pop("HERMES_AX_SLACK_BOT_USER_ID")
member_payload = slack_member_joined_payload("EvMEMBERNOID", "UORDINARY", "CMEMBERNOID", "일반참여")
member_body, member_headers = slack_headers(member_payload)
r = anon.post("/slack/events", content=member_body, headers=member_headers)
check("Slack member_joined without bot id ignored", r.status_code == 200 and r.json().get("reason") == "bot_user_id_required", f"got {r.status_code}: {r.text}")
with plugin_api.get_db() as conn:
    member_count = conn.execute("SELECT count(*) FROM workflow_instances WHERE title=?", ("[일반참여] 기획 자료조사",)).fetchone()[0]
    check("Slack member_joined without bot id creates no workflow", member_count == 0, f"got {member_count}")
os.environ["HERMES_AX_SLACK_BOT_USER_ID"] = saved_bot_user_id

payload = slack_event_payload()
body, headers = slack_headers(payload)
r = anon.post("/slack/events", content=body, headers=headers)
check("Slack onboarding event status", r.status_code == 200, f"got {r.status_code}: {r.text}")
slack_result = r.json()
expected_message = "테스트전자에 대한 기획 작업을 시작하겠습니다. 기획하기 앞서 테스트전자에 대한 자료가 있으시면 첨부해주세요."
check("Slack onboarding ok", slack_result.get("ok") is True, str(slack_result))
check("Slack company name extracted", slack_result.get("company_name") == "테스트전자", str(slack_result))
check("Slack onboarding message generated", slack_result.get("onboarding_message") == expected_message, str(slack_result))
check("Slack dry-run message treated as sent", slack_result.get("message_sent") is True, str(slack_result))
slack_wf_id = slack_result.get("workflow_id")
check("Slack workflow id returned", isinstance(slack_wf_id, str) and slack_wf_id.startswith("wi_"), str(slack_result))

slack_mapping_id = ""
with plugin_api.get_db() as conn:
    mapping = conn.execute("SELECT * FROM slack_channel_project_mappings WHERE team_id=? AND channel_id=?", ("TLOCAL", "CLOCALTEST")).fetchone()
    check("Slack channel mapping row exists", mapping is not None)
    if mapping:
        slack_mapping_id = mapping["id"]
        check("Slack mapping stores company", mapping["company_name"] == "테스트전자", dict(mapping))
        check("Slack mapping stores workflow", mapping["workflow_id"] == slack_wf_id, dict(mapping))
        check("Slack mapping marks message sent", bool(mapping["onboarding_message_sent_at"]), dict(mapping))
    wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (slack_wf_id,)).fetchone()
    check("Slack workflow exists", wf is not None)
    if wf:
        metadata = json.loads(wf["metadata_json"])
        check("Slack workflow title", wf["title"] == "[테스트전자] 기획 자료조사", dict(wf))
        check("Slack workflow initial stage", wf["current_stage_id"] == "p_material_requesting", dict(wf))
        check("Slack workflow assignee", wf["assignee"] == "기획팀 임팀장", dict(wf))
        check("Slack workflow metadata project key", metadata.get("project_key") == "planning-research:테스트전자", metadata)
        check("Slack workflow metadata channel", metadata.get("slack", {}).get("channel_id") == "CLOCALTEST", metadata)
    receipt = conn.execute("SELECT * FROM slack_event_receipts WHERE event_id=?", ("EvONBOARD1",)).fetchone()
    check("Slack event receipt recorded", receipt is not None)
    if receipt:
        check("Slack event receipt succeeded", receipt["status"] == "succeeded", dict(receipt))
    activity = conn.execute("SELECT * FROM activity_logs WHERE workflow_id=? AND action=?", (slack_wf_id, "slack.channel_onboarded")).fetchone()
    check("Slack onboarding activity exists", activity is not None)

message_payload = slack_message_files_payload("EvFILES1")
message_body, message_headers = slack_headers(message_payload)
r = anon.post("/slack/events", content=message_body, headers=message_headers)
check("Slack message files event status", r.status_code == 200, f"got {r.status_code}: {r.text}")
files_result = r.json()
check("Slack message files response ok", files_result.get("ok") is True, str(files_result))
check("Slack message files stores supported files", files_result.get("stored_count") == 2, str(files_result))
check("Slack message files rejects unsupported or oversized files", files_result.get("rejected_count") == 2, str(files_result))
confirmation_message = files_result.get("message", "")
check("Slack material confirmation message text", "첨부된 자료는 다음과 같습니다" in confirmation_message and "추가 자료는 없으십니까?" in confirmation_message, str(files_result))
check("Slack material confirmation includes supported format guide", "지원 형식" in confirmation_message and "pdf" in confirmation_message.lower() and "docx" in confirmation_message.lower() and "pptx" in confirmation_message.lower() and "xlsx" in confirmation_message.lower(), confirmation_message)
check("Slack material confirmation includes file limits", "최대 10개" in confirmation_message and "25MB" in confirmation_message, confirmation_message)
check("Slack material confirmation dry-run sent", files_result.get("message_sent") is True, str(files_result))

with plugin_api.get_db() as conn:
    source_rows = conn.execute("SELECT * FROM slack_workflow_source_files WHERE workflow_id=? ORDER BY created_at, id", (slack_wf_id,)).fetchall()
    check("Slack source file rows include all files", len(source_rows) == 4, [dict(r) for r in source_rows])
    accepted_rows = [r for r in source_rows if r["status"] == "stored"]
    rejected_rows = [r for r in source_rows if r["status"] == "rejected"]
    check("Slack accepted source files preserved", sorted(r["filename"] for r in accepted_rows) == ["intro.pdf", "notes.md"], [dict(r) for r in accepted_rows])
    rejection_reasons = {r["filename"]: r["rejection_reason"] for r in rejected_rows}
    check("Slack rejected source file reason preserved", len(rejected_rows) == 2 and "archive.zip" in rejection_reasons and "huge.pdf" in rejection_reasons and "file_too_large" in rejection_reasons.get("huge.pdf", ""), [dict(r) for r in rejected_rows])
    intro_row = next((r for r in accepted_rows if r["filename"] == "intro.pdf"), None)
    check("Slack source file metadata preserved", intro_row is not None and intro_row["slack_file_id"] == "FINTROPDF" and intro_row["uploaded_user"] == "UCLIENT1" and intro_row["url_private_download"].endswith("/download"), [dict(r) for r in accepted_rows])
    check("Slack source files linked to artifacts", len({r["artifact_id"] for r in accepted_rows if r["artifact_id"]}) == 2, [dict(r) for r in accepted_rows])
    artifacts = conn.execute("SELECT id, artifact_type, original_filename, is_latest FROM artifacts WHERE workflow_id=? AND artifact_type='source_material' ORDER BY created_at", (slack_wf_id,)).fetchall()
    check("Slack source file artifacts not hidden by latest policy", len(artifacts) == 2 and all(r["is_latest"] == 1 for r in artifacts), [dict(r) for r in artifacts])
    wf_after_files = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (slack_wf_id,)).fetchone()
    check("Slack workflow moved to material waiting", wf_after_files["current_stage_id"] == "p_material_waiting", dict(wf_after_files))
    material_state = conn.execute("SELECT * FROM slack_material_collection_states WHERE workflow_id=?", (slack_wf_id,)).fetchone()
    check("Slack material collection state stored", material_state is not None and material_state["status"] == "pending_confirmation" and material_state["source_file_count"] == 2 and material_state["rejected_file_count"] == 2, dict(material_state) if material_state else "")

r = client.get(f"/workflows/{slack_wf_id}")
check("Workflow detail includes Slack source files status", r.status_code == 200, f"got {r.status_code}: {r.text}")
slack_detail = r.json()
check("Workflow detail source files returned", len(slack_detail.get("source_files", [])) == 4, slack_detail.get("source_files"))
check("Workflow detail material collection state returned", slack_detail.get("material_collection_state", {}).get("source_file_count") == 2 and slack_detail.get("material_collection_state", {}).get("rejected_file_count") == 2, slack_detail.get("material_collection_state"))
check("Workflow detail source files preserve statuses", sorted({f.get("status") for f in slack_detail.get("source_files", [])}) == ["rejected", "stored"], slack_detail.get("source_files"))

more_payload = slack_message_text_payload("EvMORE1", "아니요, 추가 자료가 있습니다.")
more_body, more_headers = slack_headers(more_payload)
r = anon.post("/slack/events", content=more_body, headers=more_headers)
check("Slack material more-needed response status", r.status_code == 200, f"got {r.status_code}: {r.text}")
more_result = r.json()
check("Slack material more-needed status stored", more_result.get("material_status") == "awaiting_more_materials", str(more_result))
check("Slack material more-needed asks for upload", "추가 자료" in more_result.get("message", "") and "첨부" in more_result.get("message", ""), str(more_result))
with plugin_api.get_db() as conn:
    material_state = conn.execute("SELECT * FROM slack_material_collection_states WHERE workflow_id=?", (slack_wf_id,)).fetchone()
    wf_waiting_more = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (slack_wf_id,)).fetchone()
    check("Slack material more-needed state persisted", material_state is not None and material_state["status"] == "awaiting_more_materials", dict(material_state) if material_state else "")
    check("Slack material more-needed keeps workflow waiting", wf_waiting_more["current_stage_id"] == "p_material_waiting" and wf_waiting_more["assignee"] == "기획팀 임팀장", dict(wf_waiting_more))

confirm_payload = slack_message_text_payload("EvCONFIRM1", "네, 없습니다. 자료조사 worker에게 전달해주세요.")
confirm_body, confirm_headers = slack_headers(confirm_payload)
r = anon.post("/slack/events", content=confirm_body, headers=confirm_headers)
check("Slack material confirmation reply status", r.status_code == 200, f"got {r.status_code}: {r.text}")
confirm_result = r.json()
check("Slack material confirmation reply stored", confirm_result.get("material_status") == "confirmed", str(confirm_result))
check("Slack material confirmation starts worker", "자료조사 worker" in confirm_result.get("message", "") and confirm_result.get("current_stage_id") == "p_research_running", str(confirm_result))
with plugin_api.get_db() as conn:
    confirmed_state = conn.execute("SELECT * FROM slack_material_collection_states WHERE workflow_id=?", (slack_wf_id,)).fetchone()
    wf_research = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (slack_wf_id,)).fetchone()
    research_transition = conn.execute("SELECT * FROM stage_transitions WHERE workflow_id=? AND to_stage_id='p_research_running'", (slack_wf_id,)).fetchone()
    confirm_activity = conn.execute("SELECT * FROM activity_logs WHERE workflow_id=? AND action=?", (slack_wf_id, "slack.material_collection_confirmed")).fetchone()
    check("Slack material confirmation state persisted", confirmed_state is not None and confirmed_state["status"] == "confirmed", dict(confirmed_state) if confirmed_state else "")
    check("Slack material confirmation moves workflow to research", wf_research["current_stage_id"] == "p_research_running" and wf_research["assignee"] == "기획팀 임사원", dict(wf_research))
    check("Slack material confirmation transition logged", research_transition is not None and research_transition["triggered_by"] == "slack", dict(research_transition) if research_transition else "")
    check("Slack material confirmation activity logged", confirm_activity is not None, dict(confirm_activity) if confirm_activity else "")
    research_request = fetch_worker_request(conn, slack_wf_id, "research", latest=False)
    if research_request:
        research_payload = json.loads(research_request["payload_json"])
    else:
        research_payload = {}
    check("Slack material confirmation creates worker request", research_request is not None and research_request["status"] == "queued", dict(research_request) if research_request else "")
    check("Worker research payload is standardized", research_payload.get("schema_version") == 1 and research_payload.get("task_type") == "initial_research" and research_payload.get("workflow_id") == slack_wf_id and research_payload.get("stage_id") == "p_research_running", research_payload)
    check("Worker research payload includes Slack and source files", research_payload.get("slack", {}).get("channel_id") == "CLOCALTEST" and len(research_payload.get("source_files", [])) == 2, research_payload)

research_request_id = research_request["id"] if research_request else "missing-research-request"
r = client.post("/worker/results", json={
    "request_id": research_request_id,
    "workflow_id": slack_wf_id,
    "status": "succeeded",
    "title": "테스트전자 자료조사 결과",
    "content": "## 테스트전자 자료조사 결과\n\n- 핵심 요약\n- 시장/고객 맥락\n- 콘텐츠 기획 포인트",
})
check("Worker result receipt status", r.status_code == 200, f"got {r.status_code}: {r.text}")
worker_result = r.json()
check("Worker result receipt returns artifact", worker_result.get("artifact_id", "").startswith("art_"), str(worker_result))
check("Worker result posts Slack review message", worker_result.get("message_sent") is True and "자료조사 결과" in worker_result.get("message", "") and "검토" in worker_result.get("message", ""), str(worker_result))
check("Worker result moves workflow to review", worker_result.get("current_stage_id") == "p_user_review_waiting", str(worker_result))
with plugin_api.get_db() as conn:
    report_artifact = conn.execute("SELECT * FROM artifacts WHERE workflow_id=? AND artifact_type='research_report' AND stage_id='p_user_review_waiting' ORDER BY created_at DESC LIMIT 1", (slack_wf_id,)).fetchone()
    wf_review = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (slack_wf_id,)).fetchone()
    result_activity = conn.execute("SELECT * FROM activity_logs WHERE workflow_id=? AND action=?", (slack_wf_id, "slack.worker_result_received")).fetchone()
    check("Worker result creates research report artifact", report_artifact is not None and "테스트전자 자료조사 결과" in report_artifact["title"], dict(report_artifact) if report_artifact else "")
    check("Worker result review state persisted", wf_review["current_stage_id"] == "p_user_review_waiting" and wf_review["assignee"] == "기획팀 임팀장", dict(wf_review))
    check("Worker result activity logged", result_activity is not None, dict(result_activity) if result_activity else "")

review_confirm_payload = slack_message_text_payload("EvREVIEWCONFIRM1", "확정", channel_id="CLOCALTEST")
review_confirm_body, review_confirm_headers = slack_headers(review_confirm_payload)
r = anon.post("/slack/events", content=review_confirm_body, headers=review_confirm_headers)
check("Slack review positive reply status", r.status_code == 200, f"got {r.status_code}: {r.text}")
review_confirm_result = r.json()
check("Slack review positive confirms research", review_confirm_result.get("review_status") == "confirmed" and review_confirm_result.get("current_stage_id") == "p_research_confirmed", str(review_confirm_result))
with plugin_api.get_db() as conn:
    wf_confirmed = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (slack_wf_id,)).fetchone()
    confirm_review_activity = conn.execute("SELECT * FROM activity_logs WHERE workflow_id=? AND action=?", (slack_wf_id, "slack.research_confirmed")).fetchone()
    check("Slack review confirmation workflow completed", wf_confirmed["current_stage_id"] == "p_research_confirmed" and wf_confirmed["status"] == "completed", dict(wf_confirmed))
    check("Slack review confirmation activity logged", confirm_review_activity is not None, dict(confirm_review_activity) if confirm_review_activity else "")

revision_onboard_payload = slack_event_payload(event_id="EvREVONBOARD1", channel_id="CREVTEST", channel_name="수정테스트")
revision_onboard_body, revision_onboard_headers = slack_headers(revision_onboard_payload)
r = anon.post("/slack/events", content=revision_onboard_body, headers=revision_onboard_headers)
check("Revision workflow onboarding status", r.status_code == 200, f"got {r.status_code}: {r.text}")
revision_wf_id = r.json().get("workflow_id")
revision_files_payload = slack_message_files_payload("EvREVFILES1", channel_id="CREVTEST")
revision_files_body, revision_files_headers = slack_headers(revision_files_payload)
r = anon.post("/slack/events", content=revision_files_body, headers=revision_files_headers)
check("Revision workflow files status", r.status_code == 200, f"got {r.status_code}: {r.text}")
revision_confirm_payload = slack_message_text_payload("EvREVCONFIRM1", "ㅇㅋ 진행해", channel_id="CREVTEST")
revision_confirm_body, revision_confirm_headers = slack_headers(revision_confirm_payload)
r = anon.post("/slack/events", content=revision_confirm_body, headers=revision_confirm_headers)
check("Revision workflow material positive shorthand status", r.status_code == 200, f"got {r.status_code}: {r.text}")
check("Revision workflow material positive shorthand starts worker", r.json().get("current_stage_id") == "p_research_running", str(r.json()))
with plugin_api.get_db() as conn:
    revision_initial_request = fetch_worker_request(conn, revision_wf_id, "research", latest=False)
revision_initial_request_id = revision_initial_request["id"] if revision_initial_request else "missing-revision-initial-request"
r = client.post("/worker/results", json={
    "request_id": revision_initial_request_id,
    "workflow_id": revision_wf_id,
    "status": "succeeded",
    "title": "수정테스트 자료조사 결과",
    "content": "## 수정테스트 자료조사 결과\n\n초안입니다.",
})
check("Revision workflow initial worker result status", r.status_code == 200, f"got {r.status_code}: {r.text}")
revision_text_payload = slack_message_text_payload("EvREVISIONTEXT1", "시장 규모와 경쟁사 비교를 더 보강해주세요.", channel_id="CREVTEST")
revision_text_body, revision_text_headers = slack_headers(revision_text_payload)
r = anon.post("/slack/events", content=revision_text_body, headers=revision_text_headers)
check("Slack review revision text status", r.status_code == 200, f"got {r.status_code}: {r.text}")
revision_text_result = r.json()
check("Slack review free-text creates revision request", revision_text_result.get("review_status") == "revision_requested" and revision_text_result.get("current_stage_id") == "p_revision_running", str(revision_text_result))
with plugin_api.get_db() as conn:
    revision_request = fetch_worker_request(conn, revision_wf_id, "revision")
    revision_payload = json.loads(revision_request["payload_json"]) if revision_request else {}
    revision_activity = conn.execute("SELECT * FROM activity_logs WHERE workflow_id=? AND action=?", (revision_wf_id, "slack.revision_requested")).fetchone()
    check("Revision text worker request payload stored", revision_request is not None and revision_payload.get("task_type") == "revision" and "시장 규모" in revision_payload.get("revision", {}).get("instruction", ""), revision_payload)
    check("Revision text activity logged", revision_activity is not None, dict(revision_activity) if revision_activity else "")
revision_request_id = revision_request["id"] if revision_request else "missing-revision-request"
r = client.post("/worker/results", json={
    "request_id": revision_request_id,
    "workflow_id": revision_wf_id,
    "status": "succeeded",
    "title": "수정테스트 자료조사 수정본",
    "content": "## 수정테스트 자료조사 수정본\n\n시장 규모와 경쟁사 비교를 보강했습니다.",
})
check("Revision worker result returns to review", r.status_code == 200 and r.json().get("current_stage_id") == "p_user_review_waiting", f"got {r.status_code}: {r.text}")
revision_file_payload = slack_message_single_file_payload("EvREVISIONFILE1", channel_id="CREVTEST", file_id="FREVISIONDOC")
revision_file_body, revision_file_headers = slack_headers(revision_file_payload)
r = anon.post("/slack/events", content=revision_file_body, headers=revision_file_headers)
check("Slack review attached revision file status", r.status_code == 200, f"got {r.status_code}: {r.text}")
revision_file_result = r.json()
check("Slack review attached file creates revision request", revision_file_result.get("review_status") == "revision_requested" and revision_file_result.get("current_stage_id") == "p_revision_running", str(revision_file_result))
with plugin_api.get_db() as conn:
    revision_file_request = fetch_worker_request(conn, revision_wf_id, "revision")
    revision_file_payload_json = json.loads(revision_file_request["payload_json"]) if revision_file_request else {}
    check("Revision file worker payload includes attachment", any(f.get("filename") == "revision-notes.md" for f in revision_file_payload_json.get("revision", {}).get("attachments", [])), revision_file_payload_json)
revision_file_request_id = revision_file_request["id"] if revision_file_request else "missing-revision-file-request"
r = client.post("/worker/results", json={
    "request_id": revision_file_request_id,
    "workflow_id": revision_wf_id,
    "status": "failed",
    "error": "worker timeout",
})
check("Worker failure receipt status", r.status_code == 200, f"got {r.status_code}: {r.text}")
worker_failure = r.json()
check("Worker failure sends understandable Slack message", worker_failure.get("ok") is True and worker_failure.get("message_sent") is True and "오류" in worker_failure.get("message", ""), str(worker_failure))
with plugin_api.get_db() as conn:
    failed_request = conn.execute("SELECT * FROM planning_worker_requests WHERE id=?", (revision_file_request_id,)).fetchone()
    failure_activity = conn.execute("SELECT * FROM activity_logs WHERE workflow_id=? AND action=?", (revision_wf_id, "slack.worker_result_failed")).fetchone()
    check("Worker failure request marked failed", failed_request is not None and failed_request["status"] == "failed", dict(failed_request) if failed_request else "")
    check("Worker failure activity logged", failure_activity is not None, dict(failure_activity) if failure_activity else "")

r = anon.post("/slack/events", content=body, headers=headers)
check("Slack duplicate event status", r.status_code == 200, f"got {r.status_code}: {r.text}")
duplicate_result = r.json()
check("Slack duplicate reuses workflow", duplicate_result.get("workflow_id") == slack_wf_id, str(duplicate_result))
check("Slack duplicate marked idempotent", duplicate_result.get("duplicate") is True, str(duplicate_result))
with plugin_api.get_db() as conn:
    duplicate_count = conn.execute("SELECT count(*) FROM workflow_instances WHERE title=?", ("[테스트전자] 기획 자료조사",)).fetchone()[0]
    check("Slack duplicate did not create workflow", duplicate_count == 1, f"got {duplicate_count}")

payload2 = slack_event_payload(event_id="EvONBOARD2")
body2, headers2 = slack_headers(payload2)
r = anon.post("/slack/events", content=body2, headers=headers2)
check("Slack same channel new event status", r.status_code == 200, f"got {r.status_code}: {r.text}")
reuse_result = r.json()
check("Slack same channel reuses workflow", reuse_result.get("workflow_id") == slack_wf_id, str(reuse_result))
check("Slack same channel does not resend message", reuse_result.get("message_sent") is False and reuse_result.get("message_skipped_reason") == "already_sent", str(reuse_result))

saved_dry_run = os.environ.get("HERMES_AX_SLACK_DRY_RUN")
saved_ax_bot_token = os.environ.pop("HERMES_AX_SLACK_BOT_TOKEN", None)
saved_slack_bot_token = os.environ.pop("SLACK_BOT_TOKEN", None)
os.environ["HERMES_AX_SLACK_DRY_RUN"] = "false"
fail_payload = slack_event_payload(event_id="EvNOSEND", channel_id="CNOSEND", channel_name="토큰없음")
fail_body, fail_headers = slack_headers(fail_payload)
r = anon.post("/slack/events", content=fail_body, headers=fail_headers)
check("Slack missing token event status", r.status_code == 200, f"got {r.status_code}: {r.text}")
fail_result = r.json()
check("Slack missing token marks response failed", fail_result.get("ok") is False and fail_result.get("message_skipped_reason") == "missing_bot_token", str(fail_result))
with plugin_api.get_db() as conn:
    failed_receipt = conn.execute("SELECT * FROM slack_event_receipts WHERE event_id=?", ("EvNOSEND",)).fetchone()
    check("Slack missing token receipt failed", failed_receipt is not None and failed_receipt["status"] == "failed", dict(failed_receipt) if failed_receipt else "")
os.environ["HERMES_AX_SLACK_DRY_RUN"] = "true"
r = anon.post("/slack/events", content=fail_body, headers=fail_headers)
retry_result = r.json()
check("Slack failed receipt can be retried", r.status_code == 200 and retry_result.get("message_sent") is True, f"got {r.status_code}: {r.text}")
with plugin_api.get_db() as conn:
    retried_receipt = conn.execute("SELECT * FROM slack_event_receipts WHERE event_id=?", ("EvNOSEND",)).fetchone()
    check("Slack retried receipt succeeds", retried_receipt is not None and retried_receipt["status"] == "succeeded", dict(retried_receipt) if retried_receipt else "")
if saved_dry_run is not None:
    os.environ["HERMES_AX_SLACK_DRY_RUN"] = saved_dry_run
if saved_ax_bot_token is not None:
    os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = saved_ax_bot_token
if saved_slack_bot_token is not None:
    os.environ["SLACK_BOT_TOKEN"] = saved_slack_bot_token

design = client.get("/agents/design")
check("GET /agents/design status", design.status_code == 200)
design_detail = design.json()
check("design has 4 stages", len(design_detail.get("stages", [])) == 4, f"got {len(design_detail.get('stages', []))}")

print("\n=== Board / Stats ===")
r = client.get("/board/planning")
check("GET /board/planning status", r.status_code == 200)
board = r.json()
check("planning board has 6 columns", len(board["columns"]) == 6, f"got {len(board['columns'])}")

r = client.get("/board/design")
check("GET /board/design status", r.status_code == 200)
design_board = r.json()
check("design board has 4 columns", len(design_board["columns"]) == 4, f"got {len(design_board['columns'])}")

r = client.get("/stats")
check("GET /stats status", r.status_code == 200)
stats = r.json()
check("stats has by_agent", isinstance(stats.get("by_agent"), dict), str(stats))
check("stats includes planning", "planning" in stats.get("by_agent", {}), str(stats.get("by_agent")))
check("stats includes design", "design" in stats.get("by_agent", {}), str(stats.get("by_agent")))

print("\n=== Create Workflow ===")
r = client.post("/workflows", json={
    "template_id": "planning_research_mvp_v1",
    "title": "[테스트전자] 기획 자료조사",
    "priority": 1,
    "assignee": "기획팀 임팀장",
})
check("POST /workflows status", r.status_code == 200, f"got {r.status_code}: {r.text}")
wf = r.json()
wf_id = wf["id"]
check("workflow id returned", wf_id.startswith("wi_"), f"got {wf_id}")
check("initial stage is p_material_requesting", wf["current_stage_id"] == "p_material_requesting")

print("\n=== Workflow Detail / Activity Logs ===")
r = client.get(f"/workflows/{wf_id}")
check("GET /workflows/:id status", r.status_code == 200)
detail = r.json()
check("6 stages with status", len(detail["stages"]) == 6)
check("first stage is current", detail["stages"][0]["is_current"] is True)
check("1 initial transition", len(detail["transitions"]) == 1)
check("activity logs returned", len(detail.get("activity_logs", [])) >= 1, str(detail.get("activity_logs")))
create_log = next((log for log in detail.get("activity_logs", []) if log.get("action") == "workflow.create"), None)
check("workflow.create activity exists", create_log is not None, str(detail.get("activity_logs")))
if create_log:
    check("workflow.create actor is human", create_log.get("actor_kind") == "human", str(create_log))
    check("workflow.create actor label matches", create_log.get("actor_label") == "Hermes Dashboard", str(create_log))

print("\n=== Transition ===")
r = client.post(f"/workflows/{wf_id}/transition", json={
    "to_stage_id": "p_material_waiting",
    "triggered_by": "ignored-by-server",
    "note": "자료 첨부 확인",
})
check("POST transition status", r.status_code == 200, f"got {r.status_code}: {r.text}")
r = client.get(f"/workflows/{wf_id}")
detail = r.json()
check("current stage now p_material_waiting", detail["current_stage_id"] == "p_material_waiting")
check("2 transitions", len(detail["transitions"]) == 2)
transition_log = next((log for log in detail.get("activity_logs", []) if log.get("action") == "workflow.transition"), None)
check("workflow.transition activity exists", transition_log is not None, str(detail.get("activity_logs")))

print("\n=== Artifact schema migration ===")
migration_conn = sqlite3.connect(":memory:")
migration_conn.row_factory = sqlite3.Row
migration_conn.execute("""CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    stage_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'text/markdown',
    status TEXT NOT NULL DEFAULT 'draft',
    file_path TEXT NOT NULL DEFAULT '',
    file_size INTEGER NOT NULL DEFAULT 0,
    mime_type TEXT NOT NULL DEFAULT 'text/markdown',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""")
migration_conn.execute("INSERT INTO artifacts (id, workflow_id, stage_id, artifact_type, title, file_path, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                       ("art_old", "wi_old", "stg_old", "report", "Old", "wi_old/stg_old/art_old.md", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"))
migration_conn.execute("PRAGMA user_version = 4")
db_schema._run_migrations(migration_conn)
migration_row = migration_conn.execute("SELECT * FROM artifacts WHERE id='art_old'").fetchone()
check("schema v8 migration sets user_version", migration_conn.execute("PRAGMA user_version").fetchone()[0] >= 8)
check("schema v5 backfills storage backend", migration_row["storage_backend"] == "local", dict(migration_row))
check("schema v5 backfills storage key", migration_row["storage_key"] == "wi_old/stg_old/art_old.md", dict(migration_row))
check("schema v5 backfills version/latest", migration_row["version"] == 1 and migration_row["is_latest"] == 1, dict(migration_row))
slack_tables = {
    r[0]
    for r in migration_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'slack_%'").fetchall()
}
check("schema v6 creates Slack mapping tables", {"slack_channel_project_mappings", "slack_event_receipts"}.issubset(slack_tables), slack_tables)
check("schema v7 creates Slack material tables", {"slack_workflow_source_files", "slack_material_collection_states"}.issubset(slack_tables), slack_tables)
worker_tables = {
    r[0]
    for r in migration_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'planning_worker_%'").fetchall()
}
check("schema v8 creates planning worker orchestration tables", {"planning_worker_requests", "planning_worker_results"}.issubset(worker_tables), worker_tables)
migration_conn.close()

legacy_seed_conn = sqlite3.connect(":memory:")
legacy_seed_conn.row_factory = sqlite3.Row
legacy_seed_conn.executescript(db_schema.SCHEMA_SQL)
legacy_seed_conn.execute(
    "INSERT INTO agent_types (id, name, description, icon, color, config_json, created_at) VALUES (?,?,?,?,?,?,?)",
    ("marketing", "Marketing Agent", "Legacy production seed", "Megaphone", "#f97316", "{}", "2025-01-01T00:00:00Z"),
)
plugin_api.seed_if_empty(legacy_seed_conn, plugin_api._now, lambda *args, **kwargs: None)
planning_agent = legacy_seed_conn.execute("SELECT * FROM agent_types WHERE id='planning'").fetchone()
planning_template = legacy_seed_conn.execute("SELECT * FROM workflow_templates WHERE id='planning_research_mvp_v1'").fetchone()
planning_stage_count = legacy_seed_conn.execute("SELECT count(*) FROM stage_definitions WHERE template_id='planning_research_mvp_v1'").fetchone()[0]
legacy_agent = legacy_seed_conn.execute("SELECT * FROM agent_types WHERE id='marketing'").fetchone()
check("existing DB seed preserves legacy agent", legacy_agent is not None and legacy_agent["name"] == "Marketing Agent", dict(legacy_agent) if legacy_agent else "")
check("existing DB seed adds planning agent", planning_agent is not None, "planning missing")
check("existing DB seed adds planning template", planning_template is not None, "planning_research_mvp_v1 missing")
check("existing DB seed adds planning stages", planning_stage_count == 6, f"got {planning_stage_count}")
legacy_seed_conn.close()

print("\n=== Artifacts ===")
r = client.post("/artifacts", json={
    "workflow_id": wf_id,
    "stage_id": "p_material_waiting",
    "artifact_type": "source_material",
    "title": "테스트전자 전달 자료 목록",
    "content": "## 전달 자료\n- 회사 소개서\n- 제품 카탈로그\n- Slack #테스트전자 담당자 메모",
    "content_type": "text/markdown",
})
check("POST /artifacts status", r.status_code == 200, f"got {r.status_code}: {r.text}")
art_id = r.json()["id"]
check("artifact id returned", art_id.startswith("art_"))

r = client.get(f"/artifacts/{art_id}")
check("GET /artifacts/:id status", r.status_code == 200)
art = r.json()
check("artifact title matches", art["title"] == "테스트전자 전달 자료 목록")
check("artifact has empty comments", len(art["comments"]) == 0)
check("artifact storage metadata present", art.get("storage_backend") == "local" and art.get("storage_key") == art.get("file_path"), str(art))
check("artifact version starts latest", art.get("version") == 1 and art.get("is_latest") == 1, str(art))

r = client.get(f"/artifacts/{art_id}/file")
check("GET /artifacts/:id/file status", r.status_code == 200, f"got {r.status_code}: {r.text}")
check("artifact file content returned", "Slack #테스트전자" in r.text, r.text)

r = client.post("/artifacts/upload", data={
    "workflow_id": wf_id,
    "stage_id": "p_material_waiting",
    "artifact_type": "source_material",
    "title": "테스트전자 전달 자료 v2",
    "status": "draft",
}, files={"file": ("latest-source.txt", b"latest source material", "text/plain")})
check("POST /artifacts/upload versioned status", r.status_code == 200, f"got {r.status_code}: {r.text}")
uploaded = r.json()
second_art_id = uploaded.get("id")
check("upload response keeps compatible fields", uploaded.get("file_path") and uploaded.get("file_size") == len(b"latest source material") and uploaded.get("mime_type") == "text/plain", str(uploaded))
r = client.get(f"/artifacts/{second_art_id}")
second_art = r.json()
check("upload stores original filename", second_art.get("original_filename") == "latest-source.txt", str(second_art))
check("upload increments version and latest", second_art.get("version") == 2 and second_art.get("is_latest") == 1, str(second_art))
r = client.get(f"/artifacts/{art_id}")
first_art_after_upload = r.json()
check("prior artifact no longer latest", first_art_after_upload.get("is_latest") == 0, str(first_art_after_upload))
r = client.get(f"/artifacts/{second_art_id}/file")
check("uploaded artifact file returned", r.status_code == 200 and r.content == b"latest source material", f"got {r.status_code}: {r.content!r}")

r = client.patch(f"/artifacts/{art_id}", json={"status": "final"})
check("PATCH artifact status", r.status_code == 200)
r = client.get(f"/artifacts/{art_id}")
check("artifact status updated to final", r.json()["status"] == "final")

print("\n=== Comments ===")
r = client.post(f"/artifacts/{art_id}/comments", json={
    "body": "자료 목록 확인했습니다. 자료조사 worker에게 전달해주세요."
})
check("POST comment status", r.status_code == 200, f"got {r.status_code}: {r.text}")
comment_id = r.json()["id"]

r = client.get(f"/artifacts/{art_id}")
comments = r.json()["comments"]
check("1 comment on artifact", len(comments) == 1)
check("comment author defaulted to display name", comments[0]["author"] == "Hermes Dashboard", str(comments[0]))
check("comment author user id stored", comments[0].get("author_user_id") is not None, str(comments[0]))

r = client.patch(f"/comments/{comment_id}", json={"body": "Updated: 자료 목록과 추가 확인 항목이 명확합니다."})
check("PATCH comment status", r.status_code == 200)
r = client.get(f"/artifacts/{art_id}")
check("comment body updated", r.json()["comments"][0]["body"] == "Updated: 자료 목록과 추가 확인 항목이 명확합니다.")

print("\n=== Approval Flow ===")
r = client.post(f"/workflows/{wf_id}/transition", json={
    "to_stage_id": "p_research_confirmed",
    "note": "사용자 최종 확정 요청",
})
check("approval transition request status", r.status_code == 200, f"got {r.status_code}: {r.text}")
approval_id = r.json().get("approval_id")
check("approval id returned", bool(approval_id), str(r.text))

r = client.get(f"/workflows/{wf_id}")
detail = r.json()
check("workflow pending approval", detail["pending_approval"] is not None, str(detail.get("pending_approval")))
request_log = next((log for log in detail.get("activity_logs", []) if log.get("action") == "workflow.request_approval"), None)
check("workflow.request_approval activity exists", request_log is not None, str(detail.get("activity_logs")))

r = client.post(f"/approvals/{approval_id}/decide", json={
    "status": "approved",
    "note": "진행 승인",
})
check("approve request status", r.status_code == 200, f"got {r.status_code}: {r.text}")
r = client.get(f"/workflows/{wf_id}")
detail = r.json()
check("workflow moved to research confirmed stage", detail["current_stage_id"] == "p_research_confirmed", str(detail))
approval_log = next((log for log in detail.get("activity_logs", []) if log.get("action") == "approval.approved"), None)
check("approval.approved activity exists", approval_log is not None, str(detail.get("activity_logs")))

print("\n=== Events ===")
r = client.get("/events?since=0&limit=100")
check("GET /events status", r.status_code == 200)
events = r.json()
kinds = [e["kind"] for e in events["events"]]
check("workflow_created in events", "workflow_created" in kinds)
check("stage_changed in events", "stage_changed" in kinds)
check("artifact_added in events", "artifact_added" in kinds)
check("approval_requested in events", "approval_requested" in kinds)
check("approval_approved in events", "approval_approved" in kinds)

print("\n=== Logout ===")
r = client.post("/auth/logout")
check("POST /auth/logout status", r.status_code == 200)
r = client.get("/auth/session")
check("parent session remains after AX logout", r.status_code == 200 and r.json().get("authenticated") is True, str(r.text))
r = client.post("/workflows", json={
    "template_id": "design_pipeline_v1",
    "title": "Still allowed by parent dashboard token",
})
check("write still allowed after AX logout", r.status_code == 200, f"got {r.status_code}: {r.text}")

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
if failed:
    sys.exit(1)
else:
    print("All tests passed!")
