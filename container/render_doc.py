#!/usr/bin/env python3
"""render_doc.py: annotated-markdown -> styled DOCX (+ optional PDF), with no shell.

THIS IS THE IMPLEMENTATION. `container/render-doc.sh` is a thin caller that execs this module,
so the shell entry point and `render docx` cannot drift apart: there is one pipeline, reachable
two ways.

WHY IT EXISTS (issue #157). The pipeline was a 433-line bash script, and `render docx` located a
bash to run it with. On a managed Windows machine that allows software by Authenticode signature
rather than by path, there is no bash to find: Git for Windows' `git.exe` is signed and runs, the
`bash.exe` beside it is not and does not, and MSYS2 ships unsigned too. So the whole DOCX half of
the tool was unreachable on a platform the project supports and runs CI against, and the error
message advised installing the one thing that cannot help.

The port is cheap because the shell was never doing the work: every functional step is already
`python <script>` or `pandoc`. What bash contributed was argument parsing, sequencing and
temp-file bookkeeping. The only genuinely external tools left are optional and confined to the
`--pdf` leg (`soffice`, or a Word-COM PowerShell converter), which is issue #120.

FIDELITY IS THE POINT, not improvement. This is a transcription: the same steps in the same order,
the same messages, the same exit codes, the same env-var contract, and the same "skip with an
honest message when a consumer piece is not configured" behaviour. Anything that looked worth
improving on the way was left alone and noted in the PR instead, because a port that also
redesigns cannot be reviewed against the original.

Exit codes (unchanged): 0 ok, 2 usage/source error, 3 a required tool is missing, and otherwise
the exit code of whichever step failed, matching `set -euo pipefail`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

USAGE = """Usage: render-doc.sh <source.md> [--name <p>] [--profile reference|compact]
         [--project <profile>] [--template-profile <yaml>] [DRAFT|REVIEW|FINAL]
         [--pdf] [--qc] [--qc-blocking] [--lint] [--number-headings] [--no-toc]
         [--scheme <scheme>] [--page-check] [--postrender-gate]

