"""Quick integration test for plugin_api.py — runs without a live server."""
import asyncio
import hashlib
import hmac
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import time
import urllib.error

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
os.environ["HERMES_AX_WORKER_AUTO_RUNNER_DISABLED"] = "true"

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.patch_hermes_dashboard_public_api import (
    SLACK_EVENTS_PUBLIC_PATH,
    patch_public_api_allowlist_text,
)

import db_schema
import plugin_api
import slack_onboarding_api
import artifact_storage
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


print("\n=== Hermes Dashboard Public API Patch ===")
legacy_public_api_text = '''_PUBLIC_API_PATHS = frozenset({
    "/api/status",
    "/api/dashboard/plugins",
})
'''
patched_legacy_public_api_text = patch_public_api_allowlist_text(legacy_public_api_text)
check(
    "dashboard allowlist patch supports legacy web_server block",
    SLACK_EVENTS_PUBLIC_PATH in patched_legacy_public_api_text
    and patched_legacy_public_api_text.count(SLACK_EVENTS_PUBLIC_PATH) == 1,
    patched_legacy_public_api_text,
)
shared_public_api_text = '''PUBLIC_API_PATHS: frozenset[str] = frozenset({
    "/api/status",
    "/api/dashboard/plugins",
})
'''
patched_shared_public_api_text = patch_public_api_allowlist_text(shared_public_api_text)
check(
    "dashboard allowlist patch supports shared dashboard_auth public_paths block",
    SLACK_EVENTS_PUBLIC_PATH in patched_shared_public_api_text
    and patched_shared_public_api_text.count(SLACK_EVENTS_PUBLIC_PATH) == 1,
    patched_shared_public_api_text,
)
check(
    "dashboard allowlist patch is idempotent for Slack webhook path",
    patch_public_api_allowlist_text(patched_shared_public_api_text) == patched_shared_public_api_text,
    patched_shared_public_api_text,
)


print("\n=== Research Adapters ===")
try:
    import research_adapters
except Exception as exc:
    research_adapters = None
    check("research adapters module import", False, repr(exc))
else:
    check("research adapters module import", True)

