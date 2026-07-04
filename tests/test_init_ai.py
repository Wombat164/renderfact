"""
Tests for contracts/init_ai.py -- D8 harness mode (chunk 3.2): `render init-ai`
installs renderfact-aware instructions into the user's own assistant, adopting
calm-ai's `init-ai` pattern (zero new LLM-calling code of renderfact's own).

Covers: instruction text is actually generated from the vision-review contract's
schema (not hand-duplicated prose that could drift), both assistant targets
write to the right path, the copilot section is idempotent (re-running replaces
only the marked section, preserving any pre-existing repo instructions), and
main() dispatches --assistant all vs. a single assistant correctly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from contracts import init_ai  # noqa: E402


def test_step_instructions_reflect_actual_schema():
    contracts = init_ai.step_contracts()
    names = [n for n, _ in contracts]
    assert "vision-review" in names  # the first, still present
    assert "decision-capture" in names  # C8.3 added
    # every registered step must render instructions from its own schema
    for name, module in contracts:
        text = init_ai.render_step_instructions(name, module)
        assert module.TASK_INTENT in text
        for field in module.INPUT_SCHEMA:
            assert f"`{field.name}`" in text
        for field in module.OUTPUT_SCHEMA:
            assert f"`{field.name}`" in text
        assert '"harness"' in text


def test_step_instructions_expand_nested_list_item_schema():
    # findings has an item_schema (criterion/severity/comment) -- a harness reading
    # only "findings (list, required): Per-criterion findings." could not know the
    # required shape of each item without this expansion.
    contracts = dict(init_ai.step_contracts())
    module = contracts["vision-review"]
    text = init_ai.render_step_instructions("vision-review", module)
    findings_field = next(f for f in module.OUTPUT_SCHEMA if f.name == "findings")
    assert findings_field.item_schema is not None
    for nested in findings_field.item_schema:
        assert f"`{nested.name}`" in text


def test_render_step_instructions_mode_param_switches_reviewer_mode_text():
    contracts = init_ai.step_contracts()
    name, module = contracts[0]
    harness_text = init_ai.render_step_instructions(name, module, mode="harness")
    copy_paste_text = init_ai.render_step_instructions(name, module, mode="copy-paste")
    assert '"harness"' in harness_text and '"copy-paste"' not in harness_text
    assert '"copy-paste"' in copy_paste_text and '"harness"' not in copy_paste_text


def test_render_step_instructions_rejects_unknown_mode():
    contracts = init_ai.step_contracts()
    name, module = contracts[0]
    with pytest.raises(ValueError, match="mode must be"):
        init_ai.render_step_instructions(name, module, mode="telepathy")


def test_claude_skill_has_frontmatter_and_step_content():
    skill = init_ai.render_claude_skill()
    assert skill.startswith("---\nname: renderfact\n")
    assert "## vision-review" in skill


def test_copilot_section_is_marked():
    section = init_ai.render_copilot_section()
    assert section.startswith(init_ai.START_MARKER)
    assert section.rstrip().endswith(init_ai.END_MARKER)
    assert "## vision-review" in section


def test_install_claude_writes_skill_md(tmp_path):
    target = init_ai.install("claude", tmp_path)
    assert target == tmp_path / ".claude" / "skills" / "renderfact" / "SKILL.md"
    assert target.exists()
    assert "name: renderfact" in target.read_text(encoding="utf-8")


def test_install_copilot_creates_file_when_absent(tmp_path):
    target = init_ai.install("copilot", tmp_path)
    assert target == tmp_path / ".github" / "copilot-instructions.md"
    content = target.read_text(encoding="utf-8")
    assert init_ai.START_MARKER in content
    assert init_ai.END_MARKER in content


def test_install_copilot_preserves_existing_instructions_outside_markers(tmp_path):
    target = tmp_path / ".github" / "copilot-instructions.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Repo instructions\n\nAlways run tests before committing.\n", encoding="utf-8")

    init_ai.install("copilot", tmp_path)
    content = target.read_text(encoding="utf-8")
    assert "Always run tests before committing." in content
    assert init_ai.START_MARKER in content


def test_install_copilot_is_idempotent_and_replaces_only_marked_section(tmp_path):
    target = tmp_path / ".github" / "copilot-instructions.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "# Repo instructions\n\nCustom preamble.\n\n"
        + init_ai.START_MARKER
        + "\nSTALE CONTENT FROM AN OLDER SCHEMA\n"
        + init_ai.END_MARKER
        + "\n",
        encoding="utf-8",
    )

    init_ai.install("copilot", tmp_path)
    content = target.read_text(encoding="utf-8")
    assert "Custom preamble." in content
    assert "STALE CONTENT FROM AN OLDER SCHEMA" not in content
    assert "## vision-review" in content
    # markers appear exactly once each -- no duplication across re-runs
    assert content.count(init_ai.START_MARKER) == 1
    assert content.count(init_ai.END_MARKER) == 1


def test_install_unknown_assistant_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown assistant"):
        init_ai.install("copilot-x", tmp_path)


def test_main_all_writes_both_assistants(tmp_path, capsys):
    rc = init_ai.main(["--target-dir", str(tmp_path), "--assistant", "all"])
    assert rc == 0
    assert (tmp_path / ".claude" / "skills" / "renderfact" / "SKILL.md").exists()
    assert (tmp_path / ".github" / "copilot-instructions.md").exists()


def test_main_single_assistant_writes_only_that_one(tmp_path):
    rc = init_ai.main(["--target-dir", str(tmp_path), "--assistant", "claude"])
    assert rc == 0
    assert (tmp_path / ".claude" / "skills" / "renderfact" / "SKILL.md").exists()
    assert not (tmp_path / ".github" / "copilot-instructions.md").exists()
