"""
provenance.py -- D11 part 2 (chunk 4.1): hidden provenance metadata embedded in
every rendered editable-document artifact -- DOCX, XLSX, PPTX (main, annex,
embedded-variant -- chunk 4.2 wires this into all three once the dual-output
path exists), and since C8.2 also VSDX (Visio is the same OPC package family;
handled by the generic in-zip adapter below because no managing library
exists). Deliberately excludes SVG/PNG (visual/diagram artifacts, not
round-trippable Office documents) and PDF (a flattened archival format, not
editable/re-ingestable the way D11 requires).

Every such artifact renderfact produces should carry, invisible in the
rendered body, enough to answer "what source, what version of it, when, with
what tool" -- the foundation D11 parts 3/4 (re-ingestion, conflict-merge)
build on: without this, a re-ingested file can't be checked against "what
source was this actually rendered from."

Mechanism: the OOXML core property dc:identifier (docProps/core.xml) -- the
SAME schema across DOCX/XLSX/PPTX (all three are OPC/OOXML packages), verified
unused by every render script in this repo before claiming it (grepped
container/ + lint/ for core_properties/properties usage: none), and verified
to actually round-trip through save/load for all three formats (python-docx,
openpyxl, python-pptx) before relying on it, not assumed. A single JSON blob
in that one property, not one core property per fact: every format's
properties object has only a handful of single-string slots (title/subject/
comments/created/modified/...), and every one besides identifier has real
Office-native meaning a user might set (or that the pipeline's own style
post-processing might set) and would not expect renderfact to silently
overwrite.

Deliberately NOT a custom XML part (docProps/custom.xml): none of the three
libraries has native support for it, and hand-rolling the OOXML content-types
+ relationship registration carries real corruption risk (a missing
registration can make Office show a "needs repair" prompt) for no functional
gain over the core_properties approach at this stage.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
_PREFIX = "renderfact:v1:"

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Provenance:
    source_uid: str
    source_version: str
    rendered_at: str
    tool_version: str
    # D11 part 4 hardening (2026-07-04): the exact git commit of the SOURCE's
    # repository at render time ("<sha>" or "<sha>-dirty"), None when the source
    # lives outside any git repo. Optional with a default so payloads embedded
    # before this field existed still extract cleanly.
    source_commit: str | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tool_version() -> str:
    """renderfact's own version -- the tool's git commit (D11 part 4: "git is
    inherent infrastructure"), reusing git as the version authority rather than
    inventing a separate semver scheme this repo doesn't have yet. Falls back
    to "unknown" if .git isn't present (e.g. a vendored/installed copy)."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=5, check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _load_docx(path: Path):
    from docx import Document

    return Document(str(path))


def _load_xlsx(path: Path):
    import openpyxl

    return openpyxl.load_workbook(str(path))


def _load_pptx(path: Path):
    import pptx

    return pptx.Presentation(str(path))


_CORE_XML_NS = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
}
_CORE_PART = "docProps/core.xml"
_MINIMAL_CORE_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<cp:coreProperties xmlns:cp="%s" xmlns:dc="%s"/>'
    % (_CORE_XML_NS["cp"], _CORE_XML_NS["dc"])
)


