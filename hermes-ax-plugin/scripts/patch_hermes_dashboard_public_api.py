"""Allow the AX Slack Events endpoint through Hermes Dashboard API auth.

Hermes Dashboard protects every /api/* route with an ephemeral browser session
header, except for a small hard-coded public allowlist. Slack Events API cannot
send that dashboard session token, so the AX Slack webhook must be added to the
public allowlist while keeping Slack signing-secret verification inside the
plugin route itself.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SLACK_EVENTS_PUBLIC_PATH = "/api/plugins/hermes-ax/slack/events"
DEFAULT_WEB_SERVER_PATH = Path("/opt/hermes-agent/hermes_cli/web_server.py")
DEFAULT_PUBLIC_PATHS_PATH = Path("/opt/hermes-agent/hermes_cli/dashboard_auth/public_paths.py")
PUBLIC_API_BLOCK_RE = re.compile(
    r"(?P<header>^_?PUBLIC_API_PATHS\b[^\n]*frozenset\(\{\n)"
    r"(?P<body>.*?)"
    r"(?P<footer>^[ \t]*\}\)[^\n]*\n?)",
    re.MULTILINE | re.DOTALL,
)
PUBLIC_PATH_LINE_RE = re.compile(r'^(?P<indent>[ \t]*)"[^"]+",[ \t]*(?:#.*)?$', re.MULTILINE)


def patch_public_api_allowlist_text(text: str) -> str:
    """Return web_server.py text with the Slack webhook path allowlisted.

    The patch stays narrow: only the exact Slack Events endpoint is made
    public.  Instead of depending on one neighboring allowlist entry being the
    final item, locate the _PUBLIC_API_PATHS frozenset block and append the
    endpoint before the block closes. If the block shape changes enough that we
    cannot identify it safely, fail the Docker build.
    """
    if SLACK_EVENTS_PUBLIC_PATH in text:
        return text

    matches = list(PUBLIC_API_BLOCK_RE.finditer(text))
    if len(matches) != 1:
        raise RuntimeError("Hermes Dashboard public API allowlist block not found")

    match = matches[0]
    body = match.group("body")
    path_line_match = PUBLIC_PATH_LINE_RE.search(body)
    indent = path_line_match.group("indent") if path_line_match else "    "
    public_path_line = f'{indent}"{SLACK_EVENTS_PUBLIC_PATH}",\n'
    patched_block = f'{match.group("header")}{body}{public_path_line}{match.group("footer")}'
    return text[:match.start()] + patched_block + text[match.end():]


def patch_file(path: Path) -> bool:
    original = path.read_text()
    patched = patch_public_api_allowlist_text(original)
    if patched == original:
        return False
    path.write_text(patched)
    return True


def _default_target_path() -> Path:
    """Return the Hermes Dashboard file that owns the public API allowlist.

    Older Hermes Agent builds defined ``_PUBLIC_API_PATHS`` directly in
    ``web_server.py``.  Newer builds moved the shared list to
    ``dashboard_auth/public_paths.py`` so both legacy token auth and the OAuth
    gate use the same allowlist.  Prefer the shared module when it exists, while
    keeping the old Docker image path compatible.
    """
    if DEFAULT_PUBLIC_PATHS_PATH.exists():
        return DEFAULT_PUBLIC_PATHS_PATH
    return DEFAULT_WEB_SERVER_PATH


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    path = Path(argv[0]) if argv else _default_target_path()
    changed = patch_file(path)
    action = "patched" if changed else "already patched"
    print(f"Hermes Dashboard public API allowlist {action}: {SLACK_EVENTS_PUBLIC_PATH} in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
