#!/usr/bin/env python3
"""
render -- the single renderfact entry point (execution plan chunk 0.1 + 0.2).

One command surface dispatching to the existing, working per-mode pipelines,
instead of three incompatible invocation patterns (container/render's podman
wrapper, render-doc.sh's own flag set, lint/render.py's own flag set). This
is a thin dispatcher, not a rewrite -- the two proven pipelines (render-doc.sh
for DOCX, lint/render.py for diagrams) keep their internal logic unchanged;
only the entry point unifies.

Usage:
    render docx <source.md> [render-doc.sh flags...]
    render diagram <files...> [--output-dir DIR] [--formats svg,pdf]
    render init-ai [--assistant claude|copilot|all]     # D8 harness mode (chunk 3.2)
    render copy-paste <step> [--tier T] [--image PATH] [--metrics-json PATH]  # D8 copy-paste mode (chunk 3.4)
    render provenance embed <docx|xlsx|pptx> --source <source.md>   # D11 provenance embed (chunk 4.1)
    render provenance extract <docx|xlsx|pptx>                       # D11 provenance extract (chunk 4.1)
    render provenance adopt <docx|xlsx|pptx> --source <new.md>       # bootstrap provenance for an
                                                                       # externally-authored artifact with
                                                                       # no source/history yet (chunk 4.1)
    render provenance retarget <old-artifact> <new-artifact>         # carry provenance onto a
                                                                       # differently-formatted artifact
                                                                       # of the same content (chunk 4.1)
    render import-template <corporate.docx> [--out-dir DIR] [--copy-reference]
                                               [--check <probe.md>]     # C7 template import
                                               # (style axis): derive template-profile.yaml
                                               # from a branded DOCX template
    render project <source.md> --profiles <cfg.yaml> --profile <name> | --all
                                               # F1 projection engine: one full-candor
                                               # source -> one governed render per profile
    render qa leaks|tables|paras|figs|all ...  # deterministic post-render QA gate
    render serve [--port N] [--enable-ui] [--root DIR]   # localhost HTTP API + thin UI (chunk 5.1)
    render container <podman-args...>          # raw passthrough to container/render
    render doctor [--json]                     # host tools vs tools.lock: warn, never fail (1.5)
    render gate <files...> [--stages vale]     # fail-closed pre-publish QA gate chain (B3)
    render reingest <edited.docx> --source <md> [--apply]   # D11 mechanical re-ingestion (4.4)
    render drawio generate|reingest ...        # C8 editable-diagram round-trip, drawio adapter
    render vsdx generate|reingest ...          # C8.2 editable-diagram round-trip, Visio adapter
    render decision-capture --source <g> --reingest <j>  # C8.3 capture edit intent (deterministic+gate)

Modes not yet wired: pdf (typst path), deck (marp path), poster -- tracked in
docs/ROADMAP.md (Track A entry A3; see also the roadmap-formats note in CHANGELOG.md).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
CONTAINER_DIR = REPO_ROOT / "container"
LINT_DIR = REPO_ROOT / "lint"


def _find_bash() -> str | None:
    """Locate a bash interpreter (git-bash/MSYS on Windows, native elsewhere).

    On Windows, PATH's first `bash` is often the System32 WSL stub, which exits 1
    uselessly when no WSL distro is installed (and translates paths wrongly when
    one is) -- prefer Git for Windows' bash explicitly before falling back to
    whatever PATH resolves. First caught by CI on windows-latest (D10 evidence)."""
    import os
    import shutil

    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        for cand in (
            Path(program_files) / "Git" / "bin" / "bash.exe",
            Path(program_files) / "Git" / "usr" / "bin" / "bash.exe",
        ):
            if cand.exists():
                return str(cand)
    for name in ("bash", "bash.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def run_docx(args: list[str]) -> int:
    """Dispatch to render-doc.sh (bash), unmodified -- the proven DOCX pipeline."""
    script = CONTAINER_DIR / "render-doc.sh"
    if not script.exists():
        print(f"ERROR: {script} not found", file=sys.stderr)
        return 3
    bash = _find_bash()
    if not bash:
        print(
            "ERROR: bash not found on PATH (render-doc.sh requires bash; "
            "on Windows install git-bash / MSYS2)",
            file=sys.stderr,
        )
        return 3
    result = subprocess.run([bash, str(script), *args])
    return result.returncode


def run_diagram(args: list[str]) -> int:
    """Dispatch to lint/render.py's own argument parsing + main(), in-process."""
    sys.path.insert(0, str(LINT_DIR))
    import render as diagram_render  # lint/render.py

    old_argv = sys.argv
    try:
        sys.argv = ["render.py", *args]
        return diagram_render.main()
    finally:
        sys.argv = old_argv