class _OpcCoreProps:
    """Generic OPC core-properties access for package formats none of the three
    Office libraries covers (today: .vsdx, C8.2 -- Visio is OPC exactly like
    DOCX/XLSX/PPTX; Microsoft's file-format introduction confirms
    docProps/core.xml, and the prior-art pass flagged the byte-level check as
    the first implementation task, done in this chunk's tests).

    Reads the whole package into memory, exposes `.identifier` backed by the
    dc:identifier element, and rewrites the zip on save. Only the core part
    (plus, when it has to be created, its content-type override and package
    relationship) changes; every other member is copied byte-identical, so
    page XML, masters and window state survive untouched. The module docstring
    warns hand-rolling registrations risks Office 'repair' prompts -- that is
    why the creation path registers BOTH entries and is covered by a dedicated
    test rather than assumed."""

    def __init__(self, path: Path):
        import zipfile

        self._members: list[tuple[str, bytes]] = []
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                self._members.append((name, zf.read(name)))
        self._names = {n for n, _ in self._members}

    def _core_root(self):
        import xml.etree.ElementTree as ET

        for name, data in self._members:
            if name == _CORE_PART:
                return ET.fromstring(data)
        return ET.fromstring(_MINIMAL_CORE_XML)

    @property
    def identifier(self) -> str:
        el = self._core_root().find("dc:identifier", _CORE_XML_NS)
        return (el.text or "") if el is not None else ""

    @identifier.setter
    def identifier(self, value: str) -> None:
        import xml.etree.ElementTree as ET

        root = self._core_root()
        el = root.find("dc:identifier", _CORE_XML_NS)
        if el is None:
            el = ET.SubElement(root, f"{{{_CORE_XML_NS['dc']}}}identifier")
        el.text = value or None
        ET.register_namespace("cp", _CORE_XML_NS["cp"])
        ET.register_namespace("dc", _CORE_XML_NS["dc"])
        payload = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
        if _CORE_PART in self._names:
            self._members = [(n, payload if n == _CORE_PART else d) for n, d in self._members]
        else:
            self._members.append((_CORE_PART, payload))
            self._names.add(_CORE_PART)
            self._register_core_part()

    def _register_core_part(self) -> None:
        import xml.etree.ElementTree as ET

        ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
        rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        rtype = ("http://schemas.openxmlformats.org/package/2006/"
                 "relationships/metadata/core-properties")
        new_members = []
        for name, data in self._members:
            if name == "[Content_Types].xml":
                root = ET.fromstring(data)
                if not any(o.get("PartName") == "/" + _CORE_PART
                           for o in root.iter(f"{{{ct_ns}}}Override")):
                    ET.SubElement(root, f"{{{ct_ns}}}Override", {
                        "PartName": "/" + _CORE_PART,
                        "ContentType": "application/vnd.openxmlformats-package."
                                       "core-properties+xml",
                    })
                ET.register_namespace("", ct_ns)
                data = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
            elif name == "_rels/.rels":
                root = ET.fromstring(data)
                if not any(r.get("Type") == rtype
                           for r in root.iter(f"{{{rel_ns}}}Relationship")):
                    taken = {r.get("Id") for r in root.iter(f"{{{rel_ns}}}Relationship")}
                    rid = next(f"rId{i}" for i in range(1, 1000) if f"rId{i}" not in taken)
                    ET.SubElement(root, f"{{{rel_ns}}}Relationship", {
                        "Id": rid, "Type": rtype, "Target": _CORE_PART,
                    })
                ET.register_namespace("", rel_ns)
                data = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
            new_members.append((name, data))
        self._members = new_members

    def save(self, path: Path) -> None:
        import zipfile

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in self._members:
                zf.writestr(name, data)


# Per format: (loader, properties-object-getter, saver). docx/pptx expose their
# OOXML core properties via a nested `.core_properties`; openpyxl exposes them
# directly as `.properties` on the workbook; .vsdx has no managing library, so
# the generic OPC adapter above edits docProps/core.xml in the zip directly.
# Each loader imports its library lazily, so using the DOCX path never requires
# openpyxl/python-pptx to be installed, and vice versa (.vsdx needs stdlib only).
_FORMAT_ADAPTERS = {
    ".docx": (_load_docx, lambda doc: doc.core_properties, lambda doc, path: doc.save(str(path))),
    ".pptx": (_load_pptx, lambda doc: doc.core_properties, lambda doc, path: doc.save(str(path))),
    ".xlsx": (_load_xlsx, lambda wb: wb.properties, lambda wb, path: wb.save(str(path))),
    ".vsdx": (_OpcCoreProps, lambda pkg: pkg, lambda pkg, path: pkg.save(path)),
}


