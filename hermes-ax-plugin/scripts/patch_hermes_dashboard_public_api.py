"""Allow the AX Slack Events endpoint through Hermes Dashboard API auth.

Hermes Dashboard protects every /api/* route with an ephemeral browser session
header, except for a small hard-coded public allowlist. Slack Events API cannot
send that dashboard session token, so the AX Slack webhook must be added to the
public allowlist while keeping Slack signing-secret verification inside the
plugin route itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

SLACK_EVENTS_PUBLIC_PATH = "/api/plugins/hermes-ax/slack/events"
PUBLIC_PATH_LINE = f'    "{SLACK_EVENTS_PUBLIC_PATH}",\n'
ANCHOR = '    "/api/dashboard/plugins",\n})'
REPLACEMENT = '    "/api/dashboard/plugins",\n' + PUBLIC_PATH_LINE + '})'
DEFAULT_WEB_SERVER_PATH = Path("/opt/hermes-agent/hermes_cli/web_server.py")


def patch_public_api_allowlist_text(text: str) -> str:
    """Return web_server.py text with the Slack webhook path allowlisted.

    The patch is intentionally narrow and fail-fast: only the exact Slack Events
    endpoint is made public, and an upstream layout change fails the Docker build
    rather than silently shipping a blocked webhook.
    """
    if PUBLIC_PATH_LINE in text:
        return text
    if ANCHOR not in text:
        raise RuntimeError("Hermes Dashboard public API allowlist anchor not found")
    return text.replace(ANCHOR, REPLACEMENT, 1)


def patch_file(path: Path) -> bool:
    original = path.read_text()
    patched = patch_public_api_allowlist_text(original)
    if patched == original:
        return False
    path.write_text(patched)
    return True


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    path = Path(argv[0]) if argv else DEFAULT_WEB_SERVER_PATH
    changed = patch_file(path)
    action = "patched" if changed else "already patched"
    print(f"Hermes Dashboard public API allowlist {action}: {SLACK_EVENTS_PUBLIC_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
