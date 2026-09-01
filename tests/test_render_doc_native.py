"""Unit tests for container/render_doc.py, the native (shell-free) DOCX driver (issue #157).

The end-to-end behaviour of this pipeline is already covered by the integration suites
(test_render_doc_provenance, test_render_doc_toc_opt_out, test_render_doc_gate_hooks,
test_wikilink_resolution, test_raw_attribute_escape_hatch). Those became the real regression net
for the port: on Windows they used to SKIP for want of bash, and they now run.

So this file deliberately does NOT re-test the pipeline. It tests the parts of the transcription
that a port gets wrong quietly: argument-parsing edge rules, the awk-to-Python text transform,
version extraction, and the existence-gating of skin defaults. Each one is a behaviour the shell
had that a reasonable reimplementation would drop.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER = REPO_ROOT / "container" / "render_doc.py"


def _load():
    spec = importlib.util.spec_from_file_location("rf_render_doc", DRIVER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rd = _load()


# ---------- argument parsing ----------

def test_bare_word_becomes_source_then_overwrites_suffix():
    """The shell's `*)` fallback, which is the rule most likely to be lost in a port.

    An unrecognised bare word is the SOURCE if none has been seen, and otherwise REPLACES the
    suffix. That is why `render-doc.sh doc.md FINAL` and `render-doc.sh doc.md ANYTHING` both work.
    """
    a = rd.parse_args(["doc.md"])
    assert a["source"] == "doc.md" and a["suffix"] == "DRAFT"
    a = rd.parse_args(["doc.md", "ANYTHING"])
    assert a["source"] == "doc.md" and a["suffix"] == "ANYTHING"


def test_lifecycle_words_set_the_suffix_in_any_position():
    assert rd.parse_args(["REVIEW", "doc.md"])["suffix"] == "REVIEW"
    assert rd.parse_args(["doc.md", "FINAL"])["suffix"] == "FINAL"
    # ...and the lifecycle word is NOT mistaken for the source
    assert rd.parse_args(["REVIEW", "doc.md"])["source"] == "doc.md"


def test_qc_blocking_implies_qc():
    a = rd.parse_args(["doc.md", "--qc-blocking"])
    assert a["qc"] is True and a["qc_blocking"] is True


def test_value_flags_consume_their_value():
    a = rd.parse_args(["doc.md", "--name", "Report", "--profile", "compact", "--scheme", "legal"])
    assert a["name"] == "Report" and a["profile"] == "compact" and a["scheme"] == "legal"
    # the values must not be re-read as bare words and clobber the suffix
    assert a["suffix"] == "DRAFT"


def test_a_value_flag_missing_its_value_exits_2():
    try:
        rd.parse_args(["doc.md", "--name"])
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("expected SystemExit(2)")


# ---------- the awk transform ----------

def test_render_skip_blocks_are_dropped():
    src = "keep one\n<!-- render:skip -->\nhide me\n<!-- /render:skip -->\nkeep two\n"
    out = rd.strip_render_skip(src)
    assert "hide me" not in out
    assert "keep one" in out and "keep two" in out
    # the markers themselves are consumed, not passed through
    assert "render:skip" not in out


def test_render_skip_spans_multiple_lines_and_reopens():
    src = ("a\n<!-- render:skip -->\nx\ny\n<!-- /render:skip -->\nb\n"
           "<!-- render:skip -->\nz\n<!-- /render:skip -->\nc\n")
    out = rd.strip_render_skip(src)
    assert "x" not in out and "y" not in out and "z" not in out
    for keep in ("a", "b", "c"):
        assert keep in out


def test_heading_annotations_are_stripped_only_on_heading_lines():
    src = ("# Title (NEW in V2.1)\n"
           "## Sub (normative, V9.1)\n"
           "### Third (AUTHORITATIVE, V3.0)\n"
           "#### Fourth (authoritative tuples, V1.2)\n"
           "##### Fifth (RT-42 RESOLVED by council)\n"
           "Body (NEW in V2.1) must keep its annotation.\n")
    out = rd.strip_render_skip(src)
    assert "# Title\n" in out
    assert "## Sub\n" in out
    assert "### Third\n" in out
    assert "#### Fourth\n" in out
    assert "##### Fifth\n" in out
    # a body line is NOT a heading, so its parenthetical survives
    assert "Body (NEW in V2.1) must keep its annotation." in out


def test_an_unrelated_parenthetical_on_a_heading_survives():
    """The rewrite is a whitelist of editorial annotations, not 'strip trailing parentheses'."""
    src = "# Budget (2027)\n"
    assert rd.strip_render_skip(src) == "# Budget (2027)\n"


def test_frontmatter_fences_pass_through_unchanged():
    src = "---\ntitle: T\nversion: v2\n---\n\n# H\n"
    assert rd.strip_render_skip(src) == src


# ---------- version extraction ----------

def test_version_is_the_second_field_of_the_first_version_line():
    assert rd.extract_version("---\nversion: v9.1\n---\n") == "v9.1"


def test_version_defaults_to_v1_when_absent():
    assert rd.extract_version("---\ntitle: no version here\n---\n") == "v1"


def test_only_a_line_STARTING_with_version_counts():
    """awk's /^version:/ is anchored; a mention mid-document must not win."""
    assert rd.extract_version("# doc\nthe version: v5 of this\nversion: v2\n") == "v2"


