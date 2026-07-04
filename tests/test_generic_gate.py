"""
Tests for scripts/generic_gate.py, the PUBLIC hygiene gate (staged for the
public repo; the private-phase denylist quartet does not ship).

The gate's tree scan runs against the live repo only in the PUBLIC tree (the
private tree legitimately contains personal paths inside the never-shipping
internal docs), so these tests exercise the pattern and identity logic
directly rather than asserting on the current working tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generic_gate  # noqa: E402


def _first_match(line):
    for pat, label in generic_gate.PATH_PATTERNS:
        m = pat.search(line)
        if m:
            return label, m.group(0)
    return None


def test_windows_user_profile_path_detected():
    hit = _first_match(r"data at C:\Users\somebody\projects\x")
    assert hit and hit[0] == "Windows user-profile path"
    hit = _first_match("mounted from C:/Users/somebody/tree")
    assert hit and hit[0] == "Windows user-profile path"


def test_linux_and_macos_home_paths_detected():
    assert _first_match("/home/somebody/repos/thing")[0] == "Linux home path"
    assert _first_match("/Users/somebody/dev/thing")[0] == "macOS home path"


def test_placeholder_paths_are_allowed():
    assert _first_match(r"C:\Users\YOURNAME\project") is None
    assert _first_match("/home/user/project/") is None
    assert _first_match("/home/runner/work/repo/") is None  # GitHub Actions
    assert _first_match("/Users/USER/project/") is None


def test_identity_allowlist_patterns():
    allowed = [
        "12345+Someone@users.noreply.github.com",
        "Someone@users.noreply.github.com",
        "dependabot[bot]@users.noreply.github.com",
    ]
    rejected = [
        "person@example.com",
        "dev@somewhere.dev",
    ]
    for email in allowed:
        assert any(p.match(email) for p in generic_gate.DEFAULT_ALLOWED_EMAIL_PATTERNS), email
    for email in rejected:
        assert not any(p.match(email) for p in generic_gate.DEFAULT_ALLOWED_EMAIL_PATTERNS), email