def _adapter_for(path: Path):
    suffix = path.suffix.lower()
    if suffix not in _FORMAT_ADAPTERS:
        raise ValueError(
            f"unsupported artifact type '{suffix}' -- renderfact provenance supports "
            f"{sorted(_FORMAT_ADAPTERS)} (SVG/PNG/PDF are deliberately excluded, see module docstring)"
        )
    return _FORMAT_ADAPTERS[suffix]


def embed(artifact_path: Path, provenance: Provenance) -> None:
    """Embed provenance into an already-rendered DOCX/XLSX/PPTX. Overwrites any
    prior renderfact provenance if the file is re-rendered in place."""
    load, properties_of, save = _adapter_for(artifact_path)
    doc = load(artifact_path)
    properties_of(doc).identifier = _PREFIX + json.dumps(asdict(provenance), separators=(",", ":"))
    save(doc, artifact_path)


def extract(artifact_path: Path) -> Provenance | None:
    """Extract provenance from a DOCX/XLSX/PPTX, or None if it carries none
    (e.g. a file never rendered by renderfact, or a pre-chunk-4.1 render)."""
    load, properties_of, _save = _adapter_for(artifact_path)
    doc = load(artifact_path)
    raw = properties_of(doc).identifier or ""
    if not raw.startswith(_PREFIX):
        return None
    payload = json.loads(raw[len(_PREFIX):])
    return Provenance(**payload)


def strip(artifact_path: Path) -> bool:
    """Remove renderfact provenance from an artifact (D14: external/publish
    projections must not carry internal source identity). Returns True if
    provenance was present and removed, False if there was nothing to strip.

    Deliberately surgical: only clears a dc:identifier that carries the
    renderfact prefix. A foreign identifier (a DOI, an organisation's own
    document number) is never touched: stripping OUR metadata must not
    destroy someone else's."""
    load, properties_of, save = _adapter_for(artifact_path)
    doc = load(artifact_path)
    props = properties_of(doc)
    raw = props.identifier or ""
    if not raw.startswith(_PREFIX):
        return False
    props.identifier = ""
    save(doc, artifact_path)
    return True


class ProvenanceError(RuntimeError):
    """A user-facing provenance-workflow mistake (missing source, re-adopting
    an already-tracked artifact, adopting over an existing source) -- distinct
    from a bare exception so the CLI can print a clean message, not a
    traceback."""


def _source_uid_helpers():
    """Lazy import of roundtrip/source_uid.py -- avoids requiring REPO_ROOT
    (not just this file's own directory) on sys.path, which the render.py CLI
    dispatch path doesn't add."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import source_uid

    return source_uid.get_or_create_source_uid, source_uid.content_version


def build_provenance(source_path: Path) -> Provenance:
    """Assemble a Provenance from a canonical source -- the shared step behind
    both `embed` (an existing source) and `adopt` (a freshly-bootstrapped stub
    source). Raises ProvenanceError with an actionable message, not a bare
    FileNotFoundError, when source_path doesn't exist."""
    if not source_path.exists():
        raise ProvenanceError(
            f"source '{source_path}' does not exist. If this artifact was never "
            "rendered by renderfact (e.g. drafted directly in Office, no canonical "
            "source yet), use 'adopt' instead of 'embed' to bootstrap one."
        )
    get_or_create_source_uid, content_version = _source_uid_helpers()
    return Provenance(
        source_uid=get_or_create_source_uid(source_path),
        source_version=content_version(source_path),
        rendered_at=now_iso(),
        tool_version=tool_version(),
        source_commit=source_commit(source_path),
    )


