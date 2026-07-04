"""
init_ai.py -- D8 harness mode (chunk 3.2): install renderfact-aware instruction
files into the user's OWN already-configured assistant.

Adopts calm-ai's `init-ai` pattern wholesale (FINOS CALM, audited 2026-07-02 --
see docs/2026-07-02-feature-deepdive-and-canonical-plan.md section 4, "the
single most directly-adoptable idea from all four audits for D8"): rather than
renderfact embedding its own LLM-calling code, this installs a short,
schema-generated instruction file per assistant so that whichever harness the
user already runs (Claude Code, Copilot, ...) can perform a D8 step directly.
Zero new LLM-calling code of renderfact's own; zero new trust boundary.

The instruction text is GENERATED from each step contract's own FieldSpec
schema (contracts/schema_utils.py), never hand-duplicated -- so it can't drift
from the actual rule validate_output() will apply to the harness's result.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from contracts.schema_utils import FieldSpec

REPO_ROOT = Path(__file__).resolve().parent.parent
LINT_DIR = REPO_ROOT / "lint"

START_MARKER = "<!-- renderfact:init-ai:start -->"
END_MARKER = "<!-- renderfact:init-ai:end -->"


def step_contracts() -> list[tuple[str, object]]:
    """Every D8 step contract that exists so far. Append here as new steps land --
    chunk 3.1 shipped vision-review only, so this is a plain list, not a
    dynamic-discovery registry; that machinery would be premature for one item.
    Public: chunk 3.4's copy-paste CLI (render.py) reuses this as the single
    source of truth for "which steps exist" -- not just this module's own use."""
    sys.path.insert(0, str(LINT_DIR))
    sys.path.insert(0, str(REPO_ROOT / "roundtrip"))
    import vision_review_contract  # lint/vision_review_contract.py
    import decision_capture  # roundtrip/decision_capture.py (C8.3)

    return [
        ("vision-review", vision_review_contract),
        ("decision-capture", decision_capture),
    ]


def _field_doc(spec: FieldSpec, indent: str = "") -> list[str]:
    req = "required" if spec.required else "optional"
    allowed = f", one of: {', '.join(map(str, spec.allowed_values))}" if spec.allowed_values else ""
    lines = [f"{indent}- `{spec.name}` ({spec.type.__name__}, {req}{allowed}): {spec.description}"]
    if spec.item_schema is not None:
        lines.append(f"{indent}  Each item is an object with:")
        for nested in spec.item_schema:
            lines.extend(_field_doc(nested, indent=indent + "  "))
    return lines


def _schema_doc(schema: list[FieldSpec]) -> list[str]:
    lines: list[str] = []
    for f in schema:
        lines.extend(_field_doc(f))
    return lines


def render_step_instructions(step_name: str, module, mode: str = "harness") -> str:
    """Generate the instruction body for one D8 step, from its own schema.

    `mode` is "harness" (default -- used by the .claude/.github installers below)
    or "copy-paste" (chunk 3.4's contracts/copy_paste.py reuses this function
    almost unchanged for its paste-in prompt -- this parameter is the only edit
    that reuse needed, per the design spike's finding)."""
    if mode not in ("harness", "copy-paste"):
        raise ValueError(f"mode must be 'harness' or 'copy-paste', got {mode!r}")
    lines = [
        f"## {step_name}",
        "",
        "**Task:**",
        module.TASK_INTENT,
        "",
        "**Input you will receive** (assembled deterministically -- identical to "
        "what a human's copy-paste flow would receive):",
        *_schema_doc(module.INPUT_SCHEMA),
        "",
        "**Output you must produce** (validated by "
        f"`{module.__name__}.validate_output()` -- the same rule for every mode, "
        "harness or copy-paste):",
        *_schema_doc(module.OUTPUT_SCHEMA),
        "",
        f'Set `reviewer_mode` to `"{mode}"`. Before finalizing, check your output '
        "against every field above -- a missing or mistyped field fails validation "
        "identically to a human's pasted-in answer.",
    ]
    return "\n".join(lines)


def render_claude_skill() -> str:
    """SKILL.md body for .claude/skills/renderfact/SKILL.md."""
    header = (
        "---\n"
        "name: renderfact\n"
        "description: Perform renderfact's D8 LLM-touching steps (vision-review, "
        "and future steps) directly, using the exact schema renderfact validates "
        "against -- no separate API call needed.\n"
        "---\n\n"
        "# renderfact D8 steps\n\n"
        "renderfact (see docs/DECISIONS.md D8) defines a fixed input/output "
        "contract per step so an agentic harness and a human pasting into any "
        "chat LLM produce indistinguishable results. This file documents every "
        "step contract that exists today, generated from the schema in "
        "`contracts/` + `lint/*_contract.py` -- if this file and the code ever "
        "disagree, the code wins; regenerate with `render init-ai`.\n"
    )
    body = "\n\n".join(render_step_instructions(name, mod) for name, mod in step_contracts())
    return header + "\n" + body + "\n"


def render_copilot_section() -> str:
    """The renderfact section for .github/copilot-instructions.md -- marked so
    it can be idempotently replaced without disturbing any other repo instructions
    already in that file."""
    header = (
        f"{START_MARKER}\n"
        "## renderfact D8 steps\n\n"
        "This repo uses renderfact (docs/DECISIONS.md D8). The following steps "
        "have a fixed input/output contract -- when asked to perform one, follow "
        "the schema below exactly; your output is validated by the same rule a "
        "human's copy-pasted answer would be. Regenerate this section with "
        "`render init-ai` if it drifts from the code.\n"
    )
    body = "\n\n".join(render_step_instructions(name, mod) for name, mod in step_contracts())
    return header + "\n" + body + f"\n{END_MARKER}\n"


ASSISTANTS = {
    "claude": {
        "path": Path(".claude/skills/renderfact/SKILL.md"),
        "render": render_claude_skill,
        "mode": "overwrite",
    },
    "copilot": {
        "path": Path(".github/copilot-instructions.md"),
        "render": render_copilot_section,
        "mode": "section",
    },
}


def _write_section(target: Path, section: str) -> None:
    """Idempotently replace a marked section within an existing file, or append
    it (creating the file if needed) when the markers aren't present yet."""
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if START_MARKER in existing and END_MARKER in existing:
        pre = existing.split(START_MARKER)[0]
        post = existing.split(END_MARKER)[1]
        new_content = pre + section + post
    else:
        sep = "\n\n" if existing and not existing.endswith("\n\n") else ""
        new_content = existing + sep + section
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_content, encoding="utf-8")


def install(assistant: str, target_dir: Path) -> Path:
    """Install (or idempotently re-install) one assistant's instruction file
    under target_dir. Returns the path written."""
    if assistant not in ASSISTANTS:
        raise ValueError(f"unknown assistant '{assistant}' -- choose from {sorted(ASSISTANTS)}")
    spec = ASSISTANTS[assistant]
    target = target_dir / spec["path"]
    content = spec["render"]()
    if spec["mode"] == "overwrite":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    else:  # "section"
        _write_section(target, content)
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="render init-ai",
        description="Install renderfact-aware instruction files into your own "
                    "configured assistant (D8 harness mode, chunk 3.2).",
    )
    ap.add_argument("--assistant", choices=sorted(ASSISTANTS) + ["all"], default="all")
    ap.add_argument("--target-dir", type=Path, default=Path.cwd())
    args = ap.parse_args(argv)

    names = sorted(ASSISTANTS) if args.assistant == "all" else [args.assistant]
    for name in names:
        path = install(name, args.target_dir)
        print(f"renderfact init-ai: wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
