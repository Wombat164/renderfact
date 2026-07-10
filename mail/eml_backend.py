"""eml_backend.py: render markdown to a plain-text, sendable .eml file (issue #95).

The email peer of pdf/typst_backend.py (PDF) and container/render-doc.sh (DOCX):
a governed markdown source, plus a skin-supplied signature block, becomes a
directly-openable RFC822 email instead of a rendered document a person has to
manually copy into a mail client and re-sign by hand.

Scope decision (docs/DECISIONS.md D21): this backend emits `.eml` (RFC822,
plain text, stdlib `email` module) rather than the binary Outlook `.msg`/MAPI
format, and rather than driving a mail client's compose window through a
platform-specific automation interface. `.eml` is openable/importable by
essentially every mail client (Outlook included), is a portable, dependency-
free, testable open format, and is where the actual "sendable email with a
reconciliation path back to source" need is met. A `.msg` writer and mail-
client automation are both heavier, platform-specific follow-up work, tracked
as roadmap items, not built here.

The body stays a single text/plain part (no MIME multipart HTML signature): a
plain-text signature block is a straightforward extension of "plain-text
body", while an HTML part raises its own MIME-structure and rendering
questions out of scope for this change (see docs/ROADMAP.md Track J). A
signature MAY also declare PNG image(s) (e.g. a logo): each becomes its own
inline-disposition `image/png` MIME part (`multipart/mixed`), riding along
with the message as a real embedded image rather than a hyperlink to one --
still no HTML markup, so there is no `cid:` reference rendering it inline
inside styled markup, but the image data itself travels inside the .eml.
"""

from __future__ import annotations

import re
import subprocess
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# Same byte-preserving frontmatter idiom as roundtrip/dossier_role.py and
# gates/run_gates.py's run_uids: locate the `---`-delimited block, yaml.safe_load
# it to read a few keys, never write anything back: this backend is read-only
# over the source, the same posture as every other frontmatter reader here.
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

# Placeholder-only, IANA-reserved TLD (RFC 2606): a deterministic, non-resolving
# Message-ID domain, so the emitted file never carries this build machine's real
# hostname (email.utils.make_msgid()'s own default domain is socket.getfqdn()).
_MSGID_DOMAIN = "renderfact.invalid"


class EmlBackendError(RuntimeError):
    """A backend precondition failed (missing tool/source/config), or a pandoc
    step failed."""


# ------------------------------------------------------------- frontmatter --

