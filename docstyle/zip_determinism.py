#!/usr/bin/env python3
"""
zip_determinism.py: POST-RENDER normalization of the OOXML zip container's own
nondeterministic cruft (D24) -- the mechanical half of making the render
pipeline idempotent (running it twice on the same logical input produces the
same output, byte-for-byte).

What actually varies, verified empirically (not assumed) before writing this:

1. pandoc's OWN docx writer already honors SOURCE_DATE_EPOCH (the
   reproducible-builds.org convention) for both docProps/core.xml's
   dcterms:created/modified content AND every zip entry's own mtime -- two
   independent `pandoc ... -o out.docx` runs on identical input, with
   SOURCE_DATE_EPOCH set, are already byte-identical (verified: whole-file
   comparison, not just spot-checked parts). Without it, both vary with
   wall-clock time. This repo had SOURCE_DATE_EPOCH sitting unused in
   container/Containerfile and container/render as an ambient env var picked
   up by nothing -- it works today only by accidental shell-inheritance when
   a caller happens to export it before invoking render-doc.sh (true inside
   the container wrapper, false for a bare dev-host or CI invocation, which
   is why render-doc.sh now resolves and exports it explicitly instead of
   leaving that to chance).
2. python-docx (and this repo's own raw-zip writers: heading_numbering.py,
   docstyle/custom_properties.py, roundtrip/provenance.py's _OpcCoreProps)
   does NOT honor SOURCE_DATE_EPOCH: python-docx's Document.save() calls
   zipfile.ZipFile.writestr(name, data) with a plain string name, so Python's
   zipfile module auto-generates a ZipInfo whose date_time is
   time.localtime() at save time -- every entry, on every save, unconditional
   wall-clock, verified at the zipfile source level (docx/opc/phys_pkg.py).
   Because python-docx rewrites the WHOLE zip in one shot, this affects every
   member, not just the ones a given pass actually touched (verified: two
   independent full-pipeline renders differed in date_time on all ~20
   members, not just the ones style_postprocess.py/heading_numbering.py/
   custom_properties.py modify).
3. zipfile.ZipInfo also defaults `create_system` to 0 on win32, 3 (Unix)
   everywhere else -- a real cross-platform determinism gap this repo's own
   CI matrix (ubuntu + windows, CONTRIBUTING.md) would otherwise hit on every
   run, verified at the zipfile source level (not yet a single-host
   verification, since this was written on one platform, but the source
   behavior is unambiguous and CI is the actual verification, gates/ track).

Fix: (a) render-doc.sh now resolves SOURCE_DATE_EPOCH once (default 1700000000,
matching container/render's existing convention, so a bare dev-host render
matches the container's) and exports it before invoking pandoc, closing gap 1;
(b) this module's `normalize()` runs ONCE, as the LAST content-mutating step
in render-doc.sh (after every python-docx/raw-zip save that would otherwise
re-introduce wall-clock timestamps), pinning every entry's date_time,
create_system, and external_attr to fixed values, closing gaps 2 and 3.
Member order and content are never touched -- only per-entry metadata.

Deliberately NOT normalized, by design, not oversight: D11 provenance's
`rendered_at` field (embedded in docProps/core.xml's dc:identifier when
PROVENANCE=auto, the default) is INTENTIONALLY wall-clock -- its entire
purpose is recording when a render actually happened. A full render with
provenance embedding is therefore NEVER byte-identical to a later
independent render of the same source, by design; only the zip-container
cruft this module targets is spurious. See docs/DECISIONS.md D24 for the
full reasoning and for how the idempotency verification gate (a separate,
later PR) is expected to account for this (compare with PROVENANCE=off, or
exclude the one JSON field, not treat the whole artifact as one opaque blob).

Idempotent by construction: normalize() returns False (nothing written) when
every entry's date_time/create_system/external_attr already match the target,
the same "true no-op, not just an assumed one" bar heading_numbering.py's own
idempotency test already holds itself to.

Usage (post-render, in place):
  python zip_determinism.py OUT.docx [OUT2.docx ...]
  python zip_determinism.py OUT.docx --source-date-epoch 1700000000
  python zip_determinism.py OUT.docx --check   # report only, write nothing
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import zipfile
from pathlib import Path

SOURCE_DATE_EPOCH_DEFAULT = 1700000000  # matches container/render's own existing default
CREATE_SYSTEM = 0  # pin to one value (0 = FAT/Windows convention); Word never reads this field
EXTERNAL_ATTR = 0o600 << 16  # rw for owner; matches what python-docx/pandoc already emit in practice


def resolve_source_date_epoch(env: dict | None = None) -> int:
    """SOURCE_DATE_EPOCH from the environment, falling back to the same fixed
    default container/render already uses -- so a bare dev-host render and a
    containerized one produce the same timestamps without either needing to
    set anything. An empty string counts as unset (matches the `-` vs `:-`
    distinction render-doc.sh's own optional-filter variables already draw:
    here there is no "explicitly disable" meaning for an empty value, so
    treating empty as unset, not as "epoch 0", is the least surprising
    reading)."""
    raw = (env if env is not None else os.environ).get("SOURCE_DATE_EPOCH", "")
    if not raw:
        return SOURCE_DATE_EPOCH_DEFAULT
    return int(raw)


def _dos_date_time(epoch: int) -> tuple[int, int, int, int, int, int]:
    t = time.gmtime(epoch)
    year = max(t.tm_year, 1980)  # the zip format has no representation before 1980
    return (year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)


def normalize(path: Path, epoch: int | None = None) -> bool:
    """Rewrite every zip entry's date_time/create_system/external_attr to
    fixed values; content, compression type, and member order are untouched.
    Returns True if anything was actually rewritten, False if the file
    already matched (a true no-op -- nothing is written to disk in that
    case)."""
    target_epoch = epoch if epoch is not None else resolve_source_date_epoch()
    target_dt = _dos_date_time(target_epoch)

    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        already_normalized = all(
            i.date_time == target_dt and i.create_system == CREATE_SYSTEM
            and i.external_attr == EXTERNAL_ATTR
            for i in infos
        )
        if already_normalized:
            return False
        members = [(i, zf.read(i.filename)) for i in infos]

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for info, data in members:
            new_info = zipfile.ZipInfo(info.filename, date_time=target_dt)
            new_info.compress_type = info.compress_type
            new_info.create_system = CREATE_SYSTEM
            new_info.external_attr = EXTERNAL_ATTR
            zf.writestr(new_info, data)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Normalize zip-container timestamps/platform metadata (not content) "
                    "on a rendered docx/xlsx/pptx/vsdx, for reproducible-build idempotency."
    )
    ap.add_argument("artifact", nargs="+", type=Path)
    ap.add_argument("--source-date-epoch", type=int, default=None,
                     help="override; default resolves SOURCE_DATE_EPOCH env, else 1700000000")
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    args = ap.parse_args(argv)

    epoch = args.source_date_epoch if args.source_date_epoch is not None else resolve_source_date_epoch()
    rc = 0
    for artifact in args.artifact:
        if args.check:
            with zipfile.ZipFile(artifact) as zf:
                target_dt = _dos_date_time(epoch)
                already = all(
                    i.date_time == target_dt and i.create_system == CREATE_SYSTEM
                    and i.external_attr == EXTERNAL_ATTR
                    for i in zf.infolist()
                )
            print(f"{artifact}: {'already normalized' if already else 'would normalize'}")
            if not already:
                rc = 1
            continue
        changed = normalize(artifact, epoch)
        print(f"{artifact}: {'normalized' if changed else 'already normalized'} (epoch {epoch})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