def run_container(args: list[str]) -> int:
    """Raw passthrough to container/render (the podman wrapper) -- unmodified."""
    script = CONTAINER_DIR / "render"
    if not script.exists():
        print(f"ERROR: {script} not found", file=sys.stderr)
        return 3
    bash = _find_bash()
    if not bash:
        print("ERROR: bash not found on PATH", file=sys.stderr)
        return 3
    result = subprocess.run([bash, str(script), *args])
    return result.returncode


def run_doctor(args: list[str]) -> int:
    """Native-mode version-drift check against tools.lock (D10 / chunk 1.5):
    reports OK/DRIFT/MISSING per pinned tool, warns and never fails closed."""
    sys.path.insert(0, str(REPO_ROOT))
    import doctor

    return doctor.main(args)


def run_tokens(args: list[str]) -> int:
    """Dispatch to tokens/gen/generate_all.py -- brand.yaml -> per-engine themes (A1)."""
    tokens_gen_dir = REPO_ROOT / "tokens" / "gen"
    sys.path.insert(0, str(tokens_gen_dir))
    import generate_all  # tokens/gen/generate_all.py

    old_argv = sys.argv
    try:
        sys.argv = ["generate_all.py", *args]
        return generate_all.main()
    finally:
        sys.argv = old_argv


def run_init_ai(args: list[str]) -> int:
    """Dispatch to contracts/init_ai.py -- D8 harness mode (chunk 3.2): install
    renderfact-aware instructions into the user's own configured assistant."""
    sys.path.insert(0, str(REPO_ROOT))
    from contracts import init_ai

    return init_ai.main(args)


