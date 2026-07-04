"""
copy_paste.py -- D8 copy-paste fallback (chunk 3.4), implementing the design in
docs/2026-07-03-d8-copy-paste-design-spike.md.

Generic mechanism (works for any step contract in contracts/init_ai.py's
step_contracts() list, not just vision-review): compose a self-contained
paste-in prompt from a step's own schema (reusing chunk 3.2's
render_step_instructions()), deliver it (stdout + scratch file + best-effort
one-shot clipboard copy), capture the human's pasted-back reply via a
stdin-sentinel read, parse it as JSON/YAML tolerating a markdown fence, and
validate it against the SAME validate_output() a harness-mode result must
pass -- D8's core requirement.

Deliberately deferred (design doc section 5): a clipboard-watch auto-detect
loop (aider's UX, cited in section 1 of the design doc). The one-shot copy-out
below is a convenience; the stdin-sentinel read is the reliable baseline that
always works, including with no clipboard access at all (e.g. over SSH).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from contracts.init_ai import render_step_instructions

SENTINEL = "END"
SCRATCH_FILENAME = ".renderfact-copy-paste-prompt.txt"


class CopyPasteValidationError(RuntimeError):
    """Raised when the human's pasted-back reply still fails validation after
    the retry budget is exhausted."""


def compose_prompt(step_name: str, module, input_obj: dict) -> str:
    """Build the full self-contained paste-in prompt for one step (design doc S3.2)."""
    instructions = render_step_instructions(step_name, module, mode="copy-paste")
    parts = [instructions, "", "---", "INPUT DATA (JSON):", json.dumps(input_obj, indent=2)]

    image_path = input_obj.get("rendered_image_path")
    if image_path:
        parts += [
            "",
            "---",
            f"ATTACH the image at: {image_path}",
            "(most chat UIs accept an image paste/upload alongside text -- attach it "
            "in the same message as this prompt)",
        ]

    parts += [
        "",
        "---",
        "Respond with ONLY a single JSON object matching the OUTPUT SCHEMA above. "
        "No markdown fencing, no commentary before or after -- just the JSON object, "
        "so it can be pasted directly back into the terminal.",
    ]
    return "\n".join(parts)


def _try_copy_to_clipboard(text: str) -> bool:
    """Best-effort one-shot clipboard copy via a platform shell tool -- no new pip
    dependency (design doc section 5 resolves the pyperclip-vs-shell-out question
    this way). Returns whether it succeeded; callers must not depend on success."""
    if sys.platform == "win32":
        candidates = [["clip"]]
    elif sys.platform == "darwin":
        candidates = [["pbcopy"]]
    else:
        candidates = [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]

    for cmd in candidates:
        try:
            subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=5)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def deliver_prompt(prompt: str, scratch_dir: Path, out=sys.stdout) -> Path:
    """Print the prompt, write it to a scratch file (for long prompts awkward to
    re-read from a scrolled terminal), and try a best-effort clipboard copy.
    Returns the scratch file path."""
    scratch_path = Path(scratch_dir) / SCRATCH_FILENAME
    scratch_path.write_text(prompt, encoding="utf-8")

    print(prompt, file=out)
    print(f"\n(also written to {scratch_path})", file=out)
    if _try_copy_to_clipboard(prompt):
        print("(also copied to your clipboard)", file=out)
    return scratch_path


def read_pasted_response(lines_source=None, out=sys.stdout) -> str:
    """Read the human's pasted-back reply: lines until a line that is exactly
    SENTINEL. `lines_source` is an injectable iterable of lines for testing;
    defaults to reading from sys.stdin."""
    print(f"\nPaste the LLM's JSON/YAML response below, then a line containing only {SENTINEL}:", file=out)
    source = lines_source if lines_source is not None else sys.stdin
    collected: list[str] = []
    for line in source:
        line = line.rstrip("\n")
        if line == SENTINEL:
            break
        collected.append(line)
    return "\n".join(collected)


def parse_llm_response(text: str) -> dict:
    """JSON first, then a stripped markdown fence retried as JSON, then YAML
    (design doc S3.6 -- D8's own wording: "produces a json or yaml, whichever
    fits"). Raises ValueError with a clear message if all three fail -- including
    when a candidate parses cleanly but isn't an object (e.g. a pasted JSON
    array), since every step's OUTPUT_SCHEMA is an object and callers rely on
    dict-shaped output (validate_output(), result["reviewer_mode"] = ...)."""
    stripped = text.strip()

    try:
        result = json.loads(stripped)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    fence_stripped = stripped
    if fence_stripped.startswith("```"):
        lines = fence_stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        fence_stripped = "\n".join(lines).strip()
        try:
            result = json.loads(fence_stripped)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    try:
        import yaml

        result = yaml.safe_load(fence_stripped)
        if isinstance(result, dict):
            return result
    except Exception:
        pass

    raise ValueError("could not parse the pasted response as a JSON or YAML object")


def run_copy_paste_step(
    step_name: str,
    module,
    input_obj: dict,
    *,
    scratch_dir: Path = Path("."),
    max_retries: int = 3,
    lines_source=None,
    out=sys.stdout,
) -> dict:
    """The full D8 copy-paste loop for one step (design doc S3.1 steps 3-8b):
    compose -> deliver -> capture -> parse -> validate -> retry-on-failure ->
    return the validated result, or raise CopyPasteValidationError if the
    retry budget is exhausted."""
    prompt = compose_prompt(step_name, module, input_obj)
    deliver_prompt(prompt, scratch_dir, out=out)

    for attempt in range(1, max_retries + 1):
        raw = read_pasted_response(lines_source=lines_source, out=out)
        try:
            result = parse_llm_response(raw)
        except ValueError as e:
            print(f"BLOCKED (attempt {attempt}/{max_retries}): {e}", file=out)
            continue

        # This function IS the copy-paste driver -- the correct provenance value
        # is a fact about which code path ran, not something the pasted text can
        # accurately self-report. Force it rather than trusting/defaulting it, so
        # an LLM that echoed the wrong mode doesn't produce mislabeled provenance.
        # The FIELD is a REQUIRED module declaration (MODE_FIELD), so the driver
        # stays generic across step contracts (vision-review: reviewer_mode;
        # decision-capture: capture_mode) and a new step that forgets to declare
        # it fails loudly here rather than silently writing a wrong key.
        mode_field = getattr(module, "MODE_FIELD", None)
        if mode_field is None:
            raise CopyPasteValidationError(
                f"step contract '{step_name}' must declare MODE_FIELD (the output "
                "field naming which D8 mode produced the result)"
            )
        result[mode_field] = "copy-paste"

        ok, errors = module.validate_output(result)
        if ok:
            return result

        print(f"BLOCKED (attempt {attempt}/{max_retries}): the pasted response failed validation:", file=out)
        for e in errors:
            print(f"  - {e}", file=out)
        if attempt < max_retries:
            print("Fix these fields in your response and paste the corrected JSON below:", file=out)

    raise CopyPasteValidationError(
        f"copy-paste response for '{step_name}' still failed validation after {max_retries} attempts"
    )