def source_commit(source_path: Path) -> str | None:
    """The source repository's HEAD commit at render time, '-dirty'-suffixed when
    the source file itself has uncommitted changes; None outside a git repo.
    Makes every render traceable to an exact commit of its source (D11 part 4),
    independently of the TOOL's own version."""
    src_dir = source_path.resolve().parent
    try:
        head = subprocess.run(
            ["git", "-C", str(src_dir), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        if head.returncode != 0:
            return None
        sha = head.stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(src_dir), "status", "--porcelain", "--", str(source_path.resolve())],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else False
        return f"{sha}-dirty" if dirty else sha
    except (OSError, subprocess.TimeoutExpired):
        return None


def adopt(artifact_path: Path, source_path: Path) -> Provenance:
    """Bootstrap provenance for an artifact that has none yet -- e.g. a DOCX/
    XLSX/PPTX drafted directly in Office, never rendered by renderfact, with no
    canonical .md source and no ADR/justification/intent trail at all.

    Refuses two ways a caller could otherwise lose history silently:
      - the artifact ALREADY carries renderfact provenance -> use `embed` for a
        normal re-render, not `adopt` (adopt is a one-time bootstrap, not a way
        to reset an already-tracked document's history).
      - source_path ALREADY exists -> `adopt` is for a genuinely NEW source;
        point `embed` at the existing one instead.

    Creates a minimal stub source (frontmatter only -- `origin:
    adopted-external-draft` plus an adoption timestamp: an HONEST marker that
    no prior justification/ADR trail exists, rather than fabricating one;
    chunk 4.5's real contextualize/ADR step does not exist yet) at source_path,
    then embeds provenance exactly as `embed` does. Does NOT reverse-extract
    the artifact's body content into the stub -- DOCX/XLSX/PPTX -> markdown
    conversion is a distinct, much larger capability, out of scope here; a
    human (or a future ingest step) fills in the stub's real content."""
    if extract(artifact_path) is not None:
        raise ProvenanceError(
            f"'{artifact_path}' already carries renderfact provenance -- use 'embed', "
            "not 'adopt', for an already-tracked document."
        )
    if source_path.exists():
        raise ProvenanceError(
            f"source '{source_path}' already exists -- 'adopt' is only for bootstrapping "
            "a genuinely new source; use 'embed' to attach an existing one."
        )

    stub = (
        "---\n"
        "origin: adopted-external-draft\n"
        f"adopted_at: {now_iso()}\n"
        "---\n\n"
        f"<!-- renderfact: this source was bootstrapped from '{artifact_path.name}', an "
        "externally-authored artifact with no prior renderfact provenance. Replace "
        "this stub with the real canonical content. -->\n"
    )
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(stub, encoding="utf-8")

    prov = build_provenance(source_path)
    embed(artifact_path, prov)
    return prov


def retarget(old_artifact_path: Path, new_artifact_path: Path) -> Provenance:
    """Carry an artifact's provenance over to a DIFFERENTLY-FORMATTED artifact
    representing the SAME logical content -- e.g. deciding a DOCX would be
    better as an XLSX, without losing the link to the canonical source or the
    embedded provenance record itself.

    Preserves source_uid and source_version UNCHANGED (same canonical source,
    same content snapshot -- this is a format repackaging, not a re-render
    from a possibly-changed source); stamps a fresh rendered_at/tool_version
    (this IS a new physical artifact, produced right now, whatever format its
    content reached).

    new_artifact_path must already exist -- renderfact does not convert DOCX
    content into XLSX content itself (that's a distinct, much larger
    capability); this only carries the provenance link across an
    already-produced new-format file. Refuses if old_artifact_path has no
    provenance to carry over (use `adopt` on the new artifact instead), if
    new_artifact_path doesn't exist yet, or if new_artifact_path already
    carries DIFFERENT renderfact provenance (refusing to silently overwrite a
    different document's identity)."""
    old_prov = extract(old_artifact_path)
    if old_prov is None:
        raise ProvenanceError(
            f"'{old_artifact_path}' carries no renderfact provenance to retarget -- "
            "use 'adopt' on the new artifact instead."
        )
    if not new_artifact_path.exists():
        raise ProvenanceError(
            f"'{new_artifact_path}' does not exist yet -- retarget carries provenance onto "
            "an ALREADY-PRODUCED new-format artifact; render/save it first, then retarget."
        )
    existing_new_prov = extract(new_artifact_path)
    if existing_new_prov is not None and existing_new_prov.source_uid != old_prov.source_uid:
        raise ProvenanceError(
            f"'{new_artifact_path}' already carries DIFFERENT renderfact provenance "
            f"(source_uid={existing_new_prov.source_uid}) -- refusing to overwrite a "
            "different document's identity. Use 'embed' if you intend to re-point it "
            "at a different source deliberately."
        )

    new_prov = Provenance(
        source_uid=old_prov.source_uid,
        source_version=old_prov.source_version,
        rendered_at=now_iso(),
        tool_version=tool_version(),
    )
    embed(new_artifact_path, new_prov)
    return new_prov


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="render provenance",
        description="Embed, extract, or bootstrap (adopt) D11 provenance metadata on a DOCX/XLSX/PPTX (chunk 4.1).",
    )
    sub = ap.add_subparsers(dest="action", required=True)

    embed_ap = sub.add_parser("embed", help="embed provenance from an EXISTING source into a rendered artifact")
    embed_ap.add_argument("artifact", type=Path, help="the rendered .docx/.xlsx/.pptx file")
    embed_ap.add_argument("--source", type=Path, required=True, help="the canonical .md source rendered from")

    extract_ap = sub.add_parser("extract", help="print an artifact's embedded provenance as JSON")
    extract_ap.add_argument("artifact", type=Path, help="the .docx/.xlsx/.pptx file to inspect")

    adopt_ap = sub.add_parser(
        "adopt",
        help="bootstrap provenance for an artifact with NO source yet (e.g. drafted directly in Office)",
    )
    adopt_ap.add_argument("artifact", type=Path, help="the existing .docx/.xlsx/.pptx file to adopt")
    adopt_ap.add_argument(
        "--source", type=Path, required=True,
        help="path for the NEW stub canonical source (must not already exist)",
    )

    retarget_ap = sub.add_parser(
        "retarget",
        help="carry provenance from one artifact onto an already-produced differently-formatted one "
             "(e.g. a DOCX would be better as an XLSX) without losing the source link",
    )
    retarget_ap.add_argument("old_artifact", type=Path, help="the existing, already-tracked .docx/.xlsx/.pptx")
    retarget_ap.add_argument("new_artifact", type=Path, help="the already-produced new-format file to tag")

    strip_ap = sub.add_parser(
        "strip",
        help="remove renderfact provenance from an artifact (D14: externally-bound renders "
             "must not carry internal source identity); foreign identifiers are never touched",
    )
    strip_ap.add_argument("artifact", type=Path, help="the .docx/.xlsx/.pptx file to scrub")

    args = ap.parse_args(argv)

    try:
        if args.action == "embed":
            prov = build_provenance(args.source)
            embed(args.artifact, prov)
            print(f"embedded provenance into {args.artifact}: {json.dumps(asdict(prov))}")
            return 0

        if args.action == "adopt":
            prov = adopt(args.artifact, args.source)
            print(
                f"adopted {args.artifact}: bootstrapped {args.source} and embedded "
                f"provenance: {json.dumps(asdict(prov))}"
            )
            return 0

        if args.action == "retarget":
            prov = retarget(args.old_artifact, args.new_artifact)
            print(
                f"retargeted provenance from {args.old_artifact} onto {args.new_artifact}: "
                f"{json.dumps(asdict(prov))}"
            )
            return 0

        if args.action == "strip":
            if strip(args.artifact):
                print(f"stripped renderfact provenance from {args.artifact}")
            else:
                print(f"{args.artifact}: no renderfact provenance to strip (foreign identifiers untouched)")
            return 0
    except ProvenanceError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    prov = extract(args.artifact)
    if prov is None:
        print(f"{args.artifact}: no renderfact provenance found", file=sys.stderr)
        return 1
    print(json.dumps(asdict(prov), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