def run_copy_paste(args: list[str]) -> int:
    """Dispatch to contracts/copy_paste.py -- D8 copy-paste mode (chunk 3.4).

    Per D8's own wording ("the scripts should ask the input, the intent, then
    produce all the scaffolding"): any of --tier/--image/--metrics-json omitted
    on the command line is asked for interactively instead of failing."""
    sys.path.insert(0, str(REPO_ROOT))
    from contracts import copy_paste, init_ai

    steps = dict(init_ai.step_contracts())

    parser = argparse.ArgumentParser(
        prog="render copy-paste",
        description="Run one D8 step in copy-paste mode: assemble a self-contained "
                    "prompt, paste it into any chat LLM, paste the JSON/YAML reply back.",
    )
    parser.add_argument("step", choices=sorted(steps))
    parser.add_argument("--tier", default=None)
    parser.add_argument("--image", default=None, help="path to the rendered diagram image")
    parser.add_argument(
        "--metrics-json", default=None,
        help="deterministic metrics as a literal JSON object, or a path to a JSON file",
    )
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument(
        "--threshold", type=float,
        default=float(os.environ.get("RENDERFACT_VISION_THRESHOLD", 0.6)),
        help="D16 gate: accept the deterministic metrics-only verdict at/above this confidence "
             "(zero LLM tokens); escalate below. Env RENDERFACT_VISION_THRESHOLD. Default 0.6.",
    )
    parser.add_argument(
        "--force-review", action="store_true",
        help="bypass the D16 gate and always run the LLM review (e.g. for compositional coverage "
             "of a clean diagram the gate would otherwise accept).",
    )
    parsed = parser.parse_args(args)

    module = steps[parsed.step]

    # This CLI assembles the vision-review-shaped input (tier/image/metrics).
    # A step that DECLARES HAS_OWN_GATE has its own richer command with a
    # deterministic-first gate (e.g. `render decision-capture`) and is not driven
    # from here; point the user at its own door rather than mis-prompting. A
    # declared flag, not a duck-typed proxy on VALID_TIERS.
    if getattr(module, "HAS_OWN_GATE", False):
        print(f"'{parsed.step}' has its own command with a deterministic-first gate -- "
              f"use: render {parsed.step} --escalate copy-paste", file=sys.stderr)
        return 2

    tier = parsed.tier or input(f"tier ({'/'.join(module.VALID_TIERS)}): ").strip()
    image = parsed.image or input("rendered image path: ").strip()

    # Metrics: an explicit --metrics-json wins; otherwise, if the step can
    # assemble them from the image itself (vision-review over an SVG), do that so
    # the D16 gate has a canonical source instead of a hand-supplied dict.
    metrics_raw = parsed.metrics_json
    if metrics_raw:
        metrics_path = Path(metrics_raw)
        deterministic_metrics = (
            json.loads(metrics_path.read_text(encoding="utf-8"))
            if metrics_path.exists() else json.loads(metrics_raw)
        )
    elif hasattr(module, "assemble_metrics") and image.lower().endswith(".svg"):
        deterministic_metrics = module.assemble_metrics(Path(image), tier)
    else:
        metrics_raw = input("deterministic metrics (JSON object, or a path to a JSON file): ").strip()
        metrics_path = Path(metrics_raw)
        deterministic_metrics = (
            json.loads(metrics_path.read_text(encoding="utf-8"))
            if metrics_path.exists() else json.loads(metrics_raw)
        )

    input_obj = module.assemble_input(image, tier, deterministic_metrics)

    # D16 gate: run the deterministic verdict FIRST and escalate to the LLM only
    # past the threshold. Gate BEFORE prompt assembly so the accept path spends
    # zero tokens. Only steps that declare a gate participate; others (no
    # confidence/gate) run the LLM unconditionally, as before.
    if not parsed.force_review and hasattr(module, "gate") and hasattr(module, "deterministic_entry"):
        decision, score = module.gate(input_obj, parsed.threshold)
        print(f"[D16 gate] confidence {score} vs threshold {parsed.threshold} -> {decision}",
              file=sys.stderr)
        if decision == "accept":
            entry = module.deterministic_entry(input_obj)
            ok, errors = module.validate_output(entry)
            if not ok:
                print(f"ERROR: deterministic entry failed validation: {errors}", file=sys.stderr)
                return 1
            print(json.dumps(entry, indent=2))
            return 0

    try:
        result = copy_paste.run_copy_paste_step(
            parsed.step, module, input_obj, scratch_dir=REPO_ROOT, max_retries=parsed.max_retries
        )
    except copy_paste.CopyPasteValidationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


def run_provenance(args: list[str]) -> int:
    """Dispatch to roundtrip/provenance.py -- D11 part 2 provenance embed/extract/
    adopt (chunk 4.1). Not yet auto-called by render-doc.sh: the script is
    generalized now, the call simply is not wired yet (and per D14, wiring it must
    be projection-profile-aware: full internal, stripped external)."""
    sys.path.insert(0, str(REPO_ROOT / "roundtrip"))
    import provenance  # roundtrip/provenance.py

    return provenance.main(args)


def run_import_template(args: list[str]) -> int:
    """Dispatch to docstyle/template_import.py: C7 template import (style axis),
    derive a template-profile.yaml (+ optional reference.docx copy) from a branded
    corporate DOCX template, so the first render through render-doc.sh reproduces
    the template's own look with no hand-written profile."""
    sys.path.insert(0, str(REPO_ROOT))
    from docstyle import template_import

    return template_import.main(args)


def run_project(args: list[str]) -> int:
    """Dispatch to projection/projector.py -- the F1 projection engine: one
    full-candor source -> one governed render per audience/clearance profile."""
    sys.path.insert(0, str(REPO_ROOT))
    from projection import projector

    return projector.main(args)