if research_adapters:
    old_engine = os.environ.get("HERMES_AX_RESEARCH_ENGINE")
    old_fallback = os.environ.get("HERMES_AX_RESEARCH_FALLBACK_ENGINE")
    old_auth_json = os.environ.get("HERMES_AX_NOTEBOOKLM_AUTH_JSON")
    old_auth_path = os.environ.get("HERMES_AX_NOTEBOOKLM_AUTH_PATH")
    old_profile = os.environ.get("HERMES_AX_NOTEBOOKLM_PROFILE")
    try:
        os.environ["HERMES_AX_RESEARCH_ENGINE"] = "notebooklm_py"
        os.environ["HERMES_AX_RESEARCH_FALLBACK_ENGINE"] = "mock"
        os.environ.pop("HERMES_AX_NOTEBOOKLM_AUTH_JSON", None)
        os.environ.pop("HERMES_AX_NOTEBOOKLM_AUTH_PATH", None)
        os.environ.pop("HERMES_AX_NOTEBOOKLM_PROFILE", None)
        fallback_result = research_adapters.run_research_adapter(
            {
                "task_type": "initial_research",
                "company_name": "FallbackCo",
                "source_files": [{"filename": "intro.md", "title": "소개 자료", "artifact": {"content": "회사 소개"}}],
            },
            {"skill_id": "skill_001", "name": "기획 자료조사 결과 정리", "content": "핵심 요약 중심으로 정리"},
        )
        check("NotebookLM adapter falls back to mock without auth", fallback_result.engine == "mock" and fallback_result.metadata.get("fallback_from") == "notebooklm_py", fallback_result)
        check("NotebookLM fallback keeps user-safe diagnostics", "NotebookLM" not in fallback_result.metadata.get("safe_message", "") and "쿠키" not in fallback_result.metadata.get("safe_message", ""), fallback_result.metadata)

        status_missing = client.get("/worker/notebooklm/auth-status")
        status_missing_body = status_missing.json()
        check(
            "NotebookLM auth status reports missing auth without exposing secrets",
            status_missing.status_code == 200
            and status_missing_body.get("configured") is False
            and status_missing_body.get("can_run") is False
            and status_missing_body.get("code") == "notebooklm_auth_not_configured"
            and "secret-storage-state" not in json.dumps(status_missing_body, ensure_ascii=False),
            status_missing_body,
        )

        os.environ["HERMES_AX_NOTEBOOKLM_AUTH_JSON"] = '{"cookies": [{"name": "SID", "value": "secret-storage-state"}]}'
        status_json = client.get("/worker/notebooklm/auth-status")
        status_json_body = status_json.json()
        check(
            "NotebookLM auth status validates AUTH_JSON metadata only",
            status_json.status_code == 200
            and status_json_body.get("configured") is True
            and status_json_body.get("can_run") is True
            and status_json_body.get("source") == "auth_json"
            and status_json_body.get("auth_json", {}).get("present") is True
            and status_json_body.get("auth_json", {}).get("valid_json") is True
            and status_json_body.get("auth_json", {}).get("length", 0) > 0
            and "secret-storage-state" not in json.dumps(status_json_body, ensure_ascii=False),
            status_json_body,
        )

        os.environ["HERMES_AX_NOTEBOOKLM_AUTH_JSON"] = "not-json-secret-storage-state"
        status_invalid_json = client.get("/worker/notebooklm/auth-status")
        status_invalid_json_body = status_invalid_json.json()
        check(
            "NotebookLM auth status separates invalid AUTH_JSON",
            status_invalid_json.status_code == 200
            and status_invalid_json_body.get("configured") is True
            and status_invalid_json_body.get("can_run") is False
            and status_invalid_json_body.get("code") == "notebooklm_auth_json_invalid"
            and status_invalid_json_body.get("auth_json", {}).get("valid_json") is False
            and "not-json-secret-storage-state" not in json.dumps(status_invalid_json_body, ensure_ascii=False),
            status_invalid_json_body,
        )

        os.environ["HERMES_AX_NOTEBOOKLM_AUTH_JSON"] = "123"
        status_scalar_json = client.get("/worker/notebooklm/auth-status")
        status_scalar_json_body = status_scalar_json.json()
        check(
            "NotebookLM auth status rejects scalar AUTH_JSON",
            status_scalar_json.status_code == 200
            and status_scalar_json_body.get("configured") is True
            and status_scalar_json_body.get("can_run") is False
            and status_scalar_json_body.get("code") == "notebooklm_auth_json_invalid"
            and status_scalar_json_body.get("auth_json", {}).get("valid_json") is True
            and status_scalar_json_body.get("auth_json", {}).get("storage_state_shape_valid") is False,
            status_scalar_json_body,
        )

        auth_json_path = os.path.join(_tmp, "notebooklm-auth-json-path.json")
        with open(auth_json_path, "w", encoding="utf-8") as fh:
            json.dump({"cookies": [{"name": "SID", "value": "json-path-secret-storage-state"}]}, fh)
        os.environ["HERMES_AX_NOTEBOOKLM_AUTH_JSON"] = auth_json_path
        status_json_path = client.get("/worker/notebooklm/auth-status")
        status_json_path_body = status_json_path.json()
        check(
            "NotebookLM auth status supports AUTH_JSON file path runtime behavior",
            status_json_path.status_code == 200
            and status_json_path_body.get("configured") is True
            and status_json_path_body.get("can_run") is True
            and status_json_path_body.get("source") == "auth_json_path"
            and status_json_path_body.get("code") == "notebooklm_auth_ready"
            and status_json_path_body.get("auth_json", {}).get("path", {}).get("exists") is True
            and status_json_path_body.get("auth_json", {}).get("path", {}).get("valid_json") is True
            and auth_json_path not in json.dumps(status_json_path_body, ensure_ascii=False)
            and "json-path-secret-storage-state" not in json.dumps(status_json_path_body, ensure_ascii=False),
            status_json_path_body,
        )

        missing_auth_path = os.path.join(_tmp, "missing-notebooklm-auth.json")
        os.environ["HERMES_AX_NOTEBOOKLM_AUTH_JSON"] = '{"cookies": []}'
        os.environ["HERMES_AX_NOTEBOOKLM_AUTH_PATH"] = missing_auth_path
        status_path_precedence = client.get("/worker/notebooklm/auth-status")
        status_path_precedence_body = status_path_precedence.json()
        check(
            "NotebookLM auth status honors AUTH_PATH precedence over AUTH_JSON",
            status_path_precedence.status_code == 200
            and status_path_precedence_body.get("configured") is True
            and status_path_precedence_body.get("can_run") is False
            and status_path_precedence_body.get("source") == "auth_path"
            and status_path_precedence_body.get("code") == "notebooklm_auth_path_missing"
            and status_path_precedence_body.get("auth_path", {}).get("exists") is False,
            status_path_precedence_body,
        )

        valid_auth_path = os.path.join(_tmp, "notebooklm-auth.json")
        with open(valid_auth_path, "w", encoding="utf-8") as fh:
            json.dump({"cookies": [{"name": "SID", "value": "path-secret-storage-state"}]}, fh)
        os.environ["HERMES_AX_NOTEBOOKLM_AUTH_PATH"] = valid_auth_path
        status_path = client.get("/worker/notebooklm/auth-status")
        status_path_body = status_path.json()
        check(
            "NotebookLM auth status validates AUTH_PATH file metadata only",
            status_path.status_code == 200
            and status_path_body.get("configured") is True
            and status_path_body.get("can_run") is True
            and status_path_body.get("source") == "auth_path"
            and status_path_body.get("auth_path", {}).get("exists") is True
            and status_path_body.get("auth_path", {}).get("valid_json") is True
            and "path-secret-storage-state" not in json.dumps(status_path_body, ensure_ascii=False),
            status_path_body,
        )

        os.environ.pop("HERMES_AX_NOTEBOOKLM_AUTH_JSON", None)
        os.environ.pop("HERMES_AX_NOTEBOOKLM_AUTH_PATH", None)
        os.environ["HERMES_AX_NOTEBOOKLM_PROFILE"] = "company-shared"
        status_profile = client.get("/worker/notebooklm/auth-status")
        status_profile_body = status_profile.json()
        check(
            "NotebookLM auth status accepts profile-only configuration",
            status_profile.status_code == 200
            and status_profile_body.get("configured") is True
            and status_profile_body.get("can_run") is True
            and status_profile_body.get("source") == "profile"
            and status_profile_body.get("profile", {}).get("present") is True,
            status_profile_body,
        )
    finally:
        for key, value in {
            "HERMES_AX_RESEARCH_ENGINE": old_engine,
            "HERMES_AX_RESEARCH_FALLBACK_ENGINE": old_fallback,
            "HERMES_AX_NOTEBOOKLM_AUTH_JSON": old_auth_json,
            "HERMES_AX_NOTEBOOKLM_AUTH_PATH": old_auth_path,
            "HERMES_AX_NOTEBOOKLM_PROFILE": old_profile,
        }.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    class FakeNotebookSources:
        def __init__(self, fail_file_title: str = ""):
            self.files = []
            self.texts = []
            self.fail_file_title = fail_file_title

        async def add_file(self, notebook_id, file_path, **kwargs):
            title = str(kwargs.get("title") or "")
            if self.fail_file_title and title == self.fail_file_title:
                raise TimeoutError(f"Source {title} not ready after 120.0s")
            self.files.append({"notebook_id": notebook_id, "file_path": file_path, **kwargs})

        async def add_text(self, notebook_id, title, content, **kwargs):
            self.texts.append({"notebook_id": notebook_id, "title": title, "content": content, **kwargs})

    class FakeTimeoutAwareNotebookSources:
        def __init__(self):
            self.files = []
            self.texts = []

        async def add_file(self, notebook_id, file_path, *, mime_type=None, title=None, wait=True, wait_timeout=None):
            if wait_timeout is None:
                raise TimeoutError("Source failed because wait_timeout was not forwarded")
            self.files.append({"notebook_id": notebook_id, "file_path": file_path, "mime_type": mime_type, "title": title, "wait": wait, "wait_timeout": wait_timeout})

        async def add_text(self, notebook_id, title, content, *, wait=True, wait_timeout=None):
            if wait_timeout is None:
                raise TimeoutError("Text source failed because wait_timeout was not forwarded")
            self.texts.append({"notebook_id": notebook_id, "title": title, "content": content, "wait": wait, "wait_timeout": wait_timeout})

    class FakeNotebookClient:
        def __init__(self):
            self.sources = FakeNotebookSources()

    storage = artifact_storage.get_artifact_storage()
    stored = storage.write_bytes(
        workflow_id="wf_adapter_storage",
        stage_id="p_material_waiting",
        artifact_id="art_adapter_pdf",
        content=b"%PDF-1.7\nsource bytes",
        mime_type="application/pdf",
        original_filename="source.pdf",
    )
    fake_client = FakeNotebookClient()
    asyncio.run(
        research_adapters.NotebookLmPyResearchAdapter()._add_sources(
            fake_client,
            "notebook-1",
            {
                "source_files": [
                    {
                        "filename": "source.pdf",
                        "artifact": {
                            "content": "",
                            "file_path": stored.file_path,
                            "storage_backend": stored.storage_backend,
                            "storage_key": stored.storage_key,
                            "mime_type": stored.mime_type,
                        },
                    }
                ]
            },
        )
    )
    expected_file_path = str(storage.resolve_path(stored.storage_key))
    check(
        "NotebookLM adapter resolves local artifact storage file",
        len(fake_client.sources.files) == 1 and fake_client.sources.files[0]["file_path"] == expected_file_path and not fake_client.sources.texts,
        {"files": fake_client.sources.files, "texts": fake_client.sources.texts, "expected": expected_file_path},
    )

    four_source_files = []
    original_names = [
        "국내외 오가노이드 관련 기업, 연구소 현황.pdf",
        "기관투자자 요청자료.pdf",
        "기관투자자 추가질의 및 답변.pdf",
        "IR Book_Jan.2026_압축본.pdf",
    ]
    for index, original_name in enumerate(original_names, start=1):
        generated_artifact_id = f"art_notebooklm_source_{index}"
        stored_item = storage.write_bytes(
            workflow_id="wf_adapter_four_sources",
            stage_id="p_material_waiting",
            artifact_id=generated_artifact_id,
            content=f"%PDF-1.7 source {index}".encode("utf-8"),
            mime_type="application/pdf",
            original_filename=original_name,
        )
        four_source_files.append(
            {
                "filename": f"{generated_artifact_id}.pdf",
                "title": f"{generated_artifact_id}.pdf",
                "artifact": {
                    "id": generated_artifact_id,
                    "title": f"{generated_artifact_id}.pdf",
                    "content": "",
                    "file_path": stored_item.file_path,
                    "storage_backend": stored_item.storage_backend,
                    "storage_key": stored_item.storage_key,
                    "mime_type": stored_item.mime_type,
                    "original_filename": original_name,
                },
            }
        )
    four_source_client = FakeNotebookClient()
    upload_metadata = asyncio.run(
        research_adapters.NotebookLmPyResearchAdapter()._add_sources(
            four_source_client,
            "notebook-four-sources",
            {"source_files": four_source_files},
        )
    )
    check(
        "NotebookLM adapter uploads all four stored Slack artifacts",
        len(four_source_client.sources.files) == 4 and not four_source_client.sources.texts,
        {"files": four_source_client.sources.files, "texts": four_source_client.sources.texts},
    )
    check(
        "NotebookLM adapter prefers original filenames over generated artifact names",
        [item.get("title") for item in four_source_client.sources.files] == original_names,
        four_source_client.sources.files,
    )
    check(
        "NotebookLM adapter returns per-source upload diagnostics",
        isinstance(upload_metadata, dict)
        and upload_metadata.get("attempted_count") == 4
        and upload_metadata.get("succeeded_count") == 4
        and upload_metadata.get("skipped_count") == 0
        and len(upload_metadata.get("sources", [])) == 4
        and all(item.get("status") == "uploaded" for item in upload_metadata.get("sources", [])),
        upload_metadata,
    )

    timeout_client = FakeNotebookClient()
    timeout_client.sources = FakeNotebookSources(fail_file_title=original_names[1])
    timeout_metadata = asyncio.run(
        research_adapters.NotebookLmPyResearchAdapter()._add_sources(
            timeout_client,
            "notebook-timeout-sources",
            {"source_files": four_source_files},
        )
    )
    check(
        "NotebookLM adapter continues after one source upload timeout",
        len(timeout_client.sources.files) == 3
        and timeout_metadata.get("attempted_count") == 4
        and timeout_metadata.get("succeeded_count") == 3
        and timeout_metadata.get("failed_count") == 1,
        {"files": timeout_client.sources.files, "metadata": timeout_metadata},
    )
    failed_upload = next((item for item in timeout_metadata.get("sources", []) if item.get("status") == "failed"), {})
    check(
        "NotebookLM adapter records per-source timeout diagnostics",
        failed_upload.get("title") == original_names[1]
        and failed_upload.get("reason") == "source_upload_failed"
        and failed_upload.get("exception_type") == "TimeoutError"
        and "not ready" in failed_upload.get("message", ""),
        failed_upload,
    )

    old_timeout = os.environ.get("HERMES_AX_NOTEBOOKLM_TIMEOUT")
    os.environ["HERMES_AX_NOTEBOOKLM_TIMEOUT"] = "300"
    try:
        timeout_aware_client = FakeNotebookClient()
        timeout_aware_client.sources = FakeTimeoutAwareNotebookSources()
        timeout_aware_metadata = asyncio.run(
            research_adapters.NotebookLmPyResearchAdapter()._add_sources(
                timeout_aware_client,
                "notebook-timeout-aware-sources",
                {"source_files": four_source_files[:1]},
            )
        )
    finally:
        if old_timeout is None:
            os.environ.pop("HERMES_AX_NOTEBOOKLM_TIMEOUT", None)
        else:
            os.environ["HERMES_AX_NOTEBOOKLM_TIMEOUT"] = old_timeout
    check(
        "NotebookLM adapter forwards configured timeout to source ready wait",
        len(timeout_aware_client.sources.files) == 1
        and timeout_aware_client.sources.files[0].get("wait_timeout") == 300.0
        and timeout_aware_metadata.get("succeeded_count") == 1
        and timeout_aware_metadata.get("sources", [{}])[0].get("wait_timeout_seconds") == 300.0,
        {"files": timeout_aware_client.sources.files, "metadata": timeout_aware_metadata},
    )

    revision_prompt = {
        "skill_id": "skill_001",
        "name": "기획 자료조사 결과 정리",
        "content": "초기 자료조사용 프롬프트: 핵심 요약 중심으로 정리",
    }
    revision_attachment_payload = {
        "source_files": four_source_files[:1],
        "revision": {
            "instruction": "",
            "attachments": [
                {
                    "filename": "revision-notes.md",
                    "title": "수정 요청 메모",
                    "artifact": {"content": "# 수정 요청\n- 시장 규모와 경쟁사 비교를 더 보강해주세요."},
                }
            ],
        },
    }
    revision_question = research_adapters.NotebookLmPyResearchAdapter()._build_question(revision_attachment_payload, revision_prompt)
    check(
        "NotebookLM adapter carries revision attachments into question context",
        "revision-notes.md" in revision_question or "수정 요청 메모" in revision_question,
        revision_question,
    )
    revision_instruction_question = research_adapters.NotebookLmPyResearchAdapter()._build_question(
        {
            "task_type": "revision",
            "company_name": "수정테스트",
            "source_files": four_source_files[:1],
            "revision": {"instruction": "시놉시스는 어떻게 처리하는게 좋을지 알려줘"},
        },
        revision_prompt,
    )
    check(
        "NotebookLM revision question omits initial research prompt content",
        "초기 자료조사용 프롬프트" not in revision_instruction_question
        and "시놉시스는 어떻게 처리하는게 좋을지 알려줘" in revision_instruction_question,
        revision_instruction_question,
    )

    duplicate_client = FakeNotebookClient()
    initial_duplicate_payload = {"source_files": four_source_files[:2]}
    asyncio.run(
        research_adapters.NotebookLmPyResearchAdapter()._add_sources(
            duplicate_client,
            "notebook-revision-reuse",
            initial_duplicate_payload,
        )
    )
    revision_source_files = four_source_files[:2] + [
        {
            "filename": "revision-notes.md",
            "title": "수정 요청 메모",
            "artifact": {"content": "# 수정 요청\n- 시장 규모와 경쟁사 비교를 더 보강해주세요."},
        }
    ]
    duplicate_revision_metadata = asyncio.run(
        research_adapters.NotebookLmPyResearchAdapter()._add_sources(
            duplicate_client,
            "notebook-revision-reuse",
            {"notebook_id": "notebook-revision-reuse", "source_files": revision_source_files},
        )
    )
    check(
        "NotebookLM adapter skips duplicate initial sources on revision notebook reuse",
        duplicate_revision_metadata.get("attempted_count") == 3
        and duplicate_revision_metadata.get("succeeded_count") == 1
        and duplicate_revision_metadata.get("skipped_count") == 2
        and len([item for item in duplicate_revision_metadata.get("sources", []) if item.get("status") == "skipped"]) == 2
        and len(duplicate_client.sources.files) == 2
        and len(duplicate_client.sources.texts) == 1,
        {"files": duplicate_client.sources.files, "texts": duplicate_client.sources.texts, "metadata": duplicate_revision_metadata},
    )