def test_the_first_version_line_wins():
    assert rd.extract_version("version: v1.0\nversion: v2.0\n") == "v1.0"


# ---------- skin resolution ----------

def test_skin_default_is_existence_gated(tmp_path):
    """A SKIN_DIR that supplies some pieces must yield honest skips for the rest, not paths
    pointing at nothing that fail later with a confusing error."""
    skin = tmp_path / "skin"
    skin.mkdir()
    (skin / "reference.docx").write_bytes(b"not really a docx")
    assert rd._skin_default(str(skin), "reference.docx").endswith("reference.docx")
    assert rd._skin_default(str(skin), "template-profile.yaml") == ""
    assert rd._skin_default("", "reference.docx") == ""


def test_explicit_env_beats_the_skin_default(tmp_path, monkeypatch):
    skin = tmp_path / "skin"
    skin.mkdir()
    (skin / "reference.docx").write_bytes(b"x")
    monkeypatch.setenv("TEMPLATE_DOCX", "/explicit/path.docx")
    assert rd._env_or_skin("TEMPLATE_DOCX", str(skin), "reference.docx") == "/explicit/path.docx"


# ---------- the contract that made this port necessary ----------

def test_help_needs_no_shell_no_pandoc_and_no_skin():
    """Issue #26 kept: -h beats the source-existence check. Issue #157: and no bash is consulted."""
    r = subprocess.run([sys.executable, str(DRIVER), "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "Usage: render-doc.sh" in r.stdout
    assert "source not found" not in r.stdout + r.stderr


def test_missing_source_exits_2_and_names_it():
    r = subprocess.run([sys.executable, str(DRIVER), "no-such-file.md"],
                       capture_output=True, text=True)
    assert r.returncode == 2
    assert "source not found: no-such-file.md" in r.stderr


def test_absent_source_argument_exits_2():
    r = subprocess.run([sys.executable, str(DRIVER)], capture_output=True, text=True)
    assert r.returncode == 2
    assert "<source.md> is required" in r.stderr


def _python_code_only(path: Path) -> str:
    """The file's CODE, with comments and string literals removed.

    Needed because the honest version of this module explains bash at length in its docstring, and
    a naive substring check on the whole file therefore fails on its own documentation. That is
    not a nitpick: a test that forces you to stop explaining yourself in order to stay green is a
    test that degrades the code it guards.
    """
    import io
    import tokenize

    kept = []
    with open(path, "rb") as fh:
        for tok in tokenize.tokenize(io.BytesIO(fh.read()).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(tok.string)
    return " ".join(kept)


def test_the_driver_never_invokes_a_shell():
    """The regression this whole change exists to prevent: no bash anywhere in the DOCX path.

    Asserted against the SOURCE rather than by mocking, because the failure mode is someone
    reintroducing a shell-out during a later edit, which a behavioural test on a machine that HAS
    bash would not notice.
    """
    code = _python_code_only(DRIVER)
    assert "shell" not in code, "a shell=True crept into the native DOCX driver"
    for token in ("bash", "_find_bash"):
        assert token not in code, f"{token!r} reappeared in the native DOCX driver's code"


def test_render_py_docx_dispatch_does_not_look_for_bash():
    src = (REPO_ROOT / "render.py").read_text(encoding="utf-8")
    run_docx = src.split("def run_docx")[1].split("\ndef ")[0]
    assert "_find_bash" not in run_docx
    assert "render_doc.py" in run_docx


def test_shell_entry_point_is_a_thin_caller_not_a_second_implementation():
    """Two copies of a 433-line pipeline is how a consumer gets two answers to one question."""
    sh = (REPO_ROOT / "container" / "render-doc.sh").read_text(encoding="utf-8")
    assert "render_doc.py" in sh
    # Comment lines are excluded on purpose: this script's job is now to EXPLAIN why the
    # implementation moved, so its comments legitimately mention pandoc and bash.
    body = "\n".join(ln for ln in sh.splitlines()
                     if ln.strip() and not ln.strip().startswith("#"))
    assert len(body.splitlines()) < 15, "render-doc.sh should be a thin caller, not a pipeline"
    for token in ("pandoc", "PANDOC_ARGS", "awk", "--reference-doc", "--lua-filter"):
        assert token not in body, f"{token!r} suggests pipeline logic crept back into the shell"
