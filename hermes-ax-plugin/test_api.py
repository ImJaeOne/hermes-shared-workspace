"""Quick integration test for plugin_api.py — runs without a live server."""
import importlib
import os
import sys
import tempfile

# Ensure we use the dashboard package directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "dashboard"))

# Override HOME and bootstrap admin before plugin import so the temp DB is used
_tmp = tempfile.mkdtemp()
os.environ["HOME"] = _tmp
os.environ["HERMES_AX_BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["HERMES_AX_BOOTSTRAP_ADMIN_PASSWORD"] = "testpass123"
os.environ["HERMES_AX_BOOTSTRAP_ADMIN_DISPLAY_NAME"] = "테스트 관리자"

from fastapi import FastAPI
from fastapi.testclient import TestClient

import plugin_api
importlib.reload(plugin_api)

app = FastAPI()
app.include_router(plugin_api.router)
client = TestClient(app)
anon = TestClient(app)

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


def login_and_check():
    r = client.post("/auth/login", json={"username": "admin", "password": "testpass123"})
    check("POST /auth/login status", r.status_code == 200, f"got {r.status_code}")
    if r.status_code != 200:
        return None
    data = r.json()
    check("login ok response", data.get("ok") is True, str(data))
    check("login user is admin", data.get("user", {}).get("username") == "admin", str(data))
    session = client.get("/auth/session")
    check("GET /auth/session authenticated", session.status_code == 200 and session.json().get("authenticated") is True, str(session.text))
    return data


print("\n=== Auth ===")
r = anon.post("/workflows", json={
    "template_id": "sales_pipeline_v1",
    "title": "Unauthorized Workflow"
})
check("unauthenticated write blocked", r.status_code == 401, f"got {r.status_code}")
login_and_check()

print("\n=== Agents ===")
r = client.get("/agents")
check("GET /agents status", r.status_code == 200)
agents = r.json()
check("3 agent types seeded", len(agents) == 3, f"got {len(agents)}")
check("sales agent exists", any(a["id"] == "sales" for a in agents))
check("each agent has templates", all(len(a.get("templates", [])) > 0 for a in agents))

r2 = client.get("/agents/sales")
check("GET /agents/sales status", r2.status_code == 200)
sales = r2.json()
check("sales has stages", len(sales.get("stages", [])) == 5, f"got {len(sales.get('stages', []))}")

print("\n=== Board / Stats ===")
r = client.get("/board/sales")
check("GET /board/sales status", r.status_code == 200)
board = r.json()
check("board has 5 columns", len(board["columns"]) == 5, f"got {len(board['columns'])}")

r = client.get("/stats")
check("GET /stats status", r.status_code == 200)
stats = r.json()
check("stats has by_agent", isinstance(stats.get("by_agent"), dict), str(stats))

print("\n=== Create Workflow ===")
r = client.post("/workflows", json={
    "template_id": "sales_pipeline_v1",
    "title": "Acme Corp Deal",
    "priority": 1,
    "assignee": "alice"
})
check("POST /workflows status", r.status_code == 200, f"got {r.status_code}: {r.text}")
wf = r.json()
wf_id = wf["id"]
check("workflow id returned", wf_id.startswith("wi_"), f"got {wf_id}")
check("initial stage is s_lead", wf["current_stage_id"] == "s_lead")

print("\n=== Workflow Detail / Activity Logs ===")
r = client.get(f"/workflows/{wf_id}")
check("GET /workflows/:id status", r.status_code == 200)
detail = r.json()
check("5 stages with status", len(detail["stages"]) == 5)
check("first stage is current", detail["stages"][0]["is_current"] is True)
check("1 initial transition", len(detail["transitions"]) == 1)
check("activity logs returned", len(detail.get("activity_logs", [])) >= 1, str(detail.get("activity_logs")))
create_log = next((log for log in detail.get("activity_logs", []) if log.get("action") == "workflow.create"), None)
check("workflow.create activity exists", create_log is not None, str(detail.get("activity_logs")))
if create_log:
    check("workflow.create actor is human", create_log.get("actor_kind") == "human", str(create_log))
    check("workflow.create actor label matches", create_log.get("actor_label") == "테스트 관리자", str(create_log))

print("\n=== Transition ===")
r = client.post(f"/workflows/{wf_id}/transition", json={
    "to_stage_id": "s_qual",
    "triggered_by": "ignored-by-server",
    "note": "Lead qualified"
})
check("POST transition status", r.status_code == 200, f"got {r.status_code}: {r.text}")
r = client.get(f"/workflows/{wf_id}")
detail = r.json()
check("current stage now s_qual", detail["current_stage_id"] == "s_qual")
check("2 transitions", len(detail["transitions"]) == 2)
transition_log = next((log for log in detail.get("activity_logs", []) if log.get("action") == "workflow.transition"), None)
check("workflow.transition activity exists", transition_log is not None, str(detail.get("activity_logs")))

print("\n=== Artifacts ===")
r = client.post("/artifacts", json={
    "workflow_id": wf_id,
    "stage_id": "s_qual",
    "artifact_type": "contact_info",
    "title": "Acme Corp Contact",
    "content": '{"name": "John Doe", "email": "john@acme.com"}',
    "content_type": "application/json"
})
check("POST /artifacts status", r.status_code == 200, f"got {r.status_code}: {r.text}")
art_id = r.json()["id"]
check("artifact id returned", art_id.startswith("art_"))

r = client.get(f"/artifacts/{art_id}")
check("GET /artifacts/:id status", r.status_code == 200)
art = r.json()
check("artifact title matches", art["title"] == "Acme Corp Contact")
check("artifact has empty comments", len(art["comments"]) == 0)

r = client.patch(f"/artifacts/{art_id}", json={"status": "final"})
check("PATCH artifact status", r.status_code == 200)
r = client.get(f"/artifacts/{art_id}")
check("artifact status updated to final", r.json()["status"] == "final")

print("\n=== Comments ===")
r = client.post(f"/artifacts/{art_id}/comments", json={
    "body": "Looks good, verified contact info."
})
check("POST comment status", r.status_code == 200, f"got {r.status_code}: {r.text}")
comment_id = r.json()["id"]

r = client.get(f"/artifacts/{art_id}")
comments = r.json()["comments"]
check("1 comment on artifact", len(comments) == 1)
check("comment author defaulted to display name", comments[0]["author"] == "테스트 관리자", str(comments[0]))
check("comment author user id stored", comments[0].get("author_user_id") is not None, str(comments[0]))

r = client.patch(f"/comments/{comment_id}", json={"body": "Updated: All verified."})
check("PATCH comment status", r.status_code == 200)
r = client.get(f"/artifacts/{art_id}")
check("comment body updated", r.json()["comments"][0]["body"] == "Updated: All verified.")

print("\n=== Approval Flow ===")
r = client.post(f"/workflows/{wf_id}/transition", json={
    "to_stage_id": "s_prop",
    "note": "Need approval before proposal"
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
    "note": "진행 승인"
})
check("approve request status", r.status_code == 200, f"got {r.status_code}: {r.text}")
r = client.get(f"/workflows/{wf_id}")
detail = r.json()
check("workflow moved to proposal stage", detail["current_stage_id"] == "s_prop", str(detail))
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
check("session cleared after logout", r.status_code == 200 and r.json().get("authenticated") is False, str(r.text))
r = client.post("/workflows", json={
    "template_id": "support_pipeline_v1",
    "title": "Should fail after logout"
})
check("write blocked after logout", r.status_code == 401, f"got {r.status_code}")

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
if failed:
    sys.exit(1)
else:
    print("All tests passed!")