class FakeHTTPResponse:
    def __init__(self, *, payload: dict | None = None, body: bytes | None = None):
        self._body = body if body is not None else json.dumps(payload or {}).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def request_url(req) -> str:
    return getattr(req, "full_url", str(req))


def request_json(req) -> dict:
    raw = getattr(req, "data", None) or b"{}"
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return json.loads(raw.decode("utf-8") or "{}")


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


def mark_worker_request_running(request_id: str):
    with plugin_api.get_db() as conn:
        conn.execute(
            "UPDATE planning_worker_requests SET status='running', updated_at=? WHERE id=?",
            (plugin_api._now(), request_id),
        )


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


def slack_message_pdf_file_payload(
    event_id: str,
    *,
    channel_id: str,
    file_id: str,
    filename: str = "source.pdf",
    title: str = "PDF source",
    url_private: str = "https://slack.example/files/source.pdf",
    url_private_download: str = "https://slack.example/files/source.pdf/download",
) -> dict:
    file_info = {
        "id": file_id,
        "name": filename,
        "title": title,
        "mimetype": "application/pdf",
        "size": 1234,
        "user": "UCLIENTPDF",
        "created": 1710000100,
    }
    if url_private:
        file_info["url_private"] = url_private
    if url_private_download:
        file_info["url_private_download"] = url_private_download
    return {
        "type": "event_callback",
        "team_id": "TLOCAL",
        "api_app_id": "AAXLOCAL",
        "event_id": event_id,
        "event_time": int(time.time()),
        "event": {
            "type": "message",
            "channel": channel_id,
            "user": "UCLIENTPDF",
            "ts": "1710000100.000100",
            "text": "PDF 자료 첨부드립니다.",
            "files": [file_info],
        },
    }


def fetch_source_artifact(slack_file_id: str):
    with plugin_api.get_db() as conn:
        source = conn.execute("SELECT * FROM slack_workflow_source_files WHERE slack_file_id=?", (slack_file_id,)).fetchone()
        artifact = None
        if source and source["artifact_id"]:
            artifact = conn.execute("SELECT * FROM artifacts WHERE id=?", (source["artifact_id"],)).fetchone()
        return source, artifact


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

saved_dry_run = os.environ.get("HERMES_AX_SLACK_DRY_RUN")
saved_ax_bot_token = os.environ.get("HERMES_AX_SLACK_BOT_TOKEN")
saved_slack_bot_token = os.environ.get("SLACK_BOT_TOKEN")
orig_urlopen = slack_onboarding_api.urllib.request.urlopen
try:
    os.environ["HERMES_AX_SLACK_DRY_RUN"] = "true"
    os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = "test-bot-token"
    os.environ.pop("SLACK_BOT_TOKEN", None)
    dry_run_info_calls = []

    def fake_dry_run_info_lookup(req, timeout=None):
        dry_run_info_calls.append(request_url(req))
        return FakeHTTPResponse(payload={"ok": True, "channel": {"name": "네트워크조회"}})

    slack_onboarding_api.urllib.request.urlopen = fake_dry_run_info_lookup
    dry_run_info_payload = slack_event_payload(event_id="EvDRYRUNINFO", channel_id="CDRYRUNINFO", channel_name="")
    dry_run_info_payload["event"]["type"] = "channel_created"
    dry_run_info_payload["event"]["channel"] = {"id": "CDRYRUNINFO"}
    dry_run_info_body, dry_run_info_headers = slack_headers(dry_run_info_payload)
    r = anon.post("/slack/events", content=dry_run_info_body, headers=dry_run_info_headers)
    dry_run_info_result = r.json()
    check(
        "Slack dry-run channel lookup skips network",
        r.status_code == 200 and dry_run_info_result.get("reason") == "channel_name_required" and dry_run_info_calls == [],
        {"response": f"{r.status_code}: {r.text}", "network_calls": dry_run_info_calls},
    )
finally:
    slack_onboarding_api.urllib.request.urlopen = orig_urlopen
    if saved_dry_run is None:
        os.environ.pop("HERMES_AX_SLACK_DRY_RUN", None)
    else:
        os.environ["HERMES_AX_SLACK_DRY_RUN"] = saved_dry_run
    if saved_ax_bot_token is None:
        os.environ.pop("HERMES_AX_SLACK_BOT_TOKEN", None)
    else:
        os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = saved_ax_bot_token
    if saved_slack_bot_token is None:
        os.environ.pop("SLACK_BOT_TOKEN", None)
    else:
        os.environ["SLACK_BOT_TOKEN"] = saved_slack_bot_token

saved_dry_run = os.environ.get("HERMES_AX_SLACK_DRY_RUN")
saved_ax_bot_token = os.environ.get("HERMES_AX_SLACK_BOT_TOKEN")
saved_slack_bot_token = os.environ.get("SLACK_BOT_TOKEN")
orig_urlopen = slack_onboarding_api.urllib.request.urlopen
try:
    os.environ["HERMES_AX_SLACK_DRY_RUN"] = "false"
    os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = "test-bot-token"
    os.environ.pop("SLACK_BOT_TOKEN", None)
    slack_api_calls = []

    def fake_join_then_post(req, timeout=None):
        url = request_url(req)
        payload = request_json(req)
        auth = req.headers.get("Authorization") or req.headers.get("authorization")
        if url.endswith("/conversations.join"):
            slack_api_calls.append({"method": "conversations.join", "payload": payload, "auth": auth})
            return FakeHTTPResponse(payload={"ok": True, "channel": {"id": payload.get("channel")}})
        if url.endswith("/chat.postMessage"):
            slack_api_calls.append({"method": "chat.postMessage", "payload": payload, "auth": auth})
            return FakeHTTPResponse(payload={"ok": True, "ts": "1710000200.000100"})
        raise AssertionError(f"unexpected Slack API call: {url}")

    slack_onboarding_api.urllib.request.urlopen = fake_join_then_post
    join_payload = slack_event_payload(event_id="EvJOINAPI1", channel_id="CJOINAPI1", channel_name="조인테스트")
    join_payload["event"]["type"] = "channel_created"
    join_body, join_headers = slack_headers(join_payload)
    r = anon.post("/slack/events", content=join_body, headers=join_headers)
    join_result = r.json()
    check("Slack non-dry-run channel_created status", r.status_code == 200, f"got {r.status_code}: {r.text}")
    check("Slack non-dry-run joins before onboarding post", [c["method"] for c in slack_api_calls] == ["conversations.join", "chat.postMessage"], slack_api_calls)
    check("Slack join targets onboarding channel", slack_api_calls and slack_api_calls[0]["payload"].get("channel") == "CJOINAPI1", slack_api_calls)
    check("Slack onboarding post follows join", len(slack_api_calls) == 2 and slack_api_calls[1]["payload"].get("channel") == "CJOINAPI1" and join_result.get("message_sent") is True, join_result)
    check("Slack API calls use bot token", all(c.get("auth") == "Bearer test-bot-token" for c in slack_api_calls), slack_api_calls)

    def fake_progress_update(req, timeout=None):
        url = request_url(req)
        payload = request_json(req)
        auth = req.headers.get("Authorization") or req.headers.get("authorization")
        if url.endswith("/chat.update"):
            slack_api_calls.append({"method": "chat.update", "payload": payload, "auth": auth})
            return FakeHTTPResponse(payload={"ok": True, "ts": payload.get("ts")})
        if url.endswith("/chat.postMessage"):
            slack_api_calls.append({"method": "chat.postMessage", "payload": payload, "auth": auth})
            return FakeHTTPResponse(payload={"ok": True, "ts": "1710000200.999999"})
        raise AssertionError(f"unexpected Slack API call: {url}")

    slack_api_calls.clear()
    slack_onboarding_api.urllib.request.urlopen = fake_progress_update
    with plugin_api.get_db() as conn:
        mapping = conn.execute("SELECT * FROM slack_channel_project_mappings WHERE channel_id=?", ("CJOINAPI1",)).fetchone()
        slack_onboarding_api._upsert_material_state(
            conn,
            mapping=mapping,
            message="기획팀 임팀장이 자료를 확인하고 있습니다. 잠시만 기다려주세요.",
            send_result={"sent": True, "ts": "1710000200.000100"},
        )
        progress_result = slack_onboarding_api._send_progress_message(
            conn,
            mapping,
            "기획팀 임사원이 자료를 확인 중입니다. 완료되면 이 채널에 자료조사 결과를 전달드리겠습니다.",
        )
    check("Slack progress updates existing status message", progress_result.get("sent") is True and progress_result.get("updated") is True, progress_result)
    check("Slack progress uses chat.update without new post", [c["method"] for c in slack_api_calls] == ["chat.update"], slack_api_calls)
    check("Slack progress update keeps original ts", slack_api_calls and slack_api_calls[0]["payload"].get("ts") == "1710000200.000100", slack_api_calls)

    slack_api_calls.clear()
    join_again_payload = slack_event_payload(event_id="EvJOINAPI1B", channel_id="CJOINAPI1", channel_name="조인테스트")
    join_again_payload["event"]["type"] = "channel_created"
    join_again_body, join_again_headers = slack_headers(join_again_payload)
    r = anon.post("/slack/events", content=join_again_body, headers=join_again_headers)
    join_again_result = r.json()
    check("Slack already-sent mapping does not resend onboarding", r.status_code == 200 and join_again_result.get("message_sent") is False and join_again_result.get("message_skipped_reason") == "already_sent", f"got {r.status_code}: {r.text}")
    check("Slack already-sent mapping skips join and post", slack_api_calls == [], slack_api_calls)

    def fake_already_in_channel_then_post(req, timeout=None):
        url = request_url(req)
        payload = request_json(req)
        if url.endswith("/conversations.join"):
            slack_api_calls.append({"method": "conversations.join", "payload": payload})
            return FakeHTTPResponse(payload={"ok": False, "error": "already_in_channel"})
        if url.endswith("/chat.postMessage"):
            slack_api_calls.append({"method": "chat.postMessage", "payload": payload})
            return FakeHTTPResponse(payload={"ok": True, "ts": "1710000201.000100"})
        raise AssertionError(f"unexpected Slack API call: {url}")

    slack_api_calls.clear()
    slack_onboarding_api.urllib.request.urlopen = fake_already_in_channel_then_post
    already_joined_payload = slack_event_payload(event_id="EvJOINAPI2", channel_id="CJOINAPI2", channel_name="이미참여")
    already_joined_payload["event"]["type"] = "channel_created"
    already_joined_body, already_joined_headers = slack_headers(already_joined_payload)
    r = anon.post("/slack/events", content=already_joined_body, headers=already_joined_headers)
    already_joined_result = r.json()
    check("Slack already_in_channel join treated as success", r.status_code == 200 and already_joined_result.get("ok") is True and already_joined_result.get("message_sent") is True, f"got {r.status_code}: {r.text}")
    check("Slack already_in_channel still posts onboarding", [c["method"] for c in slack_api_calls] == ["conversations.join", "chat.postMessage"], slack_api_calls)
