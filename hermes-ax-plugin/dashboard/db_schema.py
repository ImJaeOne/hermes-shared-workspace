from __future__ import annotations

import json
import sqlite3

SCHEMA_VERSION = 8

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_types (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    icon TEXT NOT NULL DEFAULT 'Bot',
    color TEXT NOT NULL DEFAULT '#6366f1',
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_templates (
    id TEXT PRIMARY KEY,
    agent_type_id TEXT NOT NULL REFERENCES agent_types(id),
    name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stage_definitions (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL REFERENCES workflow_templates(id),
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    stage_order INTEGER NOT NULL,
    expected_artifacts TEXT NOT NULL DEFAULT '[]',
    trigger_conditions TEXT NOT NULL DEFAULT '{}',
    transition_mode TEXT NOT NULL DEFAULT 'auto',
    approval_roles TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_instances (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL REFERENCES workflow_templates(id),
    agent_type_id TEXT NOT NULL REFERENCES agent_types(id),
    title TEXT NOT NULL,
    current_stage_id TEXT NOT NULL REFERENCES stage_definitions(id),
    status TEXT NOT NULL DEFAULT 'active',
    priority INTEGER NOT NULL DEFAULT 0,
    assignee TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stage_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL REFERENCES workflow_instances(id),
    from_stage_id TEXT,
    to_stage_id TEXT NOT NULL REFERENCES stage_definitions(id),
    triggered_by TEXT NOT NULL DEFAULT 'system',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflow_instances(id),
    stage_id TEXT NOT NULL REFERENCES stage_definitions(id),
    artifact_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'text/markdown',
    status TEXT NOT NULL DEFAULT 'draft',
    file_path TEXT NOT NULL DEFAULT '',
    file_size INTEGER NOT NULL DEFAULT 0,
    mime_type TEXT NOT NULL DEFAULT 'text/markdown',
    storage_backend TEXT NOT NULL DEFAULT 'local',
    storage_key TEXT NOT NULL DEFAULT '',
    original_filename TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    is_latest INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT NOT NULL REFERENCES artifacts(id),
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ax_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    workflow_id TEXT,
    artifact_id TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    agent_type_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (agent_type_id) REFERENCES agent_types(id)
);

CREATE TABLE IF NOT EXISTS workflow_definitions (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL UNIQUE REFERENCES workflow_templates(id),
    content TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_skill_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id TEXT NOT NULL REFERENCES workflow_templates(id),
    skill_id TEXT NOT NULL REFERENCES skills(id),
    stage_id TEXT,
    execution_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(template_id, skill_id, stage_id),
    FOREIGN KEY (stage_id) REFERENCES stage_definitions(id)
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflow_instances(id),
    stage_id TEXT NOT NULL REFERENCES stage_definitions(id),
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at TEXT NOT NULL,
    decided_by TEXT NOT NULL DEFAULT '',
    decided_at TEXT,
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS slack_channel_project_mappings (
    id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL DEFAULT '',
    enterprise_id TEXT NOT NULL DEFAULT '',
    channel_id TEXT NOT NULL,
    channel_name TEXT NOT NULL DEFAULT '',
    normalized_channel_name TEXT NOT NULL DEFAULT '',
    company_name TEXT NOT NULL,
    project_key TEXT NOT NULL,
    workflow_id TEXT NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',
    onboarding_message TEXT NOT NULL DEFAULT '',
    onboarding_message_ts TEXT NOT NULL DEFAULT '',
    onboarding_message_sent_at TEXT,
    first_event_id TEXT NOT NULL DEFAULT '',
    last_event_id TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(team_id, channel_id),
    UNIQUE(team_id, project_key),
    UNIQUE(workflow_id)
);

CREATE TABLE IF NOT EXISTS slack_event_receipts (
    event_id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT '',
    channel_id TEXT NOT NULL DEFAULT '',
    retry_num TEXT NOT NULL DEFAULT '',
    retry_reason TEXT NOT NULL DEFAULT '',
    body_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'processing',
    mapping_id TEXT REFERENCES slack_channel_project_mappings(id) ON DELETE SET NULL,
    workflow_id TEXT REFERENCES workflow_instances(id) ON DELETE SET NULL,
    response_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS slack_workflow_source_files (
    id TEXT PRIMARY KEY,
    mapping_id TEXT NOT NULL REFERENCES slack_channel_project_mappings(id) ON DELETE CASCADE,
    workflow_id TEXT NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
    artifact_id TEXT REFERENCES artifacts(id) ON DELETE SET NULL,
    slack_file_id TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    mimetype TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    url_private TEXT NOT NULL DEFAULT '',
    url_private_download TEXT NOT NULL DEFAULT '',
    uploaded_user TEXT NOT NULL DEFAULT '',
    uploaded_ts TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'stored',
    rejection_reason TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(mapping_id, slack_file_id)
);

CREATE TABLE IF NOT EXISTS slack_material_collection_states (
    workflow_id TEXT PRIMARY KEY REFERENCES workflow_instances(id) ON DELETE CASCADE,
    mapping_id TEXT NOT NULL REFERENCES slack_channel_project_mappings(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending_confirmation',
    source_file_count INTEGER NOT NULL DEFAULT 0,
    rejected_file_count INTEGER NOT NULL DEFAULT 0,
    last_message TEXT NOT NULL DEFAULT '',
    last_message_ts TEXT NOT NULL DEFAULT '',
    last_message_sent_at TEXT,
    last_error TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS planning_worker_requests (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
    mapping_id TEXT REFERENCES slack_channel_project_mappings(id) ON DELETE SET NULL,
    request_type TEXT NOT NULL DEFAULT 'research',
    status TEXT NOT NULL DEFAULT 'queued',
    payload_json TEXT NOT NULL DEFAULT '{}',
    source_event_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS planning_worker_results (
    id TEXT PRIMARY KEY,
    request_id TEXT REFERENCES planning_worker_requests(id) ON DELETE SET NULL,
    workflow_id TEXT NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
    result_type TEXT NOT NULL DEFAULT 'research_report',
    artifact_id TEXT REFERENCES artifacts(id) ON DELETE SET NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""


def _get_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("PRAGMA user_version").fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def _set_schema_version(conn: sqlite3.Connection, version: int):
    conn.execute(f"PRAGMA user_version = {version}")


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row[0] > 0


def _normalize_slack_channel_name(channel_name: str) -> str:
    return "-".join(channel_name.strip().lstrip("#").lower().replace("_", "-").split())


def _backfill_slack_channel_project_mappings(conn: sqlite3.Connection):
    """Backfill mappings from legacy workflow metadata_json Slack fields."""
    if not _table_exists(conn, "slack_channel_project_mappings") or not _table_exists(conn, "workflow_instances"):
        return

    rows = conn.execute(
        """SELECT id, title, metadata_json, created_at, updated_at
           FROM workflow_instances
           WHERE template_id='planning_research_mvp_v1'"""
    ).fetchall()
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except Exception:
            continue
        slack = metadata.get("slack") or {}
        channel_id = (slack.get("channel_id") or "").strip()
        if not channel_id:
            continue
        company_name = (metadata.get("company_name") or row["title"].strip("[]").split("]")[0]).strip()
        if not company_name:
            continue
        channel_name = (slack.get("channel_name") or company_name).strip().lstrip("#")
        team_id = (slack.get("team_id") or metadata.get("team_id") or "").strip()
        enterprise_id = (slack.get("enterprise_id") or metadata.get("enterprise_id") or "").strip()
        project_key = (metadata.get("project_key") or f"planning-research:{company_name}").strip()
        now = row["updated_at"] or row["created_at"]
        conn.execute(
            """INSERT OR IGNORE INTO slack_channel_project_mappings
               (id, team_id, enterprise_id, channel_id, channel_name, normalized_channel_name,
                company_name, project_key, workflow_id, status, onboarding_message, first_event_id,
                last_event_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"scpm_{row['id']}",
                team_id,
                enterprise_id,
                channel_id,
                channel_name,
                _normalize_slack_channel_name(channel_name),
                company_name,
                project_key,
                row["id"],
                "active",
                "",
                "",
                "",
                row["created_at"],
                now,
            ),
        )


def _run_migrations(conn: sqlite3.Connection):
    """Run incremental migrations based on PRAGMA user_version."""
    current = _get_schema_version(conn)

    if current < 2:
        if not _column_exists(conn, "stage_definitions", "transition_mode"):
            conn.execute("ALTER TABLE stage_definitions ADD COLUMN transition_mode TEXT NOT NULL DEFAULT 'auto'")
        if not _column_exists(conn, "stage_definitions", "approval_roles"):
            conn.execute("ALTER TABLE stage_definitions ADD COLUMN approval_roles TEXT NOT NULL DEFAULT '[]'")

        if not _column_exists(conn, "artifacts", "file_path"):
            conn.execute("ALTER TABLE artifacts ADD COLUMN file_path TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "artifacts", "file_size"):
            conn.execute("ALTER TABLE artifacts ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "artifacts", "mime_type"):
            conn.execute("ALTER TABLE artifacts ADD COLUMN mime_type TEXT NOT NULL DEFAULT 'text/markdown'")

        if not _table_exists(conn, "skills"):
            conn.execute("""CREATE TABLE skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                agent_type_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (agent_type_id) REFERENCES agent_types(id)
            )""")

        if not _table_exists(conn, "workflow_definitions"):
            conn.execute("""CREATE TABLE workflow_definitions (
                id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL UNIQUE REFERENCES workflow_templates(id),
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")

        if not _table_exists(conn, "workflow_skill_bindings"):
            conn.execute("""CREATE TABLE workflow_skill_bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id TEXT NOT NULL REFERENCES workflow_templates(id),
                skill_id TEXT NOT NULL REFERENCES skills(id),
                stage_id TEXT,
                execution_order INTEGER NOT NULL DEFAULT 0,
                UNIQUE(template_id, skill_id, stage_id),
                FOREIGN KEY (stage_id) REFERENCES stage_definitions(id)
            )""")

        if not _table_exists(conn, "approval_requests"):
            conn.execute("""CREATE TABLE approval_requests (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL REFERENCES workflow_instances(id),
                stage_id TEXT NOT NULL REFERENCES stage_definitions(id),
                status TEXT NOT NULL DEFAULT 'pending',
                requested_at TEXT NOT NULL,
                decided_by TEXT NOT NULL DEFAULT '',
                decided_at TEXT,
                note TEXT NOT NULL DEFAULT ''
            )""")

        _set_schema_version(conn, 2)
        current = 2

    if current < 3:
        if not _table_exists(conn, "users"):
            conn.execute("""CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")

        if not _table_exists(conn, "auth_sessions"):
            conn.execute("""CREATE TABLE auth_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                session_token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )""")

        _set_schema_version(conn, 3)
        current = 3

    if current < 4:
        if not _table_exists(conn, "activity_logs"):
            conn.execute("""CREATE TABLE activity_logs (
                id TEXT PRIMARY KEY,
                actor_kind TEXT NOT NULL,
                actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                actor_label TEXT NOT NULL DEFAULT 'system',
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT,
                workflow_id TEXT REFERENCES workflow_instances(id) ON DELETE CASCADE,
                artifact_id TEXT REFERENCES artifacts(id) ON DELETE CASCADE,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )""")

        if not _column_exists(conn, "workflow_instances", "created_by_user_id"):
            conn.execute("ALTER TABLE workflow_instances ADD COLUMN created_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL")

        if not _column_exists(conn, "artifacts", "created_by_user_id"):
            conn.execute("ALTER TABLE artifacts ADD COLUMN created_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL")
        if not _column_exists(conn, "artifacts", "updated_by_user_id"):
            conn.execute("ALTER TABLE artifacts ADD COLUMN updated_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL")

        if not _column_exists(conn, "comments", "author_user_id"):
            conn.execute("ALTER TABLE comments ADD COLUMN author_user_id TEXT REFERENCES users(id) ON DELETE SET NULL")

        if not _column_exists(conn, "approval_requests", "requested_by_user_id"):
            conn.execute("ALTER TABLE approval_requests ADD COLUMN requested_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL")
        if not _column_exists(conn, "approval_requests", "decided_by_user_id"):
            conn.execute("ALTER TABLE approval_requests ADD COLUMN decided_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL")

        if not _column_exists(conn, "stage_transitions", "triggered_by_user_id"):
            conn.execute("ALTER TABLE stage_transitions ADD COLUMN triggered_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL")

        _set_schema_version(conn, 4)
        current = 4

    if current < 5:
        if _table_exists(conn, "artifacts"):
            if not _column_exists(conn, "artifacts", "storage_backend"):
                conn.execute("ALTER TABLE artifacts ADD COLUMN storage_backend TEXT NOT NULL DEFAULT 'local'")
            if not _column_exists(conn, "artifacts", "storage_key"):
                conn.execute("ALTER TABLE artifacts ADD COLUMN storage_key TEXT NOT NULL DEFAULT ''")
            if not _column_exists(conn, "artifacts", "original_filename"):
                conn.execute("ALTER TABLE artifacts ADD COLUMN original_filename TEXT NOT NULL DEFAULT ''")
            if not _column_exists(conn, "artifacts", "version"):
                conn.execute("ALTER TABLE artifacts ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
            if not _column_exists(conn, "artifacts", "is_latest"):
                conn.execute("ALTER TABLE artifacts ADD COLUMN is_latest INTEGER NOT NULL DEFAULT 1")

            conn.execute("UPDATE artifacts SET storage_backend='local' WHERE storage_backend='' OR storage_backend IS NULL")
            conn.execute("UPDATE artifacts SET storage_key=file_path WHERE (storage_key='' OR storage_key IS NULL) AND file_path<>''")
            conn.execute("UPDATE artifacts SET version=1 WHERE version IS NULL OR version < 1")
            conn.execute("UPDATE artifacts SET is_latest=1 WHERE is_latest IS NULL")

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artifacts_latest_group "
                "ON artifacts(workflow_id, stage_id, artifact_type, is_latest, version)"
            )

        _set_schema_version(conn, 5)
        current = 5

    if current < 6:
        conn.execute("""CREATE TABLE IF NOT EXISTS slack_channel_project_mappings (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL DEFAULT '',
            enterprise_id TEXT NOT NULL DEFAULT '',
            channel_id TEXT NOT NULL,
            channel_name TEXT NOT NULL DEFAULT '',
            normalized_channel_name TEXT NOT NULL DEFAULT '',
            company_name TEXT NOT NULL,
            project_key TEXT NOT NULL,
            workflow_id TEXT NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'active',
            onboarding_message TEXT NOT NULL DEFAULT '',
            onboarding_message_ts TEXT NOT NULL DEFAULT '',
            onboarding_message_sent_at TEXT,
            first_event_id TEXT NOT NULL DEFAULT '',
            last_event_id TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(team_id, channel_id),
            UNIQUE(team_id, project_key),
            UNIQUE(workflow_id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS slack_event_receipts (
            event_id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL DEFAULT '',
            channel_id TEXT NOT NULL DEFAULT '',
            retry_num TEXT NOT NULL DEFAULT '',
            retry_reason TEXT NOT NULL DEFAULT '',
            body_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'processing',
            mapping_id TEXT REFERENCES slack_channel_project_mappings(id) ON DELETE SET NULL,
            workflow_id TEXT REFERENCES workflow_instances(id) ON DELETE SET NULL,
            response_json TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '',
            received_at TEXT NOT NULL,
            processed_at TEXT
        )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slack_mapping_channel "
            "ON slack_channel_project_mappings(team_id, channel_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slack_mapping_project_key "
            "ON slack_channel_project_mappings(team_id, project_key)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slack_event_receipts_channel "
            "ON slack_event_receipts(team_id, channel_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slack_event_receipts_status "
            "ON slack_event_receipts(status, received_at)"
        )
        _backfill_slack_channel_project_mappings(conn)
        _set_schema_version(conn, 6)
        current = 6

    if current < 7:
        conn.execute("""CREATE TABLE IF NOT EXISTS slack_workflow_source_files (
            id TEXT PRIMARY KEY,
            mapping_id TEXT NOT NULL REFERENCES slack_channel_project_mappings(id) ON DELETE CASCADE,
            workflow_id TEXT NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
            artifact_id TEXT REFERENCES artifacts(id) ON DELETE SET NULL,
            slack_file_id TEXT NOT NULL DEFAULT '',
            filename TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            mimetype TEXT NOT NULL DEFAULT '',
            size INTEGER NOT NULL DEFAULT 0,
            url_private TEXT NOT NULL DEFAULT '',
            url_private_download TEXT NOT NULL DEFAULT '',
            uploaded_user TEXT NOT NULL DEFAULT '',
            uploaded_ts TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'stored',
            rejection_reason TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(mapping_id, slack_file_id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS slack_material_collection_states (
            workflow_id TEXT PRIMARY KEY REFERENCES workflow_instances(id) ON DELETE CASCADE,
            mapping_id TEXT NOT NULL REFERENCES slack_channel_project_mappings(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending_confirmation',
            source_file_count INTEGER NOT NULL DEFAULT 0,
            rejected_file_count INTEGER NOT NULL DEFAULT 0,
            last_message TEXT NOT NULL DEFAULT '',
            last_message_ts TEXT NOT NULL DEFAULT '',
            last_message_sent_at TEXT,
            last_error TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slack_source_files_workflow "
            "ON slack_workflow_source_files(workflow_id, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slack_source_files_mapping "
            "ON slack_workflow_source_files(mapping_id, slack_file_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slack_source_files_status "
            "ON slack_workflow_source_files(status, created_at)"
        )
        _set_schema_version(conn, 7)
        current = 7

    if current < 8:
        conn.execute("""CREATE TABLE IF NOT EXISTS planning_worker_requests (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
            mapping_id TEXT REFERENCES slack_channel_project_mappings(id) ON DELETE SET NULL,
            request_type TEXT NOT NULL DEFAULT 'research',
            status TEXT NOT NULL DEFAULT 'queued',
            payload_json TEXT NOT NULL DEFAULT '{}',
            source_event_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS planning_worker_results (
            id TEXT PRIMARY KEY,
            request_id TEXT REFERENCES planning_worker_requests(id) ON DELETE SET NULL,
            workflow_id TEXT NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
            result_type TEXT NOT NULL DEFAULT 'research_report',
            artifact_id TEXT REFERENCES artifacts(id) ON DELETE SET NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_worker_requests_workflow "
            "ON planning_worker_requests(workflow_id, request_type, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_worker_results_workflow "
            "ON planning_worker_results(workflow_id, created_at)"
        )
        _set_schema_version(conn, 8)
