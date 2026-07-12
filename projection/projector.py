"""projector -- single SOURCE (with profiled fenced-div blocks) -> one governed RENDER per PROFILE.

The projection engine (chunk F1 -- the capability the README leads with). Generalized
2026-07-03 from a private reference consumer's proven implementation; the block syntax,
gate semantics, and gloss-injection behaviour are carried over unchanged, while every
site-specific assumption (hardcoded clearance/distribution ladders, adjacent-directory
config paths, a site-relative term-bank location) is now caller-supplied configuration.

Implements the DITA conditional-processing (ditaval) pattern in markdown, at the
PREPROCESSOR level (excluded content never enters any downstream parse tree -- the
Asciidoctor-conditionals security model the roadmap's C2 entry names):

  - clearance gate   no-read-up: a block's clearance rank must be <= the profile's
                     ceiling; a block's distribution extent must cover the profile's
  - disclosure       detail-only / abstract-variant / soft-spot blocks, per posture
                     (full > contextual > minimal)
  - lang-select      keep blocks matching the profile language, or language-neutral ones
  - audience lists   per-block allow-list (audience=) and deny-list (hide=)
  - gloss-inject     optional term bank: gloss the first body occurrence of terms the
                     profile's audience does not already know

Block syntax (Pandoc fenced div, unchanged):
  ::: {.block clearance="secret" releasable="partners" detail="true" lang="en" audience="reviewer"}
  ...content...
  :::

Config (YAML, see profiles-example.yaml): a `ladders:` mapping defining the ORDERED
clearance and distribution vocabularies (rank = list position), and a `profiles:`
mapping. Ladders are consumer-defined: the engine has no built-in classification
vocabulary of its own.

Fail-closed rule (deliberate hardening over the reference implementation, which
treated unknown clearance values as rank 0 = most permissive): a block or profile
using a value absent from the configured ladder raises ProjectionError. A gate that
guesses is not a gate.

Provenance note (D14): the projected-header HTML comment stamps profile name +
gate parameters + dropped-block count into the OUTPUT. Profiles for externally-bound
renders can suppress it with `stamp_header: false` -- same audience-awareness
principle as D14's provenance rule. Profiles can additionally set
`strip_provenance: true` (default false): the DOCX pipeline then scrubs renderfact
provenance metadata from artifacts rendered under that profile, and skips the
default embed. The full/none rule is D14 as ratified; an opaque-token third mode
is a documented future extension.

Usage:
    render project <source.md> --profiles <config.yaml> --profile <name> [-o out.md]
    render project <source.md> --profiles <config.yaml> --all [--output-dir DIR]
    render project <source.md> --profiles <config.yaml> --profile <name> --stdout
                   [--keep-frontmatter] [--terms-dir DIR]

Term-bank format (optional, --terms-dir): one .md file per term with YAML frontmatter:
    term: <the term>       gloss: <short explanation>
    assume: [audience-ids that already know it]
    forbid: [audience-ids it must never be glossed for]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml


class ProjectionError(ValueError):
    """Config/gate error worth a clean message, not a traceback."""


# ---------- config ----------

def load_config(path: Path) -> tuple[dict[str, dict[str, int]], dict[str, dict]]:
    """Return ({ladder_name: {value: rank}}, {profile_name: profile})."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "ladders" not in data or "profiles" not in data:
        raise ProjectionError(
            f"{path}: config must be a mapping with 'ladders:' and 'profiles:' keys"
        )
    ladders: dict[str, dict[str, int]] = {}
    for name in ("clearance", "distribution"):
        values = data["ladders"].get(name)
        if not isinstance(values, list) or not values:
            raise ProjectionError(f"{path}: ladders.{name} must be a non-empty ordered list")
        ladders[name] = {str(v): i for i, v in enumerate(values)}
    profiles = data["profiles"]
    if not isinstance(profiles, dict) or not profiles:
        raise ProjectionError(f"{path}: profiles must be a non-empty mapping")
    for pname, prof in profiles.items():
        prof["_name"] = pname
        _rank(ladders["clearance"], prof.get("clearance_ceiling"), f"profile {pname}: clearance_ceiling")
        _rank(ladders["distribution"], prof.get("releasable_to"), f"profile {pname}: releasable_to")
        for key in ("lang", "audience", "disclosure"):
            if key not in prof:
                raise ProjectionError(f"profile {pname}: missing required key '{key}'")
        if "strip_provenance" in prof and not isinstance(prof["strip_provenance"], bool):
            raise ProjectionError(f"profile {pname}: strip_provenance must be a boolean")
    return ladders, profiles