def _read_frontmatter(source: Path) -> dict:
    """Return the parsed frontmatter dict, or {} when absent/malformed."""
    text = source.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _clean(value) -> "str | None":
    """A frontmatter value as a stripped string, or None when unset/blank:
    the same whitespace-only-is-unset rule roundtrip/dossier_role.py applies."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resolve_recipient(frontmatter: dict, override: "str | None" = None) -> "str | None":
    """An explicit --recipient wins; otherwise `recipient:` wins over `to:`
    (issue #95's own field naming). None when nothing resolves: a recipient
    is not mandatory, the same "renders a valid, honest artifact with less
    input" posture --theme/--brand take on the pdf path."""
    if override:
        cleaned = override.strip()
        return cleaned or None
    return _clean(frontmatter.get("recipient")) or _clean(frontmatter.get("to"))


def resolve_subject(frontmatter: dict, source: Path, override: "str | None" = None) -> str:
    """An explicit --subject wins; otherwise `subject:` wins over the
    document's own `title:` (the subject-equivalent field the issue calls
    for); the source stem is the last-resort fallback, the same graceful
    default pdf/typst_backend.render_pdf uses for its own --title."""
    if override:
        cleaned = override.strip()
        return cleaned or source.stem
    return _clean(frontmatter.get("subject")) or _clean(frontmatter.get("title")) or source.stem


# ---------------------------------------------------------------- signature --

def load_signature(path: "str | Path | None") -> dict:
    """Load a skin's signature.yaml: `{"lines": [...], "from_email": str|None,
    "images": [Path, ...]}`. {} when no --signature is given: the same "zero
    consumer config still runs a valid pipeline, just with nothing skin-
    supplied applied" posture pdf/typst_backend.render_pdf's optional
    --theme/--brand follow.

    Freeform text `lines`, not a rigid name/title/department/phone schema:
    the same non-enum posture roundtrip/dossier_role.py and the projection
    engine's clearance/distribution ladders use for their own consumer-defined
    text (see mail/signature-example.yaml for the worked, fictional example).

    `images` is a list of PNG file paths (a logo, most commonly), resolved
    relative to the signature YAML's own directory when not absolute, the
    same "paths are skin-relative" convention a consumer's TEMPLATE_DOCX/
    reference.docx already follows. PNG only in v1 (what the config actually
    needs today); any other extension fails closed with an actionable message
    rather than silently attaching a file no mail client will render as an
    image the way this signature block intends."""
    if not path:
        return {}
    path = Path(path)
    if not path.is_file():
        raise EmlBackendError(f"signature config not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise EmlBackendError(f"signature config is not valid YAML: {e}") from None
    if not isinstance(data, dict):
        raise EmlBackendError(f"signature config must be a YAML mapping: {path}")
    lines = data.get("lines") or []
    if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
        raise EmlBackendError(f"signature config 'lines' must be a list of strings: {path}")
    raw_images = data.get("images") or []
    if not isinstance(raw_images, list) or not all(isinstance(x, str) for x in raw_images):
        raise EmlBackendError(f"signature config 'images' must be a list of PNG file paths: {path}")
    images = []
    for rel in raw_images:
        img_path = Path(rel)
        if not img_path.is_absolute():
            img_path = (path.parent / img_path).resolve()
        if img_path.suffix.lower() != ".png":
            raise EmlBackendError(f"signature image is not a .png file: {img_path}")
        if not img_path.is_file():
            raise EmlBackendError(f"signature image not found: {img_path}")
        images.append(img_path)
    return {"lines": list(lines), "from_email": _clean(data.get("from_email")), "images": images}


def compose_signed_body(body: str, signature_lines: list) -> str:
    """body, then (when a signature is configured) the sig-dash delimiter
    `-- ` alone on its own line and the signature lines, one per line.

    `-- ` on its own line (two hyphens, one trailing space, no leading text)
    is the long-standing plain-text-email convention (mutt, Thunderbird,
    Gmail, and Outlook all recognize it) that lets a mail client fold or
    strip the signature block on reply/quote: an intentionally different
    token from this repo's own prose "spaced double-hyphen" ban
    (CONTRIBUTING.md): that rule targets a dash used as sentence punctuation
    between words, not a stand-alone protocol marker with no text before or
    after it on its line."""
    body = body.rstrip("\n")
    if not signature_lines:
        return body + "\n"
    sig = "\n".join(signature_lines)
    return f"{body}\n\n-- \n{sig}\n"


# -------------------------------------------------------------------- body --

def md_to_plaintext(md_path: Path, pandoc: str, resource_path: "Path | None" = None) -> str:
    """Translate a markdown source to plain text via pandoc's plain writer.

    --from is the shared pandoc_markdown.MARKDOWN_FROM constant, the same
    convention pdf/typst_backend.md_to_typst follows (issue #69): without
    wikilinks_title_after_pipe a `[[target|Display Text]]` source link is read
    as literal text, not a Link node, and its display text never resolves.

    --reference-links keeps a link's URL from being silently dropped: pandoc's
    plain writer otherwise renders `[text](url)` as bare `text`, losing the
    URL entirely. With --reference-links the target lands in a trailing
    `[text]: url` reference list instead, plain-text-readable and lossless."""
    sys.path.insert(0, str(REPO_ROOT))
    from pandoc_markdown import MARKDOWN_FROM  # repo-root shared module

    cmd = [pandoc, "--from", MARKDOWN_FROM, str(md_path), "-t", "plain", "--reference-links"]
    if resource_path is not None:
        cmd += ["--resource-path", str(resource_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise EmlBackendError(f"pandoc markdown->plain failed:\n{result.stderr.strip()}")
    return result.stdout


# ------------------------------------------------------------------- render --

def render_eml(
    source: "str | Path",
    output: "str | Path | None" = None,
    *,
    signature: "str | Path | None" = None,
    recipient: "str | None" = None,
    subject: "str | None" = None,
    sender: "str | None" = None,
    pandoc: "str | None" = None,
) -> Path:
    """Render a markdown source to a plain-text, sendable RFC822 .eml. Returns
    the output path. Raises EmlBackendError on any missing tool or failed
    step."""
    source = Path(source)
    if not source.is_file():
        raise EmlBackendError(f"source not found: {source}")

    if pandoc is None:
        sys.path.insert(0, str(REPO_ROOT / "pdf"))
        import typst_backend  # pdf/typst_backend.py: the one pandoc-resolution
        # helper every pandoc-invoking backend in this repo shares (env
        # override > PATH > known Windows install dirs); reused rather than
        # re-implemented so the two backends cannot drift on tool discovery.
        try:
            pandoc = typst_backend.find_pandoc()
        except typst_backend.TypstBackendError as e:
            raise EmlBackendError(str(e)) from None

    frontmatter = _read_frontmatter(source)
    resolved_recipient = resolve_recipient(frontmatter, recipient)
    resolved_subject = resolve_subject(frontmatter, source, subject)
    sig = load_signature(signature)
    resolved_sender = sender or sig.get("from_email")

    if output is None:
        import os
        out_dir = Path(os.environ.get("OUTPUT_DIR", "renders"))
        out_dir.mkdir(parents=True, exist_ok=True)
        output = out_dir / f"{source.stem}.eml"
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    body = md_to_plaintext(source, pandoc, resource_path=source.parent)
    full_text = compose_signed_body(body, sig.get("lines") or [])

    if not resolved_recipient:
        print("WARNING: no recipient (frontmatter recipient:/to:, or --recipient): "
              "writing a draft .eml with no To: header", file=sys.stderr)

    msg = EmailMessage()
    if resolved_recipient:
        msg["To"] = resolved_recipient
    if resolved_sender:
        msg["From"] = resolved_sender
    msg["Subject"] = resolved_subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=_MSGID_DOMAIN)
    msg.set_content(full_text)

    # Signature image(s) (e.g. a logo): each becomes its own inline-disposition
    # image/png part. add_attachment() promotes the message to multipart/mixed
    # automatically on first call; a Content-ID is stamped (RFC 2392 angle-
    # bracket form, via the same make_msgid() helper the message itself uses)
    # for forward compatibility with a future HTML part that would reference it
    # by cid (unused by anything in this plain-text v1, but harmless to carry).
    for img_path in sig.get("images") or []:
        msg.add_attachment(
            img_path.read_bytes(), maintype="image", subtype="png",
            filename=img_path.name, disposition="inline",
            cid=make_msgid(domain=_MSGID_DOMAIN),
        )

    output.write_bytes(bytes(msg))
    return output


def main(argv: "list[str] | None" = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="render eml",
        description="Render a markdown source to a plain-text, sendable .eml (RFC822), "
                    "with an optional skin-supplied signature block (a peer of the docx/pdf paths).",
    )
    ap.add_argument("source", help="markdown source file")
    ap.add_argument("-o", "--output", default=None, help="output .eml path (default: renders/<stem>.eml)")
    ap.add_argument("--signature", default=None, metavar="YAML",
                    help="a skin's signature.yaml (see mail/signature-example.yaml); "
                         "omitted means no signature block is appended")
    ap.add_argument("--recipient", default=None,
                    help="overrides the source's recipient:/to: frontmatter")
    ap.add_argument("--subject", default=None,
                    help="overrides the source's subject:/title: frontmatter")
    ap.add_argument("--sender", default=None,
                    help="overrides the signature config's from_email: (the eml's From:)")
    args = ap.parse_args(argv)

    try:
        out = render_eml(args.source, args.output, signature=args.signature,
                         recipient=args.recipient, subject=args.subject, sender=args.sender)
    except EmlBackendError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
