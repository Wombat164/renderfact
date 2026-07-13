#!/usr/bin/env python3
"""idempotency.py: a `render gate` stage (Track B7/D24 follow-up) that actually
RUNS the render pipeline twice on the same markdown source and asserts the
scoped byte-identity claim D24 established empirically, rather than trusting
it stays true as the pipeline evolves.

What "byte-identical" means here, precisely (see docs/DECISIONS.md D24/D25,
verified empirically before this gate was written, not assumed):

- Every zip member of the two rendered .docx files must be byte-identical,
  EXCEPT docProps/core.xml, where only the `rendered_at` value inside D11's
  embedded provenance JSON (dc:identifier) may differ -- that field is
  INTENTIONALLY wall-clock (D11's whole purpose is recording when a render
  happened), not a residual determinism gap this gate should flag.
- Because a source's FIRST-EVER render mutates its own frontmatter
  (roundtrip/source_uid.py persists a fresh renderfact_uid), this gate never
  compares against the real source file directly: it copies the source into
  an isolated scratch directory, does one PRIMING render there (establishing
  a stable renderfact_uid in the COPY, never touching the real file -- a gate
  must be read-only), then takes the two REAL comparison renders from that
  now-stable copy.
- When --check-pdf is requested, the DOCX->PDF path (LibreOffice/Word-COM,
  container/render-doc.sh's --pdf) is exercised too. PDF bytes are not
  expected to be byte-identical (the converter's own metadata/producer string
  can vary), so the comparison is PIXEL-level instead: each PDF is rasterized
  page-by-page (poppler's pdftoppm) and compared with Pillow when available,
  falling back to exact PNG-byte comparison (no tolerance) when Pillow is not
  installed -- pdftoppm's own output is itself deterministic for identical
  input, so the fallback is still a real check, just not a tolerant one.

Usage (as a render-gate stage):
    render gate source.md --stages idempotency
    render gate source.md --stages idempotency --idempotency-check-pdf
    render gate source.md --stages idempotency --idempotency-pixel-tolerance 0.001

Fail-closed, matching every other stage in gates/run_gates.py: a source this
gate cannot even render (pandoc/bash unusable) is TOOL_MISSING, not skipped;
requesting --idempotency-check-pdf with no working PDF converter configured
is also TOOL_MISSING (a requested check that silently produces no PDF is not
a check that ran).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RENDER_PY = REPO_ROOT / "render.py"

_RENDERED_AT_RE = re.compile(rb'"rendered_at":"[^"]*?"')


def _resolve_md_files(targets: list[str]) -> list[Path]:
    files: list[Path] = []
    for t in targets:
        p = Path(t)
        if p.is_dir():
            files.extend(sorted(q for q in p.rglob("*.md")))
        elif p.suffix.lower() == ".md":
            files.append(p)
    return files


def _normalize_core_xml(data: bytes) -> bytes:
    """Strip the one intentionally-wall-clock field (D11's rendered_at,
    embedded in dc:identifier's provenance JSON) before comparing
    docProps/core.xml -- see the module docstring."""
    return _RENDERED_AT_RE.sub(b'"rendered_at":"NORMALIZED"', data)


def compare_docx(a: Path, b: Path) -> list[str]:
    """Every zip member must be byte-identical in BOTH content and zip-entry
    metadata (date_time/create_system/external_attr -- exactly what D24's
    zip_determinism.py normalizes; a content-only compare would be blind to a
    regression there), except docProps/core.xml's content (normalized first,
    since D11's rendered_at is intentionally wall-clock). Returns a list of
    human-readable diff descriptions; empty means byte-identical under this
    scoped definition."""
    diffs: list[str] = []
    with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
        infos_a = {i.filename: i for i in za.infolist()}
        infos_b = {i.filename: i for i in zb.infolist()}
        names_a, names_b = set(infos_a), set(infos_b)
        if names_a != names_b:
            diffs.append(f"member set differs: only in A: {sorted(names_a - names_b)}, "
                         f"only in B: {sorted(names_b - names_a)}")
        for name in sorted(names_a & names_b):
            ia, ib = infos_a[name], infos_b[name]
            da, db = za.read(name), zb.read(name)
            if name == "docProps/core.xml":
                da, db = _normalize_core_xml(da), _normalize_core_xml(db)
            if da != db:
                diffs.append(f"{name}: content differs")
            if ia.date_time != ib.date_time:
                diffs.append(f"{name}: zip-entry date_time differs ({ia.date_time} vs {ib.date_time})")
            if ia.create_system != ib.create_system:
                diffs.append(f"{name}: zip-entry create_system differs "
                             f"({ia.create_system} vs {ib.create_system})")
            if ia.external_attr != ib.external_attr:
                diffs.append(f"{name}: zip-entry external_attr differs "
                             f"({ia.external_attr} vs {ib.external_attr})")
    return diffs


def _rasterize_pdf(pdf: Path, outdir: Path, pdftoppm: str) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    prefix = outdir / "page"
    subprocess.run([pdftoppm, "-png", "-r", "100", str(pdf), str(prefix)],
                   capture_output=True, text=True, timeout=120, check=True)
    return sorted(outdir.glob("page-*.png"))


def compare_pdf_pixels(a: Path, b: Path, tolerance: float, pdftoppm: str) -> list[str]:
    """Rasterize both PDFs page-by-page and compare. tolerance is the maximum
    fraction of differing pixels (per page) still considered a pass; 0.0
    requires exact pixel-identity. Falls back to exact PNG-byte comparison
    (tolerance ignored) when Pillow is not installed."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pages_a = _rasterize_pdf(a, tmp_path / "a", pdftoppm)
        pages_b = _rasterize_pdf(b, tmp_path / "b", pdftoppm)
        if len(pages_a) != len(pages_b):
            return [f"page count differs: {len(pages_a)} vs {len(pages_b)}"]
        if not pages_a:
            return ["pdftoppm produced no pages for either PDF"]

        try:
            from PIL import Image, ImageChops
        except ImportError:
            diffs = []
            for pa, pb in zip(pages_a, pages_b):
                if pa.read_bytes() != pb.read_bytes():
                    diffs.append(f"{pa.name}: PNG bytes differ (Pillow not installed: "
                                 "exact byte comparison only, no pixel tolerance)")
            return diffs

        diffs = []
        for pa, pb in zip(pages_a, pages_b):
            with Image.open(pa) as ia, Image.open(pb) as ib:
                if ia.size != ib.size:
                    diffs.append(f"{pa.name}: page size differs: {ia.size} vs {ib.size}")
                    continue
                diff = ImageChops.difference(ia.convert("RGB"), ib.convert("RGB")).convert("L")
                bbox = diff.getbbox()
                if bbox is None:
                    continue
                # histogram(), not getdata() (deprecated in Pillow 14): bucket 0 is
                # "no difference in any channel at this pixel", every other bucket
                # is a differing pixel.
                differing = sum(diff.histogram()[1:])
                total = ia.size[0] * ia.size[1]
                frac = differing / total
                if frac > tolerance:
                    diffs.append(f"{pa.name}: {frac:.4%} pixels differ (tolerance {tolerance:.4%})")
        return diffs


def _render_once(python_exe: str, src: Path, out_dir: Path, resource_path: str,
                 check_pdf: bool, runner) -> tuple[int, str]:
    # RESOURCE_PATH is env-var-only (container/render-doc.sh's own "consumer
    # skin configuration" contract) -- there is no --resource-path CLI flag;
    # passing it as one gets silently swallowed as a positional SUFFIX
    # argument instead and corrupts the output filename (found the hard way
    # while building this).
    args = [python_exe, str(RENDER_PY), "docx", str(src)]
    if check_pdf:
        args.append("--pdf")
    proc = runner(args, capture_output=True, text=True, timeout=180,
                 env={**os.environ, "OUTPUT_DIR": str(out_dir), "RESOURCE_PATH": resource_path})
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def check(targets: list[str], check_pdf: bool, pixel_tolerance: float,
         which, runner) -> tuple[str, str]:
    """The actual stage logic, returning (status, detail) in
    gates/run_gates.py's StageResult vocabulary (PASS|FAIL|TOOL_MISSING|
    NO_FILES) -- run_gates.py's own run_idempotency() wraps this into a real
    StageResult, the same "heavy logic in a helper module, thin STAGES
    wrapper in run_gates.py itself" shape run_plain_language/plain_language.py
    already established. which/runner have no defaults here (unlike every
    run_gates.py stage function): this module is not itself a STAGES entry,
    so there is no bare/standalone call site to default them for."""
    files = _resolve_md_files(targets)
    if not files:
        return "NO_FILES", "no .md sources among the targets"

    pdftoppm = which("pdftoppm") if check_pdf else None
    if check_pdf and not pdftoppm:
        return ("TOOL_MISSING",
               "--idempotency-check-pdf requested but pdftoppm (poppler-utils) "
               "is not installed; a requested check that cannot run is a FAILED "
               "gate, not a skipped one")

    python_exe = sys.executable
    all_diffs: dict[str, list[str]] = {}
    checked = 0

    for src in files:
        with tempfile.TemporaryDirectory() as scratch:
            scratch_path = Path(scratch)
            probe_src = scratch_path / src.name
            probe_src.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            resource_path = str(src.resolve().parent)

            rc, out = _render_once(python_exe, probe_src, scratch_path / "prime",
                                   resource_path, check_pdf, runner)
            if rc == 3 and ("pandoc not found" in out or "bash not found" in out):
                return "TOOL_MISSING", "render pipeline engines (pandoc/bash) not available"
            if rc != 0:
                all_diffs[str(src)] = [f"priming render failed (exit {rc}): {out[-500:]}"]
                continue

            out_a, out_b = scratch_path / "a", scratch_path / "b"
            failed = False
            for out_dir in (out_a, out_b):
                rc, out = _render_once(python_exe, probe_src, out_dir, resource_path,
                                       check_pdf, runner)
                if rc != 0:
                    all_diffs[str(src)] = [f"comparison render failed (exit {rc}): {out[-500:]}"]
                    failed = True
                    break
            if failed:
                continue

            docx_a = sorted(out_a.glob("*.docx"))
            docx_b = sorted(out_b.glob("*.docx"))
            if len(docx_a) != 1 or len(docx_b) != 1:
                all_diffs[str(src)] = [f"expected exactly one .docx per render, got "
                                       f"{len(docx_a)} and {len(docx_b)}"]
                continue

            checked += 1
            diffs = compare_docx(docx_a[0], docx_b[0])

            if check_pdf:
                pdf_a = sorted(out_a.glob("*.pdf"))
                pdf_b = sorted(out_b.glob("*.pdf"))
                if len(pdf_a) != 1 or len(pdf_b) != 1:
                    return ("TOOL_MISSING",
                           f"{src}: --idempotency-check-pdf requested but no PDF "
                           "was produced (no PDF converter configured -- "
                           "PDF_CONVERTER_PS1 / LibreOffice; see B6)")
                diffs += [f"PDF pixel: {d}" for d in
                         compare_pdf_pixels(pdf_a[0], pdf_b[0], pixel_tolerance, pdftoppm)]

            if diffs:
                all_diffs[str(src)] = diffs

    if all_diffs:
        lines = []
        for src, diffs in all_diffs.items():
            lines.append(f"  {src}:")
            lines.extend(f"    {d}" for d in diffs)
        return ("FAIL",
               f"{len(all_diffs)}/{len(files)} source(s) not idempotent:\n" + "\n".join(lines))
    return ("PASS",
           f"{checked} source(s), two independent renders each, byte-identical "
           f"(scoped: rendered_at excluded)" + (", PDF pixel-identical" if check_pdf else ""))
