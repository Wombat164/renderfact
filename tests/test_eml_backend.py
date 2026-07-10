"""
Tests for mail/eml_backend.py (issue #95): render a governed markdown source to
a plain-text, sendable RFC822 .eml, with a skin-supplied signature block.

Unit tests cover frontmatter resolution (recipient/to, subject/title, the
override-wins-over-frontmatter rule), signature-config loading and error
paths, and the sig-dash body composition. An integration test drives the real
pandoc-invoking render_eml() end to end and parses the produced .eml with
Python's stdlib email parser, skipped when pandoc is absent (as on some CI
runners). A dispatch test proves `render eml` routes. Every fixture below uses
entirely fictional names, addresses, and phone numbers (no real person, org,
or organisation-specific content).
"""

from __future__ import annotations

import email
import email.policy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "mail"))

import eml_backend as eb  # noqa: E402

RENDER_PY = REPO_ROOT / "render.py"
HAVE_PANDOC = shutil.which("pandoc") is not None

FICTIONAL_SIGNATURE = """\
from_email: "jane.doe@example.com"
lines:
  - "Jane Doe"
  - "Product Manager, Engineering"
  - "+1-555-0100"
  - "https://example.com/directory/jane-doe"
"""

# Same tiny synthetic 1x1 PNG tests/test_typst_backend.py already uses for its
# own image-staging tests, built programmatically, never a committed binary
# fixture (CONTRIBUTING.md).
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


# --------------------------------------------------------------- frontmatter --

def test_resolve_recipient_from_recipient_key():
    assert eb.resolve_recipient({"recipient": "  Alex Rivera <alex.rivera@example.com>  "}) == \
        "Alex Rivera <alex.rivera@example.com>"


def test_resolve_recipient_falls_back_to_to_key():
    assert eb.resolve_recipient({"to": "alex.rivera@example.com"}) == "alex.rivera@example.com"


def test_resolve_recipient_recipient_wins_over_to():
    fm = {"recipient": "alex.rivera@example.com", "to": "someone-else@example.com"}
    assert eb.resolve_recipient(fm) == "alex.rivera@example.com"


def test_resolve_recipient_cli_override_wins_over_frontmatter():
    fm = {"recipient": "alex.rivera@example.com"}
    assert eb.resolve_recipient(fm, override="override@example.com") == "override@example.com"


def test_resolve_recipient_none_when_absent():
    assert eb.resolve_recipient({}) is None


def test_resolve_recipient_whitespace_only_is_unset():
    assert eb.resolve_recipient({"recipient": "   "}) is None


def test_resolve_subject_from_subject_key(tmp_path):
    src = tmp_path / "note.md"
    src.write_text("# x\n", encoding="utf-8")
    assert eb.resolve_subject({"subject": "Q3 status update", "title": "Something else"}, src) == \
        "Q3 status update"


def test_resolve_subject_falls_back_to_title(tmp_path):
    src = tmp_path / "note.md"
    src.write_text("# x\n", encoding="utf-8")
    assert eb.resolve_subject({"title": "Q3 status update"}, src) == "Q3 status update"


def test_resolve_subject_falls_back_to_source_stem(tmp_path):
    src = tmp_path / "q3-status-update.md"
    src.write_text("# x\n", encoding="utf-8")
    assert eb.resolve_subject({}, src) == "q3-status-update"


def test_resolve_subject_cli_override_wins(tmp_path):
    src = tmp_path / "note.md"
    src.write_text("# x\n", encoding="utf-8")
    fm = {"subject": "From frontmatter", "title": "Also frontmatter"}
    assert eb.resolve_subject(fm, src, override="From CLI") == "From CLI"


def test_read_frontmatter_absent_returns_empty_dict(tmp_path):
    src = tmp_path / "note.md"
    src.write_text("Just a body, no frontmatter.\n", encoding="utf-8")
    assert eb._read_frontmatter(src) == {}


def test_read_frontmatter_malformed_yaml_returns_empty_dict(tmp_path):
    src = tmp_path / "note.md"
    src.write_text("---\nrecipient: [unterminated\n---\n\nBody.\n", encoding="utf-8")
    assert eb._read_frontmatter(src) == {}