finally:
    slack_onboarding_api.urllib.request.urlopen = orig_urlopen
    if saved_dry_run is None:
        os.environ.pop("HERMES_AX_SLACK_DRY_RUN", None)
    else:
        os.environ["HERMES_AX_SLACK_DRY_RUN"] = saved_dry_run
    if saved_ax_bot_token is None:
        os.environ.pop("HERMES_AX_SLACK_BOT_TOKEN", None)
    else:
        os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = saved_ax_bot_token
    if saved_slack_bot_token is None:
        os.environ.pop("SLACK_BOT_TOKEN", None)
    else:
        os.environ["SLACK_BOT_TOKEN"] = saved_slack_bot_token

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
check("Slack dry-run message timestamp deterministic", slack_result.get("onboarding_message_ts") == "dry-run-CLOCALTEST", str(slack_result))
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
message_payload["event"]["subtype"] = "file_share"
message_body, message_headers = slack_headers(message_payload)
r = anon.post("/slack/events", content=message_body, headers=message_headers)
check("Slack message file_share event status", r.status_code == 200, f"got {r.status_code}: {r.text}")
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

bot_echo_payload = slack_message_text_payload("EvBOTCONFIRM1", confirmation_message)
bot_echo_payload["event"]["subtype"] = "bot_message"
bot_echo_payload["event"]["bot_id"] = "BAXLOCALBOT"
bot_echo_payload["event"]["user"] = "UBOTLEAD"
bot_echo_body, bot_echo_headers = slack_headers(bot_echo_payload)
r = anon.post("/slack/events", content=bot_echo_body, headers=bot_echo_headers)
check("Slack ignores own material confirmation bot message", r.status_code == 200 and r.json().get("ignored") is True and r.json().get("reason") == "bot_message", f"got {r.status_code}: {r.text}")

bot_user_echo_payload = slack_message_text_payload("EvBOTCONFIRM2", confirmation_message)
bot_user_echo_payload["event"]["user"] = "UBOTLEAD"
bot_user_echo_body, bot_user_echo_headers = slack_headers(bot_user_echo_payload)
r = anon.post("/slack/events", content=bot_user_echo_body, headers=bot_user_echo_headers)
check("Slack ignores own bot user id material confirmation", r.status_code == 200 and r.json().get("ignored") is True and r.json().get("reason") == "bot_message", f"got {r.status_code}: {r.text}")
with plugin_api.get_db() as conn:
    wf_after_bot_echo = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (slack_wf_id,)).fetchone()
    material_state_after_bot_echo = conn.execute("SELECT * FROM slack_material_collection_states WHERE workflow_id=?", (slack_wf_id,)).fetchone()
    premature_research_count = conn.execute("SELECT count(*) FROM planning_worker_requests WHERE workflow_id=? AND request_type='research'", (slack_wf_id,)).fetchone()[0]
    premature_transition_count = conn.execute("SELECT count(*) FROM stage_transitions WHERE workflow_id=? AND to_stage_id='p_research_running'", (slack_wf_id,)).fetchone()[0]
    check("Slack bot echo keeps workflow waiting", wf_after_bot_echo["current_stage_id"] == "p_material_waiting", dict(wf_after_bot_echo))
    check("Slack bot echo keeps material state pending", material_state_after_bot_echo is not None and material_state_after_bot_echo["status"] == "pending_confirmation", dict(material_state_after_bot_echo) if material_state_after_bot_echo else "")
    check("Slack bot echo does not create research request", premature_research_count == 0, f"got {premature_research_count}")
    check("Slack bot echo does not transition to research", premature_transition_count == 0, f"got {premature_transition_count}")

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
question_message_ts = ""
with plugin_api.get_db() as conn:
    question_state = conn.execute("SELECT * FROM slack_material_collection_states WHERE workflow_id=?", (slack_wf_id,)).fetchone()
    question_message_ts = question_state["last_message_ts"] if question_state else ""

saved_confirm_dry_run = os.environ.get("HERMES_AX_SLACK_DRY_RUN")
saved_confirm_ax_bot_token = os.environ.get("HERMES_AX_SLACK_BOT_TOKEN")
saved_confirm_slack_bot_token = os.environ.get("SLACK_BOT_TOKEN")
orig_confirm_urlopen = slack_onboarding_api.urllib.request.urlopen
orig_confirm_runner_kick = getattr(slack_onboarding_api, "_kick_worker_runner", None)
confirm_slack_calls = []
worker_runner_kicks = []
try:
    os.environ["HERMES_AX_SLACK_DRY_RUN"] = "false"
    os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = "test-bot-token"
    os.environ.pop("SLACK_BOT_TOKEN", None)

    def fake_confirm_status_post(req, timeout=None):
        url = request_url(req)
        payload = request_json(req)
        if url.endswith("/chat.update"):
            confirm_slack_calls.append({"method": "chat.update", "payload": payload})
            return FakeHTTPResponse(payload={"ok": True, "ts": payload.get("ts")})
        if url.endswith("/chat.postMessage"):
            confirm_slack_calls.append({"method": "chat.postMessage", "payload": payload})
            return FakeHTTPResponse(payload={"ok": True, "ts": "1710000400.000100"})
        raise AssertionError(f"unexpected Slack API call: {url}")

    def fake_worker_runner_kick(request_id):
        worker_runner_kicks.append(request_id)
        return {"scheduled": True, "request_id": request_id, "mode": "fake"}

    slack_onboarding_api.urllib.request.urlopen = fake_confirm_status_post
    slack_onboarding_api._kick_worker_runner = fake_worker_runner_kick
    r = anon.post("/slack/events", content=confirm_body, headers=confirm_headers)
finally:
    slack_onboarding_api.urllib.request.urlopen = orig_confirm_urlopen
    if orig_confirm_runner_kick is None:
        try:
            delattr(slack_onboarding_api, "_kick_worker_runner")
        except AttributeError:
            pass
    else:
        slack_onboarding_api._kick_worker_runner = orig_confirm_runner_kick
    if saved_confirm_dry_run is None:
        os.environ.pop("HERMES_AX_SLACK_DRY_RUN", None)
    else:
        os.environ["HERMES_AX_SLACK_DRY_RUN"] = saved_confirm_dry_run
    if saved_confirm_ax_bot_token is None:
        os.environ.pop("HERMES_AX_SLACK_BOT_TOKEN", None)
    else:
        os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = saved_confirm_ax_bot_token
    if saved_confirm_slack_bot_token is None:
        os.environ.pop("SLACK_BOT_TOKEN", None)
    else:
        os.environ["SLACK_BOT_TOKEN"] = saved_confirm_slack_bot_token