def _rank(ladder: dict[str, int], value: str | None, context: str) -> int:
    """Fail-closed ladder lookup: unknown values are an error, never a guess."""
    if value is None:
        raise ProjectionError(f"{context}: missing value")
    if value not in ladder:
        raise ProjectionError(
            f"{context}: {value!r} is not in the configured ladder {sorted(ladder)}"
        )
    return ladder[value]


# ---------- term bank (for gloss-inject) ----------

def load_terms(terms_dir: Path | None) -> dict[str, dict]:
    if terms_dir is None:
        return {}
    bank: dict[str, dict] = {}
    for f in sorted(Path(terms_dir).glob("*.md")):
        text = f.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not m:
            continue
        fm = yaml.safe_load(m.group(1)) or {}
        if not fm.get("term"):
            continue
        bank[fm["term"]] = {
            "gloss": fm.get("gloss", ""),
            "assume": set(fm.get("assume") or []),
            "forbid": set(fm.get("forbid") or []),
        }
    return bank


# ---------- parse source into text / block segments ----------

def parse_segments(text: str) -> list[tuple]:
    segs: list[tuple] = []
    buf: list[str] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = re.match(r"^:::+\s*\{(.*)\}\s*$", lines[i])
        if m:
            if buf:
                segs.append(("text", "\n".join(buf)))
                buf = []
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            body: list[str] = []
            i += 1
            while i < len(lines) and not re.match(r"^:::+\s*$", lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            segs.append(("block", attrs, "\n".join(body).strip()))
        else:
            buf.append(lines[i])
            i += 1
    if buf:
        segs.append(("text", "\n".join(buf)))
    return segs


# ---------- the projection decision per block ----------

def keep_block(attrs: dict[str, str], prof: dict, ladders: dict[str, dict[str, int]]) -> bool:
    clearance = ladders["clearance"]
    distribution = ladders["distribution"]
    lowest_clearance = min(clearance, key=clearance.get)
    widest_distribution = max(distribution, key=distribution.get)

    # clearance gate (no-read-up); unlabelled block = lowest rank, unknown label = error
    block_clr = _rank(clearance, attrs.get("clearance", lowest_clearance), "block clearance")
    if block_clr > clearance[prof["clearance_ceiling"]]:
        return False
    # distribution gate: the block's allowed extent must cover how far this render travels;
    # unlabelled block = widest extent (no restriction), unknown label = error
    block_ext = _rank(distribution, attrs.get("releasable", widest_distribution), "block releasable")
    if distribution[prof["releasable_to"]] > block_ext:
        return False
    if attrs.get("lang") and attrs["lang"] != prof["lang"]:
        return False  # language select (language-neutral blocks carry no lang=)
    if attrs.get("audience") and prof["audience"] not in _csv(attrs["audience"]):
        return False  # show ONLY to these audiences (allow-list)
    if attrs.get("hide") and prof["audience"] in _csv(attrs["hide"]):
        return False  # hide from these audiences (deny-list)
    posture = prof["disclosure"]
    if attrs.get("detail") == "true" and posture != "full":
        return False
    if attrs.get("variant") == "abstract" and posture == "full":
        return False  # abstract variants REPLACE detail in non-full postures
    if attrs.get("softspot") == "true" and posture not in ("full", "contextual"):
        return False
    return True


def _csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(",")]


# ---------- gloss-inject for the audience ----------

def gloss_inject(text: str, audience: str, bank: dict[str, dict]) -> str:
    lines = text.split("\n")
    for term in sorted(bank, key=len, reverse=True):
        info = bank[term]
        if audience in info["assume"] or audience in info["forbid"] or not info["gloss"]:
            continue
        pat = re.compile(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])")
        for idx, ln in enumerate(lines):  # gloss FIRST body (non-heading) occurrence
            if ln.lstrip().startswith("#"):
                continue
            if pat.search(ln):
                lines[idx] = pat.sub(f"{term} ({info['gloss']})", ln, count=1)
                break
    return "\n".join(lines)