Renders annotated markdown to a styled DOCX (and optionally a PDF).

  --name <p>            output filename prefix (default: the source's basename)
  --profile <p>         house-style profile passed to the post-processor
  --project <profile>   project the source through a projection profile first
  --template-profile    yaml consumed by the style post-processor
  --scheme <scheme>     heading-numbering scheme (with --number-headings)
  --pdf                 also produce a PDF (needs soffice, or PDF_CONVERTER_PS1)
  --qc                  run the consumer's pre-render QC script (advisory)
  --qc-blocking         as --qc, but a finding stops the render
  --lint                run the consumer's Vale bundle (advisory)
  --number-headings     inject field-based heading numbering
  --no-toc              omit the table of contents
  --page-check          run the consumer's page-economy analyzer
  --postrender-gate     run the consumer's content-safety gate (blocking)
  DRAFT|REVIEW|FINAL    lifecycle suffix in the output filename (default DRAFT)

Every consumer-supplied piece is configured by environment variable and is SKIPPED with an
honest message when it is not configured. See the comments at the top of container/render-doc.sh
for the full list (SKIN_DIR, TEMPLATE_DOCX, FILTERS_DIR, TEMPLATE_PROFILE, STYLE_POSTPROCESS,
QC_SCRIPT, NLQA_DIR, HEADING_NUMBERING, PAGECHECK_SCRIPT, POSTRENDER_GATE_SCRIPT,
PDF_CONVERTER_PS1, PROJECTION_CONFIG, RESOURCE_PATH, OUTPUT_DIR, PROVENANCE, PANDOC, PYTHON)."""


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _detect_os() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def _resolve_pandoc(os_name: str) -> str | None:
    """PANDOC env, else PATH, else the known Windows install locations.

    The Windows fallbacks are kept because pandoc's own installer does not always put itself on
    PATH, and a consumer who installed it normally should not have to set an env var.
    """
    explicit = os.environ.get("PANDOC")
    if explicit:
        return explicit
    found = shutil.which("pandoc")
    if found:
        return found
    if os_name == "windows":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = []
        if local:
            candidates.append(Path(local) / "Pandoc" / "pandoc.exe")
        user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        if user:
            candidates.append(Path("C:/Users") / user / "AppData/Local/Pandoc/pandoc.exe")
        candidates.append(Path("C:/Program Files/Pandoc/pandoc.exe"))
        for c in candidates:
            if c.is_file():
                return str(c)
    return None


def _resolve_python() -> str | None:
    """PYTHON env, else the interpreter running this driver.

    The shell searched PATH for python3 then python. Defaulting to sys.executable is strictly
    better: the helper scripts are this repo's own, and running them under a DIFFERENT interpreter
    than the one that imported this package is how a consumer ends up with the driver working and
    a helper failing on a missing dependency.
    """
    return os.environ.get("PYTHON") or sys.executable or shutil.which("python3") or shutil.which("python")


def _skin_default(skin_dir: str, relative: str) -> str:
    """The SKIN_DIR default for one piece: used only when it actually EXISTS.

    Existence-gating is deliberate and comes from the shell. A skin that supplies three of the
    five pieces should get three configured steps and two honest skips, not two paths that point
    at nothing and fail later with a confusing error.
    """
    if not skin_dir:
        return ""
    candidate = Path(skin_dir) / relative
    return str(candidate) if candidate.exists() else ""


def _env_or_skin(var: str, skin_dir: str, relative: str) -> str:
    return os.environ.get(var) or _skin_default(skin_dir, relative)


# The audience-vs-source-of-truth transform, ported from the awk program. Kept as one regex so it
# stays comparable to the original line by line.
_HEADING_ANNOTATION = re.compile(
    r" \((?:NEW in [^)]*"
    r"|normative, V[0-9.]*"
    r"|AUTHORITATIVE, V[0-9.]*"
    r"|authoritative tuples, V[0-9.]*"
    r"|RT-[0-9]* RESOLVED[^)]*)\)"
)


def strip_render_skip(text: str) -> str:
    """Drop `render:skip` blocks and strip editorial annotations from headings.

    A direct transcription of the awk program: the `skip` flag spans lines, the heading rewrite
    applies only to lines starting with `#`, and the frontmatter fences are passed through
    unchanged. The awk kept an `in_fm` state that never altered its output; it is preserved here
    as a comment rather than as dead code.
    """
    out = []
    skip = False
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if "<!-- render:skip -->" in stripped:
            skip = True
            continue
        if "<!-- /render:skip -->" in stripped:
            skip = False
            continue
        if skip:
            continue
        if stripped.startswith("#"):
            newline = line[len(stripped):]
            line = _HEADING_ANNOTATION.sub("", stripped) + newline
        out.append(line)
    return "".join(out)


def extract_version(text: str) -> str:
    """First `version:` line's second whitespace-separated field, else v1 (awk parity)."""
    for line in text.splitlines():
        if line.startswith("version:"):
            parts = line.split()
            if len(parts) >= 2:
                return parts[1]
            return "v1"
    return "v1"


def _load_yaml(path: str):
    import yaml  # imported lazily: the tool resolution errors should fire before this
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _run(cmd, *, check=True, env=None, quiet=False):
    """Run a step. `check` mirrors `set -e`: a failure aborts the render."""
    result = subprocess.run(cmd, env=env,
                            stdout=subprocess.DEVNULL if quiet else None,
                            stderr=subprocess.DEVNULL if quiet else None)
    if check and result.returncode != 0:
        raise _StepFailed(result.returncode)
    return result.returncode


class _StepFailed(Exception):
    def __init__(self, code: int):
        super().__init__(f"step failed with exit code {code}")
        self.code = code


def parse_args(argv):
    """Port of the shell's `while [ $# -gt 0 ]` loop, including its fallback rule.

    The fallback matters and is easy to get wrong: an unrecognised bare word becomes the SOURCE if
    one has not been seen yet, and otherwise overwrites the SUFFIX. That is how
    `render-doc.sh doc.md FINAL` and `render-doc.sh doc.md WHATEVER` both work today.
    """
    args = {
        "source": "", "name": "", "profile": "reference", "suffix": "DRAFT",
        "pdf": False, "qc": False, "qc_blocking": None, "lint": False,
        "number": False, "pagecheck": False, "postrender_gate": False,
        "no_toc": False, "scheme": "modern", "project_profile": "",
        "template_profile": None,
    }
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--name", "--profile", "--project", "--template-profile", "--scheme"):
            if i + 1 >= len(argv):
                _err(f"ERROR: {a} needs a value")
                raise SystemExit(2)
            value = argv[i + 1]
            key = {"--name": "name", "--profile": "profile", "--project": "project_profile",
                   "--template-profile": "template_profile", "--scheme": "scheme"}[a]
            args[key] = value
            i += 2
            continue
        if a == "--pdf":
            args["pdf"] = True
        elif a == "--qc":
            args["qc"] = True
        elif a == "--qc-blocking":
            args["qc"] = True
            args["qc_blocking"] = True
        elif a == "--lint":
            args["lint"] = True
        elif a == "--number-headings":
            args["number"] = True
        elif a == "--no-toc":
            args["no_toc"] = True
        elif a == "--page-check":
            args["pagecheck"] = True
        elif a == "--postrender-gate":
            args["postrender_gate"] = True
        elif a in ("DRAFT", "REVIEW", "FINAL"):
            args["suffix"] = a
        else:
            if not args["source"]:
                args["source"] = a
            else:
                args["suffix"] = a
        i += 1
    return args


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Help is answered before any tool resolution, so it works on a machine with neither pandoc
    # nor a configured skin. Issue #26: it must also beat the source-existence check below.
    if any(a in ("-h", "--help") for a in argv):
        print(USAGE)
        return 0

    os_name = _detect_os()

    pandoc = _resolve_pandoc(os_name)
    if not pandoc:
        _err("ERROR: pandoc not found (PATH or known install dirs)")
        return 3
    python = _resolve_python()
    if not python:
        _err("ERROR: python not found")
        return 3

    skin_dir = os.environ.get("SKIN_DIR", "")
    template_docx = _env_or_skin("TEMPLATE_DOCX", skin_dir, "reference.docx")
    filters_dir = _env_or_skin("FILTERS_DIR", skin_dir, "filters")
    template_profile = _env_or_skin("TEMPLATE_PROFILE", skin_dir, "template-profile.yaml")
    style_postprocess = os.environ.get("STYLE_POSTPROCESS") or str(REPO_ROOT / "docstyle" / "style_postprocess.py")
    qc_script = os.environ.get("QC_SCRIPT", "")
    qc_blocking_env = os.environ.get("QC_BLOCKING", "0") == "1"
    nlqa_dir = os.environ.get("NLQA_DIR", "")
    heading_numbering = os.environ.get("HEADING_NUMBERING") or str(REPO_ROOT / "docstyle" / "heading_numbering.py")
    pagecheck_script = os.environ.get("PAGECHECK_SCRIPT", "")
    postrender_gate_script = os.environ.get("POSTRENDER_GATE_SCRIPT", "")
    postrender_gate_advisory = os.environ.get("POSTRENDER_GATE_ADVISORY", "0") == "1"
    pdf_converter_ps1 = os.environ.get("PDF_CONVERTER_PS1", "")
    projection_config = os.environ.get("PROJECTION_CONFIG") or str(REPO_ROOT / "projection" / "profiles-example.yaml")
    projector = str(REPO_ROOT / "projection" / "projector.py")
    output_dir = Path(os.environ.get("OUTPUT_DIR") or "./renders")

    args = parse_args(argv)
    if args["template_profile"] is not None:
        template_profile = args["template_profile"]
    qc_blocking = qc_blocking_env if args["qc_blocking"] is None else True

    source = args["source"]
    if not source:
        _err("ERROR: <source.md> is required")
        return 2
    if not Path(source).is_file():
        _err(f"ERROR: source not found: {source}")
        return 2

    name = args["name"] or Path(source).with_suffix("").name
    resource_path = os.environ.get("RESOURCE_PATH") or str(Path(source).resolve().parent)
    output_dir.mkdir(parents=True, exist_ok=True)

    tmp_dir = Path(os.environ.get("TMPDIR") or __import__("tempfile").gettempdir())
    pid = os.getpid()
    orig_source = source
    projected = None

    try:
        if args["project_profile"]:
            print(f"Projecting source via profile '{args['project_profile']}' "
                  f"(projection engine, {projection_config})...")
            projected = tmp_dir / f"render-doc-projected-{pid}.md"
            with open(projected, "w", encoding="utf-8", newline="") as fh:
                result = subprocess.run(
                    [python, projector, source, "--profiles", projection_config,
                     "--profile", args["project_profile"], "--stdout", "--keep-frontmatter"],
                    stdout=fh)
            if result.returncode != 0:
                raise _StepFailed(result.returncode)
            source = str(projected)

        date = datetime.now().strftime("%Y%m%d")
        source_text = Path(source).read_text(encoding="utf-8", errors="replace")
        version = extract_version(source_text)
        suffix = args["suffix"]
        output_file = output_dir / f"{name}_{version}_{date}_{suffix}.docx"

        print(f"=== render-doc ({os_name}): annotated markdown -> DOCX ===")
        print(f"Source:  {source}")
        print(f"Output:  {output_file}")
        print(f"Version: {version}   Profile: {args['profile']}")
        if skin_dir:
            print(f"Skin:    {skin_dir}")
        print("")

        if args["qc"]:
            if qc_script and Path(qc_script).is_file():
                print(f"Pre-render QC ({Path(qc_script).name}) on source...")
                if qc_blocking:
                    _run([python, qc_script, source])
                elif _run([python, qc_script, source], check=False) != 0:
                    print("  (findings above are advisory, not blocking; set QC_BLOCKING=1 or "
                          "--qc-blocking to fail the render on findings)")
            else:
                print("Skipping --qc: no QC_SCRIPT configured (consumer skin supplies one).")
            print("")

        if args["lint"]:
            _run_lint(python, nlqa_dir, source, os_name)

        tmp_input = tmp_dir / f"render-doc-{pid}.md"
        tmp_input.write_text(strip_render_skip(source_text), encoding="utf-8", newline="")

        # Shared source of truth for the pandoc reader extensions (issue #69): pandoc_markdown.py
        # is the ONE place the wikilink extension is listed, so this driver and the typst backend
        # cannot drift the way they did before that fix.
        from_md = subprocess.run([python, str(REPO_ROOT / "pandoc_markdown.py")],
                                 capture_output=True, text=True)
        if from_md.returncode != 0:
            sys.stderr.write(from_md.stderr)
            raise _StepFailed(from_md.returncode)
        pandoc_from = from_md.stdout.strip() + os.environ.get("PANDOC_EXTRA_EXTENSIONS", "")

        no_toc = args["no_toc"]
        if template_profile and Path(template_profile).is_file():
            profile_yaml = _load_yaml(template_profile)
            if not profile_yaml.get("toc", True):
                no_toc = True

        pandoc_args = [f"--from={pandoc_from}", f"--resource-path={resource_path}"]
        if no_toc:
            print("Table of contents: disabled (--no-toc or template-profile toc: false).")
        else:
            print("Table of contents: enabled (default). Pass --no-toc, or set toc: false in")
            print("  --template-profile, to disable.")
            pandoc_args += ["--toc", "--toc-depth=2"]
        if template_docx and Path(template_docx).is_file():
            pandoc_args.append(f"--reference-doc={template_docx}")
            print(f"Running pandoc (reference-doc: {Path(template_docx).name})...")
        else:
            print("Running pandoc (no TEMPLATE_DOCX configured: pandoc built-in reference style)...")
        if filters_dir and Path(filters_dir).is_dir():
            # sorted(): the shell glob applied filters in name order, and filter order is
            # semantic, so this must not become filesystem order.
            for lf in sorted(Path(filters_dir).glob("*.lua")):
                if lf.is_file():
                    pandoc_args.append(f"--lua-filter={lf}")
                    print(f"  lua-filter: {lf.name}")
        _run([pandoc, *pandoc_args, "-o", str(output_file), str(tmp_input)])

        print("")
        if style_postprocess and Path(style_postprocess).is_file():
            print(f"Applying configured house style (profile: {args['profile']})...")
            cover_date = datetime.now().strftime("%d %B %Y")
            tp_arg = []
            if template_profile and Path(template_profile).is_file():
                tp_arg = ["--template-profile", template_profile]
                print(f"  template-profile: {Path(template_profile).name}")
            _run([python, style_postprocess, str(output_file), "--profile", args["profile"],
                  *tp_arg, "--cover-version", version, "--cover-date", cover_date])
        else:
            print("Skipping house-style pass: no STYLE_POSTPROCESS configured "
                  "(consumer skin supplies one).")

        tmp_input.unlink(missing_ok=True)
        if projected:
            Path(projected).unlink(missing_ok=True)
            projected = None

        if args["number"]:
            print("")
            if heading_numbering and Path(heading_numbering).is_file():
                print(f"Injecting field-based heading numbering (scheme: {args['scheme']})...")
                num_args = ["--scheme", args["scheme"]]
                if template_profile and Path(template_profile).is_file():
                    num_args += ["--profile", template_profile]
                _run([python, heading_numbering, str(output_file), *num_args])
            else:
                print("Skipping --number-headings: no HEADING_NUMBERING configured "
                      "(consumer skin supplies one).")

        if os.environ.get("PROVENANCE", "auto") != "off":
            print("")
            prov_tool = str(REPO_ROOT / "roundtrip" / "provenance.py")
            prov_strip = False
            if args["project_profile"]:
                profiles = _load_yaml(projection_config)
                prof = profiles["profiles"][args["project_profile"]]
                prov_strip = bool(prof.get("strip_provenance", False))
            if prov_strip:
                print(f"Provenance (D14): profile '{args['project_profile']}' is externally "
                      f"bound: stripping, not embedding...")
                _run([python, prov_tool, "strip", str(output_file)])
            else:
                print("Provenance (D11/D14): embedding source identity (from the canonical "
                      "source, not the projection)...")
                _run([python, prov_tool, "embed", str(output_file), "--source", orig_source])

        pdf_made = _maybe_pdf(args, os_name, output_file, output_dir, name, version, suffix,
                              pdf_converter_ps1)

        if args["pagecheck"]:
            print("")
            if pagecheck_script and Path(pagecheck_script).is_file():
                target = output_file
                pdf_path = output_file.with_suffix(".pdf")
                if pdf_made and pdf_path.is_file():
                    target = pdf_path
                print(f"Page-economy check ({Path(pagecheck_script).name})...")
                _run([python, pagecheck_script, str(target)], check=False)
            else:
                print("Skipping --page-check: no PAGECHECK_SCRIPT configured "
                      "(consumer skin supplies one).")

        if args["postrender_gate"]:
            print("")
            if postrender_gate_script and Path(postrender_gate_script).is_file():
                # Passed through so the gate can see which template-profile this render used;
                # docstyle/marking_lint.py (#123) is the first consumer. The shell `export`ed it.
                gate_env = dict(os.environ)
                if template_profile:
                    gate_env["TEMPLATE_PROFILE"] = template_profile
                print(f"Post-render content-safety gate ({Path(postrender_gate_script).name}) "
                      f"on {output_file.name}...")
                if postrender_gate_advisory:
                    if _run([python, postrender_gate_script, str(output_file)],
                            check=False, env=gate_env) != 0:
                        print("  (findings above are advisory, not blocking; "
                              "POSTRENDER_GATE_ADVISORY=1 is set)")
                else:
                    _run([python, postrender_gate_script, str(output_file)], env=gate_env)
            else:
                print("Skipping --postrender-gate: no POSTRENDER_GATE_SCRIPT configured "
                      "(consumer skin supplies one).")

        print("")
        print("=== render-doc complete ===")
        print(f"Output: {output_file}")
        if pdf_made:
            print(f"PDF:    {output_file.with_suffix('.pdf')}")
        return 0

    except _StepFailed as exc:
        return exc.code
    finally:
        if projected:
            Path(projected).unlink(missing_ok=True)


def _run_lint(python: str, nlqa_dir: str, source: str, os_name: str) -> None:
    if not (nlqa_dir and Path(nlqa_dir).is_dir()):
        print("Skipping --lint: no NLQA_DIR configured (consumer skin supplies one).")
        print("")
        return
    _run([python, str(Path(nlqa_dir) / "nlqa.py"), "gen-vale"], check=False, quiet=True)
    doc_lang = ""
    for line in Path(source).read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("lang:"):
            parts = re.split(r"[: ]+", line.strip())
            if len(parts) >= 2:
                doc_lang = parts[1].strip().lower()
            break
    vale_cfg = ".vale.ini" if doc_lang == "nl" else ".vale-common.ini"
    print(f"Consistency lint (Vale; lang={doc_lang or 'unknown'} -> {vale_cfg})...")
    vale_bin = shutil.which("vale")
    if not vale_bin and os_name == "windows":
        home = Path(os.environ.get("USERPROFILE") or Path.home())
        for c in (home / "AppData/Local/Microsoft/WinGet/Links/vale.exe",
                  home / "AppData/Local/Microsoft/WinGet/Links/vale"):
            if c.is_file():
                vale_bin = str(c)
                break
    if vale_bin:
        if _run([vale_bin, "--config", str(Path(nlqa_dir) / "vale" / vale_cfg), source],
                check=False) != 0:
            print("  (Vale findings above are advisory, not blocking)")
    else:
        print(f"  Vale not installed (rules refreshed under {nlqa_dir}/vale/, advisory).")
        if os_name == "windows":
            print("    install: winget install errata-ai.Vale")
    print("")


def _maybe_pdf(args, os_name, output_file: Path, output_dir: Path, name, version, suffix,
               pdf_converter_ps1) -> bool:
    if not args["pdf"]:
        return False
    pdf_file = output_file.with_suffix(".pdf")
    print("")
    pdf_made = False
    if os_name == "windows" and pdf_converter_ps1 and Path(pdf_converter_ps1).is_file():
        print("Converting to PDF via Word (TOC + fields refreshed)...")
        # No MSYS path-mangling guards needed here: without bash in the chain there is nothing
        # rewriting the argument, which is one class of Windows bug this port simply removes.
        _run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
              "-File", pdf_converter_ps1, str(output_file)])
        pdf_made = True
    elif shutil.which("soffice"):
        print("Converting to PDF via LibreOffice headless...")
        if _run(["soffice", "--headless", "--convert-to", "pdf", "--outdir",
                 str(output_dir), str(output_file)], check=False, quiet=True) == 0:
            pdf_made = True
    else:
        print("WARN: --pdf needs LibreOffice (soffice) on PATH, or PDF_CONVERTER_PS1 on Windows.")
        print("      For archival PDF use the typst path (render-pdf.py). Skipping PDF + prune.")

    if pdf_made:
        print(f"Pruning prior-dated {name}_{version}_*_{suffix} artefacts...")
        keep = {output_file.name, pdf_file.name}
        for ext in ("docx", "pdf"):
            for f in sorted(output_dir.glob(f"{name}_{version}_*_{suffix}.{ext}")):
                if f.name not in keep:
                    print(f"  removed {f.name}")
                    f.unlink(missing_ok=True)
    return pdf_made


if __name__ == "__main__":
    sys.exit(main())