check("Slack material confirmation reply status", r.status_code == 200, f"got {r.status_code}: {r.text}")
confirm_result = r.json()
check("Slack material confirmation reply stored", confirm_result.get("material_status") == "confirmed", str(confirm_result))
check("Slack material confirmation starts worker", "자료조사 worker" in confirm_result.get("message", "") and confirm_result.get("current_stage_id") == "p_research_running", str(confirm_result))
check("Slack material confirmation posts new worker status message", [c["method"] for c in confirm_slack_calls] == ["chat.postMessage"], confirm_slack_calls)
check("Slack material confirmation does not edit material question message", all(c["payload"].get("ts") != question_message_ts for c in confirm_slack_calls if c["method"] == "chat.update"), {"question_message_ts": question_message_ts, "calls": confirm_slack_calls})
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
    check("Slack material confirmation kicks queued worker runner", worker_runner_kicks == ([research_request["id"]] if research_request else []), {"request": dict(research_request) if research_request else None, "kicks": worker_runner_kicks})
    check("Worker research payload is standardized", research_payload.get("schema_version") == 1 and research_payload.get("task_type") == "initial_research" and research_payload.get("workflow_id") == slack_wf_id and research_payload.get("stage_id") == "p_research_running", research_payload)
    check("Worker research payload includes Slack and source files", research_payload.get("slack", {}).get("channel_id") == "CLOCALTEST" and len(research_payload.get("source_files", [])) == 2, research_payload)
    check("Worker research payload includes prompt and engine metadata", research_payload.get("research_engine") == "mock" and research_payload.get("prompt", {}).get("source") == "skills" and research_payload.get("prompt", {}).get("skill_id"), research_payload)

    four_wf_id = "wi_four_source_payload"
    four_mapping_id = "scpm_four_source_payload"
    now = plugin_api._now()
    tmpl = conn.execute("SELECT * FROM workflow_templates WHERE id=?", ("planning_research_mvp_v1",)).fetchone()
    conn.execute(
        """INSERT INTO workflow_instances
           (id, template_id, agent_type_id, title, current_stage_id, status, priority, assignee, metadata_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            four_wf_id,
            "planning_research_mvp_v1",
            tmpl["agent_type_id"],
            "[세라트젠] 기획 자료조사",
            "p_material_waiting",
            "active",
            0,
            "기획팀 임팀장",
            json.dumps({"company_name": "세라트젠", "project_key": "planning-research:세라트젠"}, ensure_ascii=False),
            now,
            now,
        ),
    )
    conn.execute(
        """INSERT INTO slack_channel_project_mappings
           (id, team_id, enterprise_id, channel_id, channel_name, normalized_channel_name, company_name,
            project_key, workflow_id, status, onboarding_message, onboarding_message_ts, onboarding_message_sent_at,
            first_event_id, last_event_id, last_error, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            four_mapping_id,
            "TLOCAL",
            "",
            "CFOURSOURCE",
            "세라트젠",
            "세라트젠",
            "세라트젠",
            "planning-research:세라트젠",
            four_wf_id,
            "active",
            "",
            "",
            None,
            "EvFOURONBOARD",
            "EvFOURCONFIRM",
            "",
            now,
            now,
        ),
    )
    for index, original_name in enumerate([
        "국내외 오가노이드 관련 기업, 연구소 현황.pdf",
        "기관투자자 요청자료.pdf",
        "기관투자자 추가질의 및 답변.pdf",
        "IR Book_Jan.2026_압축본.pdf",
    ], start=1):
        conn.execute(
            """INSERT INTO slack_workflow_source_files
               (id, mapping_id, workflow_id, artifact_id, slack_file_id, filename, title, mimetype, size,
                url_private, url_private_download, uploaded_user, uploaded_ts, status, rejection_reason,
                metadata_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"sfs_four_{index}",
                four_mapping_id,
                four_wf_id,
                None,
                f"FFOUR{index}",
                original_name,
                original_name,
                "application/pdf",
                1024 + index,
                f"https://slack.example/files/FFOUR{index}",
                f"https://slack.example/files/FFOUR{index}/download",
                "UCLIENTFOUR",
                f"1710000{index}",
                "stored",
                "",
                "{}",
                now,
                now,
            ),
        )
    four_mapping = conn.execute("SELECT * FROM slack_channel_project_mappings WHERE id=?", (four_mapping_id,)).fetchone()
    four_request = slack_onboarding_api._create_worker_request(conn, mapping=four_mapping, request_type="research", source_event_id="EvFOURCONFIRM")
    four_payload = json.loads(four_request["payload_json"])
    check(
        "Worker research payload keeps all four stored Slack source files",
        [item.get("filename") for item in four_payload.get("source_files", [])]
        == [
            "국내외 오가노이드 관련 기업, 연구소 현황.pdf",
            "기관투자자 요청자료.pdf",
            "기관투자자 추가질의 및 답변.pdf",
            "IR Book_Jan.2026_압축본.pdf",
        ],
        four_payload,
    )

    mapping_columns = {row[1] for row in conn.execute("PRAGMA table_info(slack_channel_project_mappings)").fetchall()}
    check("Schema exposes Slack notebook binding columns", "notebook_id" in mapping_columns or "notebook_binding_json" in mapping_columns, mapping_columns)

    notebook_bound_mapping_a = dict(four_mapping)
    notebook_bound_mapping_a.update({"channel_id": "CFOURSOURCE_A", "notebook_id": "nb_existing_channel"})
    notebook_bound_request_a = slack_onboarding_api._create_worker_request(conn, mapping=notebook_bound_mapping_a, request_type="research", source_event_id="EvFOURBINDINGA")
    notebook_bound_payload_a = json.loads(notebook_bound_request_a["payload_json"])
    check(
        "Worker research payload reuses existing notebook binding",
        notebook_bound_payload_a.get("notebook_id") == "nb_existing_channel"
        or notebook_bound_payload_a.get("notebook", {}).get("notebook_id") == "nb_existing_channel"
        or notebook_bound_payload_a.get("notebook_binding", {}).get("notebook_id") == "nb_existing_channel",
        notebook_bound_payload_a,
    )

    notebook_bound_mapping_b = dict(four_mapping)
    notebook_bound_mapping_b.update({"channel_id": "CFOURSOURCE_B", "notebook_id": "nb_other_channel"})
    notebook_bound_request_b = slack_onboarding_api._create_worker_request(conn, mapping=notebook_bound_mapping_b, request_type="research", source_event_id="EvFOURBINDINGB")
    notebook_bound_payload_b = json.loads(notebook_bound_request_b["payload_json"])
    check(
        "Slack channel notebook bindings stay isolated per channel",
        notebook_bound_payload_a.get("notebook_id") == "nb_existing_channel"
        and notebook_bound_payload_b.get("notebook_id") == "nb_other_channel"
        and notebook_bound_payload_a.get("notebook_id") != notebook_bound_payload_b.get("notebook_id"),
        {"channel_a": notebook_bound_payload_a, "channel_b": notebook_bound_payload_b},
    )

research_request_id = research_request["id"] if research_request else "missing-research-request"
r = client.post(f"/worker/requests/{research_request_id}/run")
check("Worker request runner status", r.status_code == 200, f"got {r.status_code}: {r.text}")
worker_result = r.json()
check("Worker request runner used mock engine", worker_result.get("engine_used") == "mock" and worker_result.get("request_status") == "completed", str(worker_result))
check("Worker request runner returns artifact", worker_result.get("artifact_id", "").startswith("art_"), str(worker_result))
check("Worker request runner posts Slack review message", worker_result.get("message_sent") is True and "자료조사 결과" in worker_result.get("message", "") and "검토" in worker_result.get("message", ""), str(worker_result))
check("Worker request runner moves workflow to review", worker_result.get("current_stage_id") == "p_user_review_waiting", str(worker_result))
duplicate_run = client.post(f"/worker/requests/{research_request_id}/run")
check("Worker request runner prevents duplicate execution", duplicate_run.status_code == 409, f"got {duplicate_run.status_code}: {duplicate_run.text}")
with plugin_api.get_db() as conn:
    report_artifact = conn.execute("SELECT * FROM artifacts WHERE workflow_id=? AND artifact_type='research_report' AND stage_id='p_user_review_waiting' ORDER BY created_at DESC LIMIT 1", (slack_wf_id,)).fetchone()
    wf_review = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (slack_wf_id,)).fetchone()
    result_activity = conn.execute("SELECT * FROM activity_logs WHERE workflow_id=? AND action=?", (slack_wf_id, "slack.worker_result_received")).fetchone()
    review_progress = conn.execute("SELECT * FROM slack_material_collection_states WHERE workflow_id=?", (slack_wf_id,)).fetchone()
    check("Worker result creates research report artifact", report_artifact is not None and "테스트전자 자료조사 결과" in report_artifact["title"], dict(report_artifact) if report_artifact else "")
    check("Worker result review state persisted", wf_review["current_stage_id"] == "p_user_review_waiting" and wf_review["assignee"] == "기획팀 임팀장", dict(wf_review))
    check("Worker result updates Slack progress state", review_progress is not None and review_progress["status"] == "review_waiting" and review_progress["last_message_ts"] == worker_result.get("message_ts"), dict(review_progress) if review_progress else "")
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
    final_report = conn.execute("SELECT * FROM artifacts WHERE workflow_id=? AND artifact_type='research_report' AND is_latest=1", (slack_wf_id,)).fetchone()
    confirmed_progress = conn.execute("SELECT * FROM slack_material_collection_states WHERE workflow_id=?", (slack_wf_id,)).fetchone()
    check("Slack review confirmation workflow completed", wf_confirmed["current_stage_id"] == "p_research_confirmed" and wf_confirmed["status"] == "completed", dict(wf_confirmed))
    check("Slack review confirmation marks latest report final", final_report is not None and final_report["status"] == "final", dict(final_report) if final_report else "")
    check("Slack review confirmation updates progress message", confirmed_progress is not None and confirmed_progress["status"] == "research_confirmed" and confirmed_progress["last_message_ts"] == review_confirm_result.get("message_ts"), dict(confirmed_progress) if confirmed_progress else "")
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
revision_initial_result_payload = {
    "request_id": revision_initial_request_id,
    "workflow_id": revision_wf_id,
    "status": "succeeded",
    "title": "수정테스트 자료조사 결과",
    "content": "## 수정테스트 자료조사 결과\n\n초안입니다.",
    "metadata": {"notebook_id": "nb_created_initial"},
}
r = client.post("/worker/results", json={
    "workflow_id": revision_wf_id,
    "status": "succeeded",
    "title": "request_id 누락 결과",
    "content": "request_id가 없어야 실패합니다.",
})
check("Worker result missing request_id rejected", r.status_code == 400, f"got {r.status_code}: {r.text}")
r = client.post("/worker/results", json=revision_initial_result_payload)
check("Worker result requires running request", r.status_code == 409, f"got {r.status_code}: {r.text}")
mark_worker_request_running(revision_initial_request_id)
r = client.post("/worker/results", json=revision_initial_result_payload)
check("Revision workflow initial worker result status", r.status_code == 200, f"got {r.status_code}: {r.text}")
with plugin_api.get_db() as conn:
    replay_artifact_count = conn.execute("SELECT count(*) FROM artifacts WHERE workflow_id=? AND artifact_type='research_report'", (revision_wf_id,)).fetchone()[0]
    replay_result_count = conn.execute("SELECT count(*) FROM planning_worker_results WHERE request_id=?", (revision_initial_request_id,)).fetchone()[0]
    replay_activity_count = conn.execute("SELECT count(*) FROM activity_logs WHERE workflow_id=? AND action='slack.worker_result_received'", (revision_wf_id,)).fetchone()[0]
r = client.post("/worker/results", json=revision_initial_result_payload)
check("Worker result replay rejected", r.status_code == 409, f"got {r.status_code}: {r.text}")
with plugin_api.get_db() as conn:
    replay_artifact_count_after = conn.execute("SELECT count(*) FROM artifacts WHERE workflow_id=? AND artifact_type='research_report'", (revision_wf_id,)).fetchone()[0]
    replay_result_count_after = conn.execute("SELECT count(*) FROM planning_worker_results WHERE request_id=?", (revision_initial_request_id,)).fetchone()[0]
    replay_activity_count_after = conn.execute("SELECT count(*) FROM activity_logs WHERE workflow_id=? AND action='slack.worker_result_received'", (revision_wf_id,)).fetchone()[0]
check(
    "Worker result replay creates no duplicate artifacts or messages",
    replay_artifact_count_after == replay_artifact_count and replay_result_count_after == replay_result_count and replay_activity_count_after == replay_activity_count,
    {
        "before": (replay_artifact_count, replay_result_count, replay_activity_count),
        "after": (replay_artifact_count_after, replay_result_count_after, replay_activity_count_after),
    },
)
revision_text_payload = slack_message_text_payload("EvREVISIONTEXT1", "시장 규모와 경쟁사 비교를 더 보강해주세요.", channel_id="CREVTEST")
revision_text_body, revision_text_headers = slack_headers(revision_text_payload)
orig_revision_text_runner_kick = getattr(slack_onboarding_api, "_kick_worker_runner", None)
orig_revision_text_urlopen = slack_onboarding_api.urllib.request.urlopen
saved_revision_text_dry_run = os.environ.get("HERMES_AX_SLACK_DRY_RUN")
saved_revision_text_ax_bot_token = os.environ.get("HERMES_AX_SLACK_BOT_TOKEN")
saved_revision_text_slack_bot_token = os.environ.get("SLACK_BOT_TOKEN")
revision_text_runner_kicks = []
revision_text_slack_calls = []
try:
    os.environ["HERMES_AX_SLACK_DRY_RUN"] = "false"
    os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = "test-bot-token"
    os.environ.pop("SLACK_BOT_TOKEN", None)

    def fake_revision_text_slack(req, timeout=None):
        url = request_url(req)
        payload = request_json(req)
        if url.endswith("/chat.update"):
            revision_text_slack_calls.append({"method": "chat.update", "payload": payload})
            return FakeHTTPResponse(payload={"ok": True, "ts": payload.get("ts")})
        if url.endswith("/chat.postMessage"):
            revision_text_slack_calls.append({"method": "chat.postMessage", "payload": payload})
            return FakeHTTPResponse(payload={"ok": True, "ts": "1710000500.000100"})
        raise AssertionError(f"unexpected Slack API call: {url}")

    def fake_revision_text_runner_kick(request_id):
        revision_text_runner_kicks.append(request_id)
        return {"scheduled": True, "request_id": request_id, "mode": "fake"}

    slack_onboarding_api.urllib.request.urlopen = fake_revision_text_slack
    slack_onboarding_api._kick_worker_runner = fake_revision_text_runner_kick
    r = anon.post("/slack/events", content=revision_text_body, headers=revision_text_headers)
finally:
    slack_onboarding_api.urllib.request.urlopen = orig_revision_text_urlopen
    if orig_revision_text_runner_kick is None:
        try:
            delattr(slack_onboarding_api, "_kick_worker_runner")
        except AttributeError:
            pass
    else:
        slack_onboarding_api._kick_worker_runner = orig_revision_text_runner_kick
    if saved_revision_text_dry_run is None:
        os.environ.pop("HERMES_AX_SLACK_DRY_RUN", None)
    else:
        os.environ["HERMES_AX_SLACK_DRY_RUN"] = saved_revision_text_dry_run
    if saved_revision_text_ax_bot_token is None:
        os.environ.pop("HERMES_AX_SLACK_BOT_TOKEN", None)
    else:
        os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = saved_revision_text_ax_bot_token
    if saved_revision_text_slack_bot_token is None:
        os.environ.pop("SLACK_BOT_TOKEN", None)
    else:
        os.environ["SLACK_BOT_TOKEN"] = saved_revision_text_slack_bot_token
check("Slack review revision text status", r.status_code == 200, f"got {r.status_code}: {r.text}")
revision_text_result = r.json()
check("Slack review free-text creates revision request", revision_text_result.get("review_status") == "revision_requested" and revision_text_result.get("current_stage_id") == "p_revision_running", str(revision_text_result))
check("Slack review revision text posts a new worker handoff message", [c["method"] for c in revision_text_slack_calls] == ["chat.postMessage"], revision_text_slack_calls)
with plugin_api.get_db() as conn:
    revision_request = fetch_worker_request(conn, revision_wf_id, "revision")
    revision_payload = json.loads(revision_request["payload_json"]) if revision_request else {}
    revision_activity = conn.execute("SELECT * FROM activity_logs WHERE workflow_id=? AND action=?", (revision_wf_id, "slack.revision_requested")).fetchone()
    check("Revision text worker request payload stored", revision_request is not None and revision_payload.get("task_type") == "revision" and "시장 규모" in revision_payload.get("revision", {}).get("instruction", ""), revision_payload)
    check("Revision text activity logged", revision_activity is not None, dict(revision_activity) if revision_activity else "")
revision_request_id = revision_request["id"] if revision_request else "missing-revision-request"
check(
    "Slack review revision text schedules worker runner",
    revision_request is not None
    and revision_text_result.get("worker_runner_scheduled") is True
    and revision_text_result.get("worker_runner_mode") == "fake"
    and revision_text_runner_kicks == [revision_request_id],
    {"response": revision_text_result, "request_id": revision_request_id, "runner_kicks": revision_text_runner_kicks},
)
mark_worker_request_running(revision_request_id)
orig_revision_result_urlopen = slack_onboarding_api.urllib.request.urlopen
saved_revision_result_dry_run = os.environ.get("HERMES_AX_SLACK_DRY_RUN")
saved_revision_result_ax_bot_token = os.environ.get("HERMES_AX_SLACK_BOT_TOKEN")
saved_revision_result_slack_bot_token = os.environ.get("SLACK_BOT_TOKEN")
revision_result_slack_calls = []
try:
    os.environ["HERMES_AX_SLACK_DRY_RUN"] = "false"
    os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = "test-bot-token"
    os.environ.pop("SLACK_BOT_TOKEN", None)

    def fake_revision_result_slack(req, timeout=None):
        url = request_url(req)
        payload = request_json(req)
        if url.endswith("/chat.update"):
            revision_result_slack_calls.append({"method": "chat.update", "payload": payload})
            return FakeHTTPResponse(payload={"ok": True, "ts": payload.get("ts")})
        if url.endswith("/chat.postMessage"):
            revision_result_slack_calls.append({"method": "chat.postMessage", "payload": payload})
            return FakeHTTPResponse(payload={"ok": True, "ts": "1710000500.000200"})
        raise AssertionError(f"unexpected Slack API call: {url}")

    slack_onboarding_api.urllib.request.urlopen = fake_revision_result_slack
    r = client.post("/worker/results", json={
        "request_id": revision_request_id,
        "workflow_id": revision_wf_id,
        "status": "succeeded",
        "title": "수정테스트 자료조사 수정본",
        "content": "## 수정테스트 자료조사 수정본\n\n시장 규모와 경쟁사 비교를 보강했습니다.",
    })
finally:
    slack_onboarding_api.urllib.request.urlopen = orig_revision_result_urlopen
    if saved_revision_result_dry_run is None:
        os.environ.pop("HERMES_AX_SLACK_DRY_RUN", None)
    else:
        os.environ["HERMES_AX_SLACK_DRY_RUN"] = saved_revision_result_dry_run
    if saved_revision_result_ax_bot_token is None:
        os.environ.pop("HERMES_AX_SLACK_BOT_TOKEN", None)
    else:
        os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = saved_revision_result_ax_bot_token
    if saved_revision_result_slack_bot_token is None:
        os.environ.pop("SLACK_BOT_TOKEN", None)
    else:
        os.environ["SLACK_BOT_TOKEN"] = saved_revision_result_slack_bot_token
check("Revision worker result returns to review", r.status_code == 200 and r.json().get("current_stage_id") == "p_user_review_waiting", f"got {r.status_code}: {r.text}")
check("Revision worker result posts a new completion message", [c["method"] for c in revision_result_slack_calls] == ["chat.postMessage"], revision_result_slack_calls)
revision_file_payload = slack_message_single_file_payload("EvREVISIONFILE1", channel_id="CREVTEST", file_id="FREVISIONDOC")
revision_file_body, revision_file_headers = slack_headers(revision_file_payload)
orig_revision_file_runner_kick = getattr(slack_onboarding_api, "_kick_worker_runner", None)
orig_revision_file_urlopen = slack_onboarding_api.urllib.request.urlopen
saved_revision_file_dry_run = os.environ.get("HERMES_AX_SLACK_DRY_RUN")
saved_revision_file_ax_bot_token = os.environ.get("HERMES_AX_SLACK_BOT_TOKEN")
saved_revision_file_slack_bot_token = os.environ.get("SLACK_BOT_TOKEN")
revision_file_runner_kicks = []
revision_file_slack_calls = []
try:
    os.environ["HERMES_AX_SLACK_DRY_RUN"] = "false"
    os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = "test-bot-token"
    os.environ.pop("SLACK_BOT_TOKEN", None)

    def fake_revision_file_slack(req, timeout=None):
        url = request_url(req)
        payload = request_json(req)
        if url.endswith("/chat.update"):
            revision_file_slack_calls.append({"method": "chat.update", "payload": payload})
            return FakeHTTPResponse(payload={"ok": True, "ts": payload.get("ts")})
        if url.endswith("/chat.postMessage"):
            revision_file_slack_calls.append({"method": "chat.postMessage", "payload": payload})
            return FakeHTTPResponse(payload={"ok": True, "ts": "1710000500.000300"})
        raise AssertionError(f"unexpected Slack API call: {url}")

    def fake_revision_file_runner_kick(request_id):
        revision_file_runner_kicks.append(request_id)
        return {"scheduled": True, "request_id": request_id, "mode": "fake"}

    slack_onboarding_api.urllib.request.urlopen = fake_revision_file_slack
    slack_onboarding_api._kick_worker_runner = fake_revision_file_runner_kick
    r = anon.post("/slack/events", content=revision_file_body, headers=revision_file_headers)
finally:
    slack_onboarding_api.urllib.request.urlopen = orig_revision_file_urlopen
    if orig_revision_file_runner_kick is None:
        try:
            delattr(slack_onboarding_api, "_kick_worker_runner")
        except AttributeError:
            pass
    else:
        slack_onboarding_api._kick_worker_runner = orig_revision_file_runner_kick
    if saved_revision_file_dry_run is None:
        os.environ.pop("HERMES_AX_SLACK_DRY_RUN", None)
    else:
        os.environ["HERMES_AX_SLACK_DRY_RUN"] = saved_revision_file_dry_run
    if saved_revision_file_ax_bot_token is None:
        os.environ.pop("HERMES_AX_SLACK_BOT_TOKEN", None)
    else:
        os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = saved_revision_file_ax_bot_token
    if saved_revision_file_slack_bot_token is None:
        os.environ.pop("SLACK_BOT_TOKEN", None)
    else:
        os.environ["SLACK_BOT_TOKEN"] = saved_revision_file_slack_bot_token
check("Slack review attached revision file status", r.status_code == 200, f"got {r.status_code}: {r.text}")
revision_file_result = r.json()
check("Slack review attached file creates revision request", revision_file_result.get("review_status") == "revision_requested" and revision_file_result.get("current_stage_id") == "p_revision_running", str(revision_file_result))
check("Slack review attached file posts a new worker handoff message", [c["method"] for c in revision_file_slack_calls] == ["chat.postMessage"], revision_file_slack_calls)
with plugin_api.get_db() as conn:
    revision_file_request = fetch_worker_request(conn, revision_wf_id, "revision")
    revision_file_payload_json = json.loads(revision_file_request["payload_json"]) if revision_file_request else {}
    check("Revision file worker payload includes attachment", any(f.get("filename") == "revision-notes.md" for f in revision_file_payload_json.get("revision", {}).get("attachments", [])), revision_file_payload_json)
    revision_mapping_columns = {row[1] for row in conn.execute("PRAGMA table_info(slack_channel_project_mappings)").fetchall()}
    if revision_file_request and "notebook_id" in revision_mapping_columns:
        revision_mapping = conn.execute("SELECT * FROM slack_channel_project_mappings WHERE id=?", (revision_file_request["mapping_id"],)).fetchone()
        check(
            "Worker result notebook metadata persisted to mapping row",
            revision_mapping is not None and revision_mapping["notebook_id"] == "nb_created_initial",
            dict(revision_mapping) if revision_mapping else "",
        )
    else:
        check("Worker result notebook metadata persisted to mapping row", False, revision_mapping_columns)
    check(
        "Revision worker payload reuses notebook_id from worker result metadata",
        revision_file_payload_json.get("notebook_id") == "nb_created_initial"
        or revision_file_payload_json.get("notebook", {}).get("notebook_id") == "nb_created_initial"
        or revision_file_payload_json.get("notebook_binding", {}).get("notebook_id") == "nb_created_initial",
        revision_file_payload_json,
    )
revision_file_request_id = revision_file_request["id"] if revision_file_request else "missing-revision-file-request"
check(
    "Slack review attachment schedules worker runner",
    revision_file_request is not None
    and revision_file_result.get("worker_runner_scheduled") is True
    and revision_file_result.get("worker_runner_mode") == "fake"
    and revision_file_runner_kicks == [revision_file_request_id],
    {"response": revision_file_result, "request_id": revision_file_request_id, "runner_kicks": revision_file_runner_kicks},
)
mark_worker_request_running(revision_file_request_id)
worker_failure_payload = {
    "request_id": revision_file_request_id,
    "workflow_id": revision_wf_id,
    "status": "failed",
    "error": "NotebookLM auth expired cookie token /tmp/secret-storage.json",
}
orig_revision_failure_urlopen = slack_onboarding_api.urllib.request.urlopen
saved_revision_failure_dry_run = os.environ.get("HERMES_AX_SLACK_DRY_RUN")
saved_revision_failure_ax_bot_token = os.environ.get("HERMES_AX_SLACK_BOT_TOKEN")
saved_revision_failure_slack_bot_token = os.environ.get("SLACK_BOT_TOKEN")
revision_failure_slack_calls = []
try:
    os.environ["HERMES_AX_SLACK_DRY_RUN"] = "false"
    os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = "test-bot-token"
    os.environ.pop("SLACK_BOT_TOKEN", None)

    def fake_revision_failure_slack(req, timeout=None):
        url = request_url(req)
        payload = request_json(req)
        if url.endswith("/chat.update"):
            revision_failure_slack_calls.append({"method": "chat.update", "payload": payload})
            return FakeHTTPResponse(payload={"ok": True, "ts": payload.get("ts")})
        if url.endswith("/chat.postMessage"):
            revision_failure_slack_calls.append({"method": "chat.postMessage", "payload": payload})
            return FakeHTTPResponse(payload={"ok": True, "ts": "1710000500.000400"})
        raise AssertionError(f"unexpected Slack API call: {url}")

    slack_onboarding_api.urllib.request.urlopen = fake_revision_failure_slack
    r = client.post("/worker/results", json=worker_failure_payload)
finally:
    slack_onboarding_api.urllib.request.urlopen = orig_revision_failure_urlopen
    if saved_revision_failure_dry_run is None:
        os.environ.pop("HERMES_AX_SLACK_DRY_RUN", None)
    else:
        os.environ["HERMES_AX_SLACK_DRY_RUN"] = saved_revision_failure_dry_run
    if saved_revision_failure_ax_bot_token is None:
        os.environ.pop("HERMES_AX_SLACK_BOT_TOKEN", None)
    else:
        os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = saved_revision_failure_ax_bot_token
    if saved_revision_failure_slack_bot_token is None:
        os.environ.pop("SLACK_BOT_TOKEN", None)
    else:
        os.environ["SLACK_BOT_TOKEN"] = saved_revision_failure_slack_bot_token
check("Worker failure receipt status", r.status_code == 200, f"got {r.status_code}: {r.text}")
worker_failure = r.json()
check("Worker failure sends understandable Slack message", worker_failure.get("ok") is True and worker_failure.get("message_sent") is True and "오류" in worker_failure.get("message", ""), str(worker_failure))
check("Worker failure hides internal diagnostics from Slack message", all(term not in worker_failure.get("message", "") for term in ("NotebookLM", "cookie", "token", "/tmp/secret")), str(worker_failure))
check("Revision worker failure posts a new failure message", [c["method"] for c in revision_failure_slack_calls] == ["chat.postMessage"], revision_failure_slack_calls)
with plugin_api.get_db() as conn:
    failed_activity_count = conn.execute("SELECT count(*) FROM activity_logs WHERE workflow_id=? AND action='slack.worker_result_failed'", (revision_wf_id,)).fetchone()[0]
r = client.post("/worker/results", json=worker_failure_payload)
check("Worker failure replay rejected", r.status_code == 409, f"got {r.status_code}: {r.text}")
with plugin_api.get_db() as conn:
    failed_request = conn.execute("SELECT * FROM planning_worker_requests WHERE id=?", (revision_file_request_id,)).fetchone()
    failure_activity = conn.execute("SELECT * FROM activity_logs WHERE workflow_id=? AND action=?", (revision_wf_id, "slack.worker_result_failed")).fetchone()
    failed_activity_count_after = conn.execute("SELECT count(*) FROM activity_logs WHERE workflow_id=? AND action='slack.worker_result_failed'", (revision_wf_id,)).fetchone()[0]
    check("Worker failure request marked failed", failed_request is not None and failed_request["status"] == "failed", dict(failed_request) if failed_request else "")
    check("Worker failure replay creates no duplicate message", failed_activity_count_after == failed_activity_count, {"before": failed_activity_count, "after": failed_activity_count_after})
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

print("\n=== Slack PDF File Downloads ===")
pdf_onboard_payload = slack_event_payload(event_id="EvPDFONBOARD1", channel_id="CPDFTEST", channel_name="PDF테스트")
pdf_onboard_body, pdf_onboard_headers = slack_headers(pdf_onboard_payload)
r = anon.post("/slack/events", content=pdf_onboard_body, headers=pdf_onboard_headers)
check("PDF workflow onboarding status", r.status_code == 200 and r.json().get("workflow_id"), f"got {r.status_code}: {r.text}")
pdf_wf_id = r.json().get("workflow_id")

saved_download_files = os.environ.get("HERMES_AX_SLACK_DOWNLOAD_FILES")
saved_ax_bot_token = os.environ.get("HERMES_AX_SLACK_BOT_TOKEN")
saved_slack_bot_token = os.environ.get("SLACK_BOT_TOKEN")
orig_urlopen = slack_onboarding_api.urllib.request.urlopen
try:
    os.environ["HERMES_AX_SLACK_DRY_RUN"] = "false"
    os.environ["HERMES_AX_SLACK_DOWNLOAD_FILES"] = "true"
    os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = "test-bot-token"
    os.environ.pop("SLACK_BOT_TOKEN", None)
    download_calls = []
    post_calls = []

    def fake_pdf_download(req, timeout=None):
        url = request_url(req)
        auth = req.headers.get("Authorization") or req.headers.get("authorization")
        if url == "https://slack.example/files/FDOWNLOADPDF/download":
            download_calls.append({"url": url, "auth": auth})
            return FakeHTTPResponse(body=b"%PDF-1.7\nreal downloaded pdf bytes")
        if url.endswith("/chat.postMessage"):
            post_calls.append({"url": url, "auth": auth, "payload": request_json(req)})
            return FakeHTTPResponse(payload={"ok": True, "ts": "1710000300.000100"})
        raise AssertionError(f"unexpected Slack API call: {url}")

    slack_onboarding_api.urllib.request.urlopen = fake_pdf_download
    download_payload = slack_message_pdf_file_payload(
        "EvPDFDOWNLOAD1",
        channel_id="CPDFTEST",
        file_id="FDOWNLOADPDF",
        filename="downloaded.pdf",
        title="다운로드 PDF",
        url_private="https://slack.example/files/FDOWNLOADPDF",
        url_private_download="https://slack.example/files/FDOWNLOADPDF/download",
    )
    download_body, download_headers = slack_headers(download_payload)
    r = anon.post("/slack/events", content=download_body, headers=download_headers)
    check("Slack PDF download event status", r.status_code == 200 and r.json().get("stored_count") == 1, f"got {r.status_code}: {r.text}")
    source, artifact = fetch_source_artifact("FDOWNLOADPDF")
    file_response = client.get(f"/artifacts/{artifact['id']}/file") if artifact else None
    metadata = json.loads(source["metadata_json"]) if source else {}
    expected_download_auth = "Bearer " + os.environ["HERMES_AX_SLACK_BOT_TOKEN"]
    check("Slack PDF download uses url_private_download with bot token", download_calls == [{"url": "https://slack.example/files/FDOWNLOADPDF/download", "auth": expected_download_auth}], download_calls)
    check("Slack downloaded PDF bytes stored", file_response is not None and file_response.status_code == 200 and file_response.content.startswith(b"%PDF-"), file_response.content[:40] if file_response is not None else "missing")
    check("Slack downloaded PDF artifact remains linked", source is not None and artifact is not None and source["artifact_id"] == artifact["id"] and source["workflow_id"] == pdf_wf_id, (dict(source) if source else None, dict(artifact) if artifact else None))
    check("Slack downloaded PDF metadata preserved", metadata.get("file", {}).get("url_private_download", "").endswith("/download") and metadata.get("file", {}).get("id") == "FDOWNLOADPDF", metadata)

    os.environ["HERMES_AX_SLACK_DRY_RUN"] = "true"
    os.environ["HERMES_AX_SLACK_DOWNLOAD_FILES"] = "true"
    os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = "test-bot-token"
    dry_run_download_calls = []

    def fake_dry_run_download(req, timeout=None):
        dry_run_download_calls.append(request_url(req))
        return FakeHTTPResponse(body=b"%PDF-1.7\ndry-run should not download")

    slack_onboarding_api.urllib.request.urlopen = fake_dry_run_download
    dry_run_payload = slack_message_pdf_file_payload(
        "EvPDFDRYRUNSKIP",
        channel_id="CPDFTEST",
        file_id="FDRYRUNPDF",
        filename="dry-run.pdf",
        title="Dry-run PDF",
        url_private="https://slack.example/files/FDRYRUNPDF",
        url_private_download="https://slack.example/files/FDRYRUNPDF/download",
    )
    dry_run_body, dry_run_headers = slack_headers(dry_run_payload)
    r = anon.post("/slack/events", content=dry_run_body, headers=dry_run_headers)
    dry_source, dry_artifact = fetch_source_artifact("FDRYRUNPDF")
    dry_file_response = client.get(f"/artifacts/{dry_artifact['id']}/file") if dry_artifact else None
    check(
        "Slack PDF dry-run skips download network",
        r.status_code == 200
        and r.json().get("stored_count") == 1
        and dry_run_download_calls == []
        and dry_artifact is not None
        and dry_artifact["mime_type"] != "application/pdf"
        and dry_file_response is not None
        and dry_file_response.content.startswith(b"Slack file metadata manifest"),
        {
            "response": f"{r.status_code}: {r.text}",
            "network_calls": dry_run_download_calls,
            "source": dict(dry_source) if dry_source else None,
            "artifact": dict(dry_artifact) if dry_artifact else None,
            "file_prefix": dry_file_response.content[:40] if dry_file_response is not None else None,
        },
    )

    def check_pdf_manifest_fallback(label: str, *, event_id: str, file_id: str, env_download: str | None, token: str | None, url_private: str, url_private_download: str, fake_failure: bool = False):
        if env_download is None:
            os.environ.pop("HERMES_AX_SLACK_DOWNLOAD_FILES", None)
        else:
            os.environ["HERMES_AX_SLACK_DOWNLOAD_FILES"] = env_download
        if token is None:
            os.environ.pop("HERMES_AX_SLACK_BOT_TOKEN", None)
            os.environ.pop("SLACK_BOT_TOKEN", None)
        else:
            os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = token
            os.environ.pop("SLACK_BOT_TOKEN", None)
        if fake_failure:
            def failing_download(req, timeout=None):
                raise urllib.error.URLError("download failed")
            slack_onboarding_api.urllib.request.urlopen = failing_download
        else:
            slack_onboarding_api.urllib.request.urlopen = orig_urlopen
        payload = slack_message_pdf_file_payload(
            event_id,
            channel_id="CPDFTEST",
            file_id=file_id,
            filename=f"{file_id.lower()}.pdf",
            title=f"{label} PDF",
            url_private=url_private,
            url_private_download=url_private_download,
        )
        body, headers = slack_headers(payload)
        resp = anon.post("/slack/events", content=body, headers=headers)
        source_row, artifact_row = fetch_source_artifact(file_id)
        file_resp = client.get(f"/artifacts/{artifact_row['id']}/file") if artifact_row else None
        source_metadata = json.loads(source_row["metadata_json"]) if source_row else {}
        fallback_ok = (
            resp.status_code == 200
            and resp.json().get("stored_count") == 1
            and source_row is not None
            and artifact_row is not None
            and source_row["artifact_id"] == artifact_row["id"]
            and artifact_row["mime_type"] != "application/pdf"
            and artifact_row["content_type"] != "application/pdf"
            and file_resp is not None
            and file_resp.status_code == 200
            and file_resp.content.startswith(b"Slack file metadata manifest")
            and not file_resp.content.startswith(b"%PDF-")
            and source_metadata.get("file", {}).get("id") == file_id
        )
        check(f"Slack PDF manifest fallback for {label}", fallback_ok, {
            "response": f"{resp.status_code}: {resp.text}",
            "source": dict(source_row) if source_row else None,
            "artifact": dict(artifact_row) if artifact_row else None,
            "file_prefix": file_resp.content[:40] if file_resp is not None else None,
            "metadata": source_metadata,
        })

    check_pdf_manifest_fallback(
        "download disabled",
        event_id="EvPDFFALLBACKDISABLED",
        file_id="FPDFDISABLED",
        env_download="false",
        token="test-bot-token",
        url_private="https://slack.example/files/FPDFDISABLED",
        url_private_download="https://slack.example/files/FPDFDISABLED/download",
    )
    check_pdf_manifest_fallback(
        "missing token",
        event_id="EvPDFFALLBACKTOKEN",
        file_id="FPDFTOKEN",
        env_download="true",
        token=None,
        url_private="https://slack.example/files/FPDFTOKEN",
        url_private_download="https://slack.example/files/FPDFTOKEN/download",
    )
    check_pdf_manifest_fallback(
        "missing URL",
        event_id="EvPDFFALLBACKURL",
        file_id="FPDFNOURL",
        env_download="true",
        token="test-bot-token",
        url_private="",
        url_private_download="",
    )
    check_pdf_manifest_fallback(
        "download failure",
        event_id="EvPDFFALLBACKFAIL",
        file_id="FPDFFAIL",
        env_download="true",
        token="test-bot-token",
        url_private="https://slack.example/files/FPDFFAIL",
        url_private_download="https://slack.example/files/FPDFFAIL/download",
        fake_failure=True,
    )
finally:
    slack_onboarding_api.urllib.request.urlopen = orig_urlopen
    if saved_download_files is None:
        os.environ.pop("HERMES_AX_SLACK_DOWNLOAD_FILES", None)
    else:
        os.environ["HERMES_AX_SLACK_DOWNLOAD_FILES"] = saved_download_files
    if saved_ax_bot_token is None:
        os.environ.pop("HERMES_AX_SLACK_BOT_TOKEN", None)
    else:
        os.environ["HERMES_AX_SLACK_BOT_TOKEN"] = saved_ax_bot_token
    if saved_slack_bot_token is None:
        os.environ.pop("SLACK_BOT_TOKEN", None)
    else:
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

print("\n=== Delete Workflow Cascade ===")
r = client.post("/workflows", json={
    "template_id": "planning_research_mvp_v1",
    "title": "[삭제테스트] 기획 자료조사",
    "priority": 2,
    "assignee": "기획팀 임팀장",
})
check("POST delete-target workflow status", r.status_code == 200, f"got {r.status_code}: {r.text}")
delete_wf_id = r.json()["id"]
with plugin_api.get_db() as conn:
    now = plugin_api._now()
    mapping_id = "scpm_delete_cascade"
    request_id = "pwr_delete_cascade"
    conn.execute(
        """INSERT INTO slack_channel_project_mappings
           (id, team_id, channel_id, channel_name, normalized_channel_name, company_name, project_key,
            workflow_id, status, onboarding_message, first_event_id, last_event_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (mapping_id, "TDEL", "CDEL", "삭제테스트", "삭제테스트", "삭제테스트", "planning-research:삭제테스트",
         delete_wf_id, "active", "", "", "", now, now),
    )
    conn.execute(
        """INSERT INTO slack_workflow_source_files
           (id, mapping_id, workflow_id, artifact_id, slack_file_id, filename, title, mimetype, size,
            url_private, url_private_download, uploaded_user, uploaded_ts, status, rejection_reason,
            metadata_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("swf_delete_cascade", mapping_id, delete_wf_id, None, "FDEL", "delete.pdf", "삭제 테스트", "application/pdf", 123,
         "", "", "UDEL", "111.222", "stored", "", "{}", now, now),
    )
    conn.execute(
        """INSERT INTO slack_material_collection_states
           (workflow_id, mapping_id, status, source_file_count, rejected_file_count, last_message,
            last_message_ts, last_error, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (delete_wf_id, mapping_id, "pending_confirmation", 1, 0, "자료 확인", "111.333", "", now),
    )
    conn.execute(
        """INSERT INTO planning_worker_requests
           (id, workflow_id, mapping_id, request_type, status, payload_json, source_event_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (request_id, delete_wf_id, mapping_id, "research", "queued", "{}", "EvDEL", now, now),
    )
    conn.execute(
        """INSERT INTO planning_worker_results
           (id, request_id, workflow_id, result_type, artifact_id, payload_json, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        ("pwr_result_delete_cascade", request_id, delete_wf_id, "research_report", None, "{}", now),
    )
r = client.delete(f"/workflows/{delete_wf_id}")
check("DELETE workflow with Slack/worker rows status", r.status_code == 200, f"got {r.status_code}: {r.text}")
with plugin_api.get_db() as conn:
    workflow_count = conn.execute("SELECT count(*) FROM workflow_instances WHERE id=?", (delete_wf_id,)).fetchone()[0]
    mapping_count = conn.execute("SELECT count(*) FROM slack_channel_project_mappings WHERE workflow_id=?", (delete_wf_id,)).fetchone()[0]
    source_count = conn.execute("SELECT count(*) FROM slack_workflow_source_files WHERE workflow_id=?", (delete_wf_id,)).fetchone()[0]
    material_state_count = conn.execute("SELECT count(*) FROM slack_material_collection_states WHERE workflow_id=?", (delete_wf_id,)).fetchone()[0]
    worker_request_count = conn.execute("SELECT count(*) FROM planning_worker_requests WHERE workflow_id=?", (delete_wf_id,)).fetchone()[0]
    worker_result_count = conn.execute("SELECT count(*) FROM planning_worker_results WHERE workflow_id=?", (delete_wf_id,)).fetchone()[0]
check("deleted workflow row removed", workflow_count == 0, f"got {workflow_count}")
check("deleted workflow Slack mapping rows removed", mapping_count == 0, f"got {mapping_count}")
check("deleted workflow source file rows removed", source_count == 0, f"got {source_count}")
check("deleted workflow material state removed", material_state_count == 0, f"got {material_state_count}")
check("deleted workflow worker request rows removed", worker_request_count == 0, f"got {worker_request_count}")
check("deleted workflow worker result rows removed", worker_result_count == 0, f"got {worker_result_count}")

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
check("schema v9 migration sets user_version", migration_conn.execute("PRAGMA user_version").fetchone()[0] >= 9)
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
slack_mapping_columns = {row[1] for row in migration_conn.execute("PRAGMA table_info(slack_channel_project_mappings)").fetchall()}
check("schema v9 adds Slack notebook binding column", "notebook_id" in slack_mapping_columns, slack_mapping_columns)
migration_conn.close()

legacy_seed_conn = sqlite3.connect(":memory:")
legacy_seed_conn.row_factory = sqlite3.Row
legacy_seed_conn.executescript(db_schema.SCHEMA_SQL)
legacy_seed_conn.execute(
    "INSERT INTO agent_types (id, name, description, icon, color, config_json, created_at) VALUES (?,?,?,?,?,?,?)",
    ("marketing", "Marketing Agent", "Legacy production seed", "Megaphone", "#f97316", "{}", "2025-01-01T00:00:00Z"),
)
legacy_seed_conn.execute(
    "INSERT INTO skills (id, name, description, content, agent_type_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
    (
        "skill_001",
        "초기 연락 이메일 작성",
        "Legacy wrong planning skill row",
        "# 초기 연락 이메일 작성\n\n회사에 보낼 이메일을 작성합니다.",
        "sales",
        "2025-01-01T00:00:00Z",
        "2025-01-01T00:00:00Z",
    ),
)
plugin_api.seed_if_empty(legacy_seed_conn, plugin_api._now, lambda *args, **kwargs: None)
planning_agent = legacy_seed_conn.execute("SELECT * FROM agent_types WHERE id='planning'").fetchone()
planning_template = legacy_seed_conn.execute("SELECT * FROM workflow_templates WHERE id='planning_research_mvp_v1'").fetchone()
planning_stage_count = legacy_seed_conn.execute("SELECT count(*) FROM stage_definitions WHERE template_id='planning_research_mvp_v1'").fetchone()[0]
research_skill = legacy_seed_conn.execute("SELECT * FROM skills WHERE id='skill_001'").fetchone()
legacy_agent = legacy_seed_conn.execute("SELECT * FROM agent_types WHERE id='marketing'").fetchone()
check("existing DB seed preserves legacy agent", legacy_agent is not None and legacy_agent["name"] == "Marketing Agent", dict(legacy_agent) if legacy_agent else "")
check("existing DB seed adds planning agent", planning_agent is not None, "planning missing")
check("existing DB seed adds planning template", planning_template is not None, "planning_research_mvp_v1 missing")
check("existing DB seed adds planning stages", planning_stage_count == 6, f"got {planning_stage_count}")
check("existing DB seed repairs stale research skill", research_skill is not None and research_skill["name"] == "기획 자료조사 결과 정리" and research_skill["agent_type_id"] == "planning", dict(research_skill) if research_skill else "")
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