# ---------- project one profile ----------

def project(source_path: Path, prof: dict, ladders: dict, bank: dict,
            keep_fm: bool = False) -> tuple[str, int]:
    raw = Path(source_path).read_text(encoding="utf-8")
    m = re.match(r"^---\n.*?\n---\n", raw, flags=re.DOTALL)  # source frontmatter
    fm = m.group(0) if m else ""
    if fm and not keep_fm:
        # Silent metadata loss is the actual footgun (issue seen in practice: a
        # downstream `render docx` then has no title to render, with nothing in
        # this command's own output pointing at why). Noisy by design.
        print(f"NOTE: {source_path}: source frontmatter (title, etc) dropped from "
              f"this projection ({prof['_name']}); pass --keep-frontmatter "
              f"to carry it into a downstream `render docx`.", file=sys.stderr)
    raw = raw[len(fm):]
    out: list[str] = []
    dropped = 0
    for seg in parse_segments(raw):
        if seg[0] == "text":
            if seg[1].strip():
                out.append(seg[1].strip())
        else:
            _, attrs, body = seg
            if keep_block(attrs, prof, ladders):
                out.append(body)
            else:
                dropped += 1
    body = "\n\n".join(out)
    body = gloss_inject(body, prof["audience"], bank)
    doc = body + "\n"
    if prof.get("stamp_header", True):
        header = (
            f"<!-- projected: profile={prof['_name']} audience={prof['audience']} "
            f"clearance<={prof['clearance_ceiling']} releasable={prof['releasable_to']} "
            f"lang={prof['lang']} disclosure={prof['disclosure']} | blocks_dropped={dropped} -->"
        )
        doc = header + "\n\n" + doc
    if keep_fm and fm:
        doc = fm + "\n" + doc  # re-attach frontmatter for downstream render pipelines
    return doc, dropped


# ---------- CLI ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render project",
        description="Project a profiled source into one governed render per profile.",
    )
    parser.add_argument("source", help="the full-candor markdown source")
    parser.add_argument("--profiles", required=True, help="ladders+profiles YAML config")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--profile", help="project this one profile")
    group.add_argument("--all", action="store_true", help="project every profile")
    parser.add_argument("-o", "--output", default=None, help="output path (single profile)")
    parser.add_argument("--output-dir", default=None,
                        help="output directory (default: alongside the source)")
    parser.add_argument("--stdout", action="store_true",
                        help="single profile -> stdout instead of a file")
    parser.add_argument("--keep-frontmatter", action="store_true",
                        help="re-attach the source frontmatter (for downstream pipelines)")
    parser.add_argument("--terms-dir", default=None,
                        help="optional term-bank directory for gloss-inject")
    args = parser.parse_args(argv)

    try:
        ladders, profiles = load_config(Path(args.profiles))
        bank = load_terms(Path(args.terms_dir) if args.terms_dir else None)
        targets = list(profiles) if args.all else [args.profile]
        for name in targets:
            if name not in profiles:
                raise ProjectionError(
                    f"unknown profile {name!r} (available: {', '.join(sorted(profiles))})"
                )
        if args.stdout:
            if args.all:
                raise ProjectionError("--stdout takes a single --profile, not --all")
            text, _ = project(Path(args.source), profiles[targets[0]], ladders, bank,
                              keep_fm=args.keep_frontmatter)
            sys.stdout.write(text)
            return 0
        out_dir = Path(args.output_dir) if args.output_dir else Path(args.source).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in targets:
            text, dropped = project(Path(args.source), profiles[name], ladders, bank,
                                    keep_fm=args.keep_frontmatter)
            outp = (Path(args.output) if (args.output and not args.all)
                    else out_dir / f"{Path(args.source).stem}--{name}.md")
            outp.write_text(text, encoding="utf-8", newline="\n")
            print(f"{name:24} -> {outp}  ({dropped} blocks dropped)")
        return 0
    except (ProjectionError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
