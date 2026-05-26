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
try:
    patch_public_api_allowlist_text('_PUBLIC_API_PATHS: frozenset = frozenset({"/api/status"})')
except RuntimeError:
    missing_anchor_failed = True
else:
    missing_anchor_failed = False
check("dashboard public allowlist patch fails fast when anchor changes", missing_anchor_failed)

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

with plugin_api.get_db() as conn:
    mapping = conn.execute("SELECT * FROM slack_channel_project_mappings WHERE team_id=? AND channel_id=?", ("TLOCAL", "CLOCALTEST")).fetchone()
    check("Slack channel mapping row exists", mapping is not None)
    if mapping:
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
check("schema v6 migration sets user_version", migration_conn.execute("PRAGMA user_version").fetchone()[0] >= 6)
check("schema v5 backfills storage backend", migration_row["storage_backend"] == "local", dict(migration_row))
check("schema v5 backfills storage key", migration_row["storage_key"] == "wi_old/stg_old/art_old.md", dict(migration_row))
check("schema v5 backfills version/latest", migration_row["version"] == 1 and migration_row["is_latest"] == 1, dict(migration_row))
slack_tables = {
    r[0]
    for r in migration_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'slack_%'").fetchall()
}
check("schema v6 creates Slack mapping tables", {"slack_channel_project_mappings", "slack_event_receipts"}.issubset(slack_tables), slack_tables)
migration_conn.close()

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
