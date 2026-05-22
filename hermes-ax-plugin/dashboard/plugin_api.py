"""Hermes AX Plugin API — FastAPI backend for Agent eXecution Dashboard."""

from __future__ import annotations

from fastapi import APIRouter

try:
    from .events import _emit_event
    from .bootstrap import _upsert_bootstrap_admin
    from .common import _now
    from .db import get_db
    from .db_schema import SCHEMA_SQL, _run_migrations
    from .auth_api import router as auth_router
    from .artifacts_api import router as artifacts_router
    from .catalog_api import router as catalog_router
    from .definitions_api import router as definitions_router
    from .approvals_api import router as approvals_router
    from .comments_api import router as comments_router
    from .events_api import router as events_router
    from .stats_api import router as stats_router
    from .stage_settings_api import router as stage_settings_router
    from .workflows_api import router as workflows_router
    from .skills_api import router as skills_router
    from .slack_onboarding_api import router as slack_onboarding_router
    from .seed import seed_if_empty
except ImportError:
    import os
    import sys

    _dashboard_dir = os.path.dirname(os.path.abspath(__file__))
    if _dashboard_dir not in sys.path:
        sys.path.insert(0, _dashboard_dir)

    from events import _emit_event
    from bootstrap import _upsert_bootstrap_admin
    from common import _now
    from db import get_db
    from db_schema import SCHEMA_SQL, _run_migrations
    from auth_api import router as auth_router
    from artifacts_api import router as artifacts_router
    from catalog_api import router as catalog_router
    from definitions_api import router as definitions_router
    from approvals_api import router as approvals_router
    from comments_api import router as comments_router
    from events_api import router as events_router
    from stats_api import router as stats_router
    from stage_settings_api import router as stage_settings_router
    from workflows_api import router as workflows_router
    from skills_api import router as skills_router
    from slack_onboarding_api import router as slack_onboarding_router
    from seed import seed_if_empty

router = APIRouter()
router.include_router(auth_router)
router.include_router(definitions_router)
router.include_router(approvals_router)
router.include_router(comments_router)
router.include_router(events_router)
router.include_router(stats_router)
router.include_router(stage_settings_router)
router.include_router(workflows_router)
router.include_router(slack_onboarding_router)


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
        _run_migrations(conn)
        seed_if_empty(conn, _now, _emit_event)
        _upsert_bootstrap_admin(conn)


# Run on import
init_db()

router.include_router(catalog_router)


router.include_router(artifacts_router)
router.include_router(skills_router)
