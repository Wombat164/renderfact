#!/usr/bin/env python3
"""check_wiki_sync.py: enforce that the wiki reference stays in sync with the code.

Every user-facing `render <command>` (the keys of render.py's MODES dispatch) must
appear in the wiki command-surface reference. A new command that ships without a
wiki entry fails this check -- so the docs site cannot silently drift behind the
CLI. This is the "UX/command change must update the wiki" doctrine, made
deterministic and CI-enforced rather than left to discipline.

If a command genuinely needs no reference entry, add it to ALLOW_UNDOCUMENTED here
(with a reason) rather than skipping the check.

Exit codes: 0 in sync, 1 drift (undocumented command), 2 environment error.
Usage: python scripts/check_wiki_sync.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE = REPO_ROOT / "wiki" / "content" / "reference" / "index.md"

# Commands intentionally absent from the reference table, each with a reason.
ALLOW_UNDOCUMENTED: dict[str, str] = {
    "container": "raw podman passthrough, documented in the container-mode section, not a step",
}


def render_commands() -> list[str]:
    sys.path.insert(0, str(REPO_ROOT))
    import render  # importing is side-effect-free (dispatch does its imports lazily)

    return sorted(render.MODES)


def main() -> int:
    if not REFERENCE.exists():
        print(f"ERROR: wiki reference not found at {REFERENCE.relative_to(REPO_ROOT)}",
              file=sys.stderr)
        return 2
    ref = REFERENCE.read_text(encoding="utf-8")

    missing = []
    for cmd in render_commands():
        if cmd in ALLOW_UNDOCUMENTED:
            continue
        # documented if the reference mentions `render <cmd>` (backtick or plain)
        if re.search(rf"`render {re.escape(cmd)}[ `]", ref) or f"render {cmd} " in ref \
                or f"render {cmd}`" in ref:
            continue
        missing.append(cmd)

    if missing:
        rel = REFERENCE.relative_to(REPO_ROOT)
        print("Wiki reference is out of sync with the render command surface.", file=sys.stderr)
        print(f"  undocumented in {rel}: {', '.join(missing)}", file=sys.stderr)
        print("  -> add each to the command-surface table, or (if it truly needs no entry)", file=sys.stderr)
        print("     add it to ALLOW_UNDOCUMENTED in scripts/check_wiki_sync.py with a reason.", file=sys.stderr)
        return 1

    total = len(render_commands())
    print(f"wiki reference in sync: all {total - len(ALLOW_UNDOCUMENTED)} documented "
          f"render commands present ({len(ALLOW_UNDOCUMENTED)} intentionally exempt).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
