"""Quick integration test for plugin_api.py — runs without a live server."""
import sys, os, json

# Ensure we use the venv
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "dashboard"))

# Override DB path to temp location for testing
import tempfile, pathlib
_tmp = tempfile.mkdtemp()
os.environ["HOME"] = _tmp  # seed will write to $HOME/.hermes/...

from fastapi.testclient import TestClient
from fastapi import FastAPI

# Re-import after HOME override so DB goes to temp dir
import importlib
import plugin_api
importlib.reload(plugin_api)

app = FastAPI()
app.include_router(plugin_api.router)
client = TestClient(app)

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

# ---- 1. Agents ----
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

# ---- 2. Board (empty) ----
print("\n=== Board (empty) ===")
r = client.get("/board/sales")
check("GET /board/sales status", r.status_code == 200)
board = r.json()
check("board has 5 columns", len(board["columns"]) == 5, f"got {len(board['columns'])}")
check("all columns empty", all(len(c["workflows"]) == 0 for c in board["columns"]))

# ---- 3. Stats (empty) ----
print("\n=== Stats (empty) ===")
r = client.get("/stats")
check("GET /stats status", r.status_code == 200)
stats = r.json()
check("zero active", stats["active"] == 0)

# ---- 4. Create workflow ----
print("\n=== Create Workflow ===")
r = client.post("/workflows", json={
    "template_id": "sales_pipeline_v1",
    "title": "Acme Corp Deal",
    "priority": 1,
    "assignee": "alice"
})
check("POST /workflows status", r.status_code == 200)
wf = r.json()
wf_id = wf["id"]
check("workflow id returned", wf_id.startswith("wi_"), f"got {wf_id}")
check("initial stage is s_lead", wf["current_stage_id"] == "s_lead")

# ---- 5. Board after create ----
print("\n=== Board (1 workflow) ===")
r = client.get("/board/sales")
board = r.json()
lead_col = board["columns"][0]
check("Lead In column has 1 workflow", len(lead_col["workflows"]) == 1)

# ---- 6. Get workflow detail ----
print("\n=== Workflow Detail ===")
r = client.get(f"/workflows/{wf_id}")
check("GET /workflows/:id status", r.status_code == 200)
detail = r.json()
check("5 stages with status", len(detail["stages"]) == 5)
check("first stage is current", detail["stages"][0]["is_current"] == True)
check("second stage not current", detail["stages"][1]["is_current"] == False)
check("1 initial transition", len(detail["transitions"]) == 1)

# ---- 7. Transition ----
print("\n=== Transition ===")
r = client.post(f"/workflows/{wf_id}/transition", json={
    "to_stage_id": "s_qual",
    "triggered_by": "user",
    "note": "Lead qualified"
})
check("POST transition status", r.status_code == 200)
r = client.get(f"/workflows/{wf_id}")
detail = r.json()
check("current stage now s_qual", detail["current_stage_id"] == "s_qual")
check("2 transitions", len(detail["transitions"]) == 2)

# ---- 8. Create artifact ----
print("\n=== Artifacts ===")
r = client.post("/artifacts", json={
    "workflow_id": wf_id,
    "stage_id": "s_lead",
    "artifact_type": "contact_info",
    "title": "Acme Corp Contact",
    "content": '{"name": "John Doe", "email": "john@acme.com"}',
    "content_type": "application/json"
})
check("POST /artifacts status", r.status_code == 200)
art_id = r.json()["id"]
check("artifact id returned", art_id.startswith("art_"))

r = client.get(f"/artifacts/{art_id}")
check("GET /artifacts/:id status", r.status_code == 200)
art = r.json()
check("artifact title matches", art["title"] == "Acme Corp Contact")
check("artifact has empty comments", len(art["comments"]) == 0)

# ---- 9. Update artifact ----
r = client.patch(f"/artifacts/{art_id}", json={"status": "final"})
check("PATCH artifact status", r.status_code == 200)
r = client.get(f"/artifacts/{art_id}")
check("artifact status updated to final", r.json()["status"] == "final")

# ---- 10. Comments ----
print("\n=== Comments ===")
r = client.post(f"/artifacts/{art_id}/comments", json={
    "author": "alice",
    "body": "Looks good, verified contact info."
})
check("POST comment status", r.status_code == 200)
comment_id = r.json()["id"]

r = client.get(f"/artifacts/{art_id}")
check("1 comment on artifact", len(r.json()["comments"]) == 1)
check("comment author correct", r.json()["comments"][0]["author"] == "alice")

r = client.patch(f"/comments/{comment_id}", json={"body": "Updated: All verified."})
check("PATCH comment status", r.status_code == 200)

r = client.get(f"/artifacts/{art_id}")
check("comment body updated", r.json()["comments"][0]["body"] == "Updated: All verified.")

r = client.delete(f"/comments/{comment_id}")
check("DELETE comment status", r.status_code == 200)

r = client.get(f"/artifacts/{art_id}")
check("0 comments after delete", len(r.json()["comments"]) == 0)

# ---- 11. Update workflow ----
print("\n=== Update Workflow ===")
r = client.patch(f"/workflows/{wf_id}", json={"status": "completed", "title": "Acme Corp Deal (Won)"})
check("PATCH workflow status", r.status_code == 200)
r = client.get(f"/workflows/{wf_id}")
check("workflow completed", r.json()["status"] == "completed")
check("title updated", r.json()["title"] == "Acme Corp Deal (Won)")

# ---- 12. Events ----
print("\n=== Events ===")
r = client.get("/events?since=0&limit=100")
check("GET /events status", r.status_code == 200)
events = r.json()
check("events generated", len(events["events"]) > 0, f"got {len(events['events'])}")
check("cursor > 0", events["cursor"] > 0)
kinds = [e["kind"] for e in events["events"]]
check("workflow_created in events", "workflow_created" in kinds)
check("stage_changed in events", "stage_changed" in kinds)
check("artifact_added in events", "artifact_added" in kinds)

# ---- 13. Stats after operations ----
print("\n=== Final Stats ===")
r = client.get("/stats")
stats = r.json()
check("1 completed workflow", stats["completed"] == 1)
check("1 artifact today", stats["artifacts_today"] >= 1)

# ---- 14. Marketing & Support agents ----
print("\n=== Multi-Agent ===")
r = client.post("/workflows", json={"template_id": "marketing_pipeline_v1", "title": "Q3 Campaign"})
check("marketing workflow created", r.status_code == 200)
r = client.get("/board/marketing")
check("marketing board has workflow", any(len(c["workflows"]) > 0 for c in r.json()["columns"]))

r = client.post("/workflows", json={"template_id": "support_pipeline_v1", "title": "Ticket #1234"})
check("support workflow created", r.status_code == 200)
r = client.get("/board/support")
check("support board has workflow", any(len(c["workflows"]) > 0 for c in r.json()["columns"]))

# ---- Summary ----
print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
if failed:
    sys.exit(1)
else:
    print("All tests passed!")