def run_serve(args: list[str]) -> int:
    """Dispatch to api/app.py, the stdlib HTTP API (chunk 5.1, D9/D15): the D8
    step contracts and the projection engine over localhost HTTP, with the
    thin reference UI at /ui when --enable-ui is passed."""
    sys.path.insert(0, str(REPO_ROOT))
    from api import app as api_app

    return api_app.main(args)


def run_qa(args: list[str]) -> int:
    """Dispatch to lint/render_qa.py, the deterministic post-render QA gate:
    leak scan on rendered text, table-geometry pressure, overweight paragraphs,
    figure contrast pre-filter. Report-only by default; leaks --fail-on-hits
    turns it into a CI gate."""
    sys.path.insert(0, str(LINT_DIR))
    import render_qa

    return render_qa.main(args)


def run_reingest(args: list[str]) -> int:
    """Dispatch to roundtrip/reingest.py: mechanical DOCX re-ingestion (D11 part
    3a, chunk 4.4): provenance verdict + reviewer-edit report, report-only by
    default; --apply back-ports the mechanically safe fast-forward subset."""
    sys.path.insert(0, str(REPO_ROOT / 'roundtrip'))
    import reingest

    return reingest.main(args)


def run_drawio(args: list[str]) -> int:
    """Dispatch to roundtrip/drawio.py: the editable-diagram round-trip, drawio
    adapter (C8): generate a .drawio with stable IDs + provenance from a concept
    graph; re-ingest hand-edits with ID-first semantic/style/layout routing."""
    sys.path.insert(0, str(REPO_ROOT / 'roundtrip'))
    import drawio

    return drawio.main(args)


def run_decision_capture(args: list[str]) -> int:
    """Dispatch to roundtrip/decision_capture.py: the editable-diagram
    round-trip decision-capture step (C8.3). Turns a reingest's semantic diff
    into a decision-log entry -- deterministic first, escalating to an LLM (D8
    copy-paste) only when confidence misses the threshold (the D16 fuzzy gate)."""
    sys.path.insert(0, str(REPO_ROOT / 'roundtrip'))
    import decision_capture

    return decision_capture.main(args)


def run_vsdx(args: list[str]) -> int:
    """Dispatch to roundtrip/visio.py: the editable-diagram round-trip, Visio
    adapter (C8.2): generate a .vsdx with NameU anchors + OPC provenance from a
    concept graph; re-ingest hand-edits with ID-first semantic/layout routing.
    Needs the optional 'vsdx' library (pip install renderfact[vsdx])."""
    sys.path.insert(0, str(REPO_ROOT / 'roundtrip'))
    import visio

    return visio.main(args)


def run_gate(args: list[str]) -> int:
    """Dispatch to gates/run_gates.py: the deterministic fail-closed QA gate
    chain (B3). Findings fail; a requested stage with no tool installed fails."""
    sys.path.insert(0, str(REPO_ROOT))
    from gates import run_gates

    return run_gates.main(args)


MODES = {
    "docx": run_docx,
    "diagram": run_diagram,
    "tokens": run_tokens,
    "init-ai": run_init_ai,
    "copy-paste": run_copy_paste,
    "provenance": run_provenance,
    "reingest": run_reingest,
    "drawio": run_drawio,
    "vsdx": run_vsdx,
    "decision-capture": run_decision_capture,
    "import-template": run_import_template,
    "project": run_project,
    "qa": run_qa,
    "serve": run_serve,
    "gate": run_gate,
    "container": run_container,
    "doctor": run_doctor,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="render",
        description="renderfact single entry point -- dispatches to the per-mode pipeline.",
    )
    parser.add_argument(
        "mode",
        choices=sorted(MODES),
        help="Which pipeline to invoke",
    )
    parser.add_argument(
        "mode_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed through unchanged to the selected mode's own pipeline",
    )
    args = parser.parse_args()
    return MODES[args.mode](args.mode_args)


if __name__ == "__main__":
    sys.exit(main())