# ----------------------------------------------------------------- signature --

def test_load_signature_none_path_returns_empty_dict():
    assert eb.load_signature(None) == {}


def test_load_signature_missing_file_raises(tmp_path):
    with pytest.raises(eb.EmlBackendError, match="not found"):
        eb.load_signature(tmp_path / "nope.yaml")


def test_load_signature_malformed_yaml_raises(tmp_path):
    f = tmp_path / "sig.yaml"
    f.write_text("lines: [unterminated\n", encoding="utf-8")
    with pytest.raises(eb.EmlBackendError, match="not valid YAML"):
        eb.load_signature(f)


def test_load_signature_not_a_mapping_raises(tmp_path):
    f = tmp_path / "sig.yaml"
    f.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(eb.EmlBackendError, match="must be a YAML mapping"):
        eb.load_signature(f)


def test_load_signature_lines_not_list_of_strings_raises(tmp_path):
    f = tmp_path / "sig.yaml"
    f.write_text("lines:\n  - ok\n  - 42\n", encoding="utf-8")
    with pytest.raises(eb.EmlBackendError, match="list of strings"):
        eb.load_signature(f)


def test_load_signature_valid_fictional_fixture(tmp_path):
    f = tmp_path / "sig.yaml"
    f.write_text(FICTIONAL_SIGNATURE, encoding="utf-8")
    sig = eb.load_signature(f)
    assert sig["from_email"] == "jane.doe@example.com"
    assert sig["lines"] == [
        "Jane Doe", "Product Manager, Engineering", "+1-555-0100",
        "https://example.com/directory/jane-doe",
    ]


def test_load_signature_no_from_email_is_none(tmp_path):
    f = tmp_path / "sig.yaml"
    f.write_text('lines:\n  - "Jane Doe"\n', encoding="utf-8")
    assert eb.load_signature(f)["from_email"] is None


def test_load_signature_no_images_key_is_empty_list(tmp_path):
    f = tmp_path / "sig.yaml"
    f.write_text('lines:\n  - "Jane Doe"\n', encoding="utf-8")
    assert eb.load_signature(f)["images"] == []


def test_load_signature_images_resolves_relative_to_yaml_dir(tmp_path):
    (tmp_path / "logo.png").write_bytes(_PNG)
    f = tmp_path / "sig.yaml"
    f.write_text('lines:\n  - "Jane Doe"\nimages:\n  - "logo.png"\n', encoding="utf-8")
    sig = eb.load_signature(f)
    assert sig["images"] == [(tmp_path / "logo.png").resolve()]


def test_load_signature_images_missing_file_raises(tmp_path):
    f = tmp_path / "sig.yaml"
    f.write_text('lines:\n  - "Jane Doe"\nimages:\n  - "nope.png"\n', encoding="utf-8")
    with pytest.raises(eb.EmlBackendError, match="signature image not found"):
        eb.load_signature(f)


def test_load_signature_images_non_png_extension_raises(tmp_path):
    (tmp_path / "logo.jpg").write_bytes(_PNG)
    f = tmp_path / "sig.yaml"
    f.write_text('lines:\n  - "Jane Doe"\nimages:\n  - "logo.jpg"\n', encoding="utf-8")
    with pytest.raises(eb.EmlBackendError, match="not a .png file"):
        eb.load_signature(f)


def test_load_signature_images_not_list_of_strings_raises(tmp_path):
    f = tmp_path / "sig.yaml"
    f.write_text('lines:\n  - "Jane Doe"\nimages:\n  - 42\n', encoding="utf-8")
    with pytest.raises(eb.EmlBackendError, match="list of PNG file paths"):
        eb.load_signature(f)


# ------------------------------------------------------------- body compose --

def test_compose_signed_body_appends_sig_dash_and_lines():
    out = eb.compose_signed_body("Hello there.\n", ["Jane Doe", "+1-555-0100"])
    assert out == "Hello there.\n\n-- \nJane Doe\n+1-555-0100\n"


def test_compose_signed_body_no_signature_no_delimiter():
    out = eb.compose_signed_body("Hello there.\n", [])
    assert out == "Hello there.\n"
    assert "-- " not in out


def test_compose_signed_body_strips_trailing_blank_lines_before_delimiter():
    out = eb.compose_signed_body("Hello there.\n\n\n", ["Jane Doe"])
    assert out == "Hello there.\n\n-- \nJane Doe\n"


# ---------------------------------------------------------- integration (real) --

@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_render_eml_end_to_end_with_signature(tmp_path):
    src = tmp_path / "status-update.md"
    src.write_text(
        '---\ntitle: "Q3 status update"\nrecipient: "Alex Rivera <alex.rivera@example.com>"\n---\n\n'
        "# Status\n\nHello Alex, the [dashboard](https://example.com/dashboard) is live.\n\n"
        "- item one\n- item two\n",
        encoding="utf-8",
    )
    sig = tmp_path / "sig.yaml"
    sig.write_text(FICTIONAL_SIGNATURE, encoding="utf-8")

    out = eb.render_eml(src, tmp_path / "status-update.eml", signature=sig)
    assert out.is_file()

    msg = email.message_from_bytes(out.read_bytes(), policy=email.policy.default)
    assert msg["To"] == "Alex Rivera <alex.rivera@example.com>"
    assert msg["Subject"] == "Q3 status update"
    assert msg["From"] == "jane.doe@example.com"
    assert msg["Date"] is not None
    assert msg["Message-ID"] is not None
    assert "renderfact.invalid" in msg["Message-ID"]
    assert msg.get_content_type() == "text/plain"
    assert not msg.is_multipart()

    body = msg.get_content()
    assert "Hello Alex" in body
    assert "dashboard" in body
    assert "https://example.com/dashboard" in body  # --reference-links: URL preserved
    assert "item one" in body and "item two" in body
    assert "\n-- \n" in body  # sig-dash delimiter present
    assert "Jane Doe" in body
    assert "Product Manager, Engineering" in body
    assert "+1-555-0100" in body


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_render_eml_with_image_signature_is_multipart_with_inline_png(tmp_path):
    src = tmp_path / "note.md"
    src.write_text('---\ntitle: "With logo"\nrecipient: "alex.rivera@example.com"\n---\n\nBody text.\n',
                   encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(_PNG)
    sig = tmp_path / "sig.yaml"
    sig.write_text(FICTIONAL_SIGNATURE + 'images:\n  - "logo.png"\n', encoding="utf-8")

    out = eb.render_eml(src, tmp_path / "note.eml", signature=sig)
    msg = email.message_from_bytes(out.read_bytes(), policy=email.policy.default)

    assert msg.is_multipart()
    assert msg.get_content_type() == "multipart/mixed"

    parts = list(msg.iter_parts())
    text_parts = [p for p in parts if p.get_content_type() == "text/plain"]
    image_parts = [p for p in parts if p.get_content_type() == "image/png"]
    assert len(text_parts) == 1
    assert len(image_parts) == 1

    body = text_parts[0].get_content()
    assert "Body text" in body and "Jane Doe" in body

    img_part = image_parts[0]
    assert img_part.get_content_disposition() == "inline"
    assert img_part.get_filename() == "logo.png"
    assert img_part.get("Content-ID")
    assert img_part.get_content() == _PNG


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_render_eml_no_images_stays_single_text_plain_part(tmp_path):
    src = tmp_path / "note.md"
    src.write_text('---\ntitle: "No logo"\nrecipient: "alex.rivera@example.com"\n---\n\nBody text.\n',
                   encoding="utf-8")
    sig = tmp_path / "sig.yaml"
    sig.write_text(FICTIONAL_SIGNATURE, encoding="utf-8")

    out = eb.render_eml(src, tmp_path / "note.eml", signature=sig)
    msg = email.message_from_bytes(out.read_bytes(), policy=email.policy.default)
    assert not msg.is_multipart()
    assert msg.get_content_type() == "text/plain"


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_render_eml_no_signature_no_delimiter(tmp_path):
    src = tmp_path / "note.md"
    src.write_text('---\ntitle: "A note"\nrecipient: "alex.rivera@example.com"\n---\n\nBody text.\n',
                   encoding="utf-8")
    out = eb.render_eml(src, tmp_path / "note.eml")
    msg = email.message_from_bytes(out.read_bytes(), policy=email.policy.default)
    body = msg.get_content()
    assert "-- " not in body


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_render_eml_missing_recipient_warns_and_omits_to_header(tmp_path, capsys):
    src = tmp_path / "note.md"
    src.write_text("# Just a note\n\nNo frontmatter recipient here.\n", encoding="utf-8")
    out = eb.render_eml(src, tmp_path / "note.eml")
    msg = email.message_from_bytes(out.read_bytes(), policy=email.policy.default)
    assert msg["To"] is None
    captured = capsys.readouterr()
    assert "WARNING" in captured.err and "recipient" in captured.err


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_render_eml_subject_falls_back_to_source_stem(tmp_path):
    src = tmp_path / "no-title-here.md"
    src.write_text("Just a body.\n", encoding="utf-8")
    out = eb.render_eml(src, tmp_path / "out.eml")
    msg = email.message_from_bytes(out.read_bytes(), policy=email.policy.default)
    assert msg["Subject"] == "no-title-here"


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_render_eml_cli_overrides_win_over_frontmatter(tmp_path):
    src = tmp_path / "note.md"
    src.write_text('---\ntitle: "Frontmatter subject"\nrecipient: "frontmatter@example.com"\n---\n\nBody.\n',
                   encoding="utf-8")
    out = eb.render_eml(src, tmp_path / "note.eml", recipient="cli-override@example.com",
                        subject="CLI subject", sender="cli-sender@example.com")
    msg = email.message_from_bytes(out.read_bytes(), policy=email.policy.default)
    assert msg["To"] == "cli-override@example.com"
    assert msg["Subject"] == "CLI subject"
    assert msg["From"] == "cli-sender@example.com"


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_render_eml_wikilink_display_text_resolves(tmp_path):
    src = tmp_path / "wiki.md"
    src.write_text("See [[some-target|Display Text]] for detail.\n", encoding="utf-8")
    out = eb.render_eml(src, tmp_path / "wiki.eml")
    msg = email.message_from_bytes(out.read_bytes(), policy=email.policy.default)
    body = msg.get_content()
    assert "Display Text" in body
    assert "[[" not in body and "]]" not in body


def test_render_eml_missing_source_raises(tmp_path):
    with pytest.raises(eb.EmlBackendError, match="source not found"):
        eb.render_eml(tmp_path / "nope.md", pandoc="pandoc")


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_render_eml_default_output_dir(tmp_path, monkeypatch):
    src = tmp_path / "mynote.md"
    src.write_text("# Hi\n", encoding="utf-8")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "renders"))
    out = eb.render_eml(src)
    assert out == tmp_path / "renders" / "mynote.eml"
    assert out.is_file()


# --------------------------------------------------------------- dispatch --

def test_render_eml_mode_help_routes():
    r = subprocess.run([sys.executable, str(RENDER_PY), "eml", "--help"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    assert "render eml" in r.stdout and "--signature" in r.stdout


def test_render_eml_mode_requires_source():
    r = subprocess.run([sys.executable, str(RENDER_PY), "eml"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 2  # argparse: missing required positional


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_render_eml_mode_end_to_end_cli(tmp_path):
    src = tmp_path / "note.md"
    src.write_text('---\ntitle: "CLI test subject"\nrecipient: "alex.rivera@example.com"\n---\n\nBody.\n',
                   encoding="utf-8")
    out = tmp_path / "note.eml"
    r = subprocess.run([sys.executable, str(RENDER_PY), "eml", str(src), "-o", str(out)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert out.is_file()
    msg = email.message_from_bytes(out.read_bytes(), policy=email.policy.default)
    assert msg["Subject"] == "CLI test subject"
    assert msg["To"] == "alex.rivera@example.com"
