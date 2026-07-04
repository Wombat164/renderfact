"""typst_backend.py -- render markdown to a layout-native PDF via typst (issue #31).

A first-class PDF backend, a PEER of the DOCX path rather than a LibreOffice
afterthought. Markdown is translated to typst markup by pandoc's typst writer,
wrapped in a brand-token-driven theme, and compiled to PDF by the typst binary.
No OOXML and no LibreOffice are involved, so the layout is typst's own --
deterministic and print-precise, which is exactly where the DOCX->LibreOffice
path drifts (page chrome, callout boxes, signature grids, ledger rules).

Generic core (D3): the default theme ships in pdf/theme/default.typ and needs no
consumer configuration; a consumer supplies its own theme via --theme / THEME_TYP
and its palette via --brand (consumed through the existing tokens.typ generator).

Toolchain: pandoc (>=3, has a typst writer) as the markdown reader, typst as the
layout engine. Both are already known to `render doctor`. When either is missing
the backend fails with a clear, actionable message rather than a traceback.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
THEME_DIR = Path(__file__).resolve().parent / "theme"
DEFAULT_THEME = THEME_DIR / "default.typ"
BLOCKS_TYP = THEME_DIR / "blocks.typ"           # #33 semantic-block render functions
SEMANTIC_FILTER = Path(__file__).resolve().parent / "filters" / "semantic-blocks.lua"


class TypstBackendError(RuntimeError):
    """A backend precondition failed (missing tool) or a subprocess step failed."""


# --------------------------------------------------------------- tool lookup --

def _windows_candidates(binary: str) -> list[str]:
    la = os.environ.get("LOCALAPPDATA", "")
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if binary == "pandoc":
        return [f"{la}\\Pandoc\\pandoc.exe", r"C:\Program Files\Pandoc\pandoc.exe"]
    if binary == "typst":
        return [f"{la}\\Microsoft\\WinGet\\Links\\typst.exe", f"{la}\\Programs\\typst\\typst.exe"]
    return []


def _resolve(binary: str, env_var: str) -> "str | None":
    """env override > PATH > known Windows install dirs."""
    explicit = os.environ.get(env_var)
    if explicit:
        return explicit
    found = shutil.which(binary)
    if found:
        return found
    if sys.platform == "win32":
        for c in _windows_candidates(binary):
            if Path(c).exists():
                return c
    return None


def find_pandoc() -> str:
    p = _resolve("pandoc", "PANDOC")
    if not p:
        raise TypstBackendError(
            "pandoc not found (needed to translate markdown -> typst). Install pandoc >=3 "
            "or set PANDOC=/path/to/pandoc.")
    return p


def find_typst() -> str:
    t = _resolve("typst", "TYPST")
    if not t:
        raise TypstBackendError(
            "typst not found (the PDF layout engine). Install typst "
            "(https://github.com/typst/typst) or set TYPST=/path/to/typst.")
    return t


# ------------------------------------------------------------- build helpers --

def md_to_typst(md_path: Path, pandoc: str, resource_path: "Path | None" = None) -> str:
    """Translate a markdown source to a typst FRAGMENT (no --standalone: we supply
    the template ourselves via the theme). The semantic-blocks Lua filter maps
    renderfact's fenced-div blocks (#33) to typst function calls; it is a no-op
    for documents that use none. resource_path (the original source dir) keeps
    relative image lookups working when md_path is an expanded temp file."""
    cmd = [pandoc, str(md_path), "-t", "typst"]
    if SEMANTIC_FILTER.is_file():
        cmd += ["--lua-filter", str(SEMANTIC_FILTER)]
    if resource_path is not None:
        cmd += ["--resource-path", str(resource_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise TypstBackendError(f"pandoc markdown->typst failed:\n{result.stderr.strip()}")
    return result.stdout


def generate_tokens_typ(work_dir: Path, brand: "Path | None" = None, variant: str = "base") -> Path:
    """Emit tokens.typ (palette+fonts) and chrome.typ (the #32 engine-agnostic
    theme descriptor for the given variant) into work_dir, both from the same
    brand.yaml the other engines use. Returns the tokens.typ path."""
    sys.path.insert(0, str(REPO_ROOT / "tokens" / "gen"))
    import typst_tokens  # tokens/gen/typst_tokens.py
    import theme_tokens  # tokens/gen/theme_tokens.py (#32)
    from _common import load_tokens  # tokens/gen/_common.py

    tokens = load_tokens(brand)
    out = work_dir / "tokens.typ"
    out.write_text(typst_tokens.render_typst(tokens), encoding="utf-8")
    try:
        chrome = theme_tokens.render_theme(tokens, variant)
    except KeyError as e:
        raise TypstBackendError(str(e).strip('"')) from None
    (work_dir / "chrome.typ").write_text(chrome, encoding="utf-8")
    return out


def _typ_str(value: "str | None") -> str:
    """A typst string literal, or `none`."""
    if value is None:
        return "none"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def compose_main(
    body: str,
    *,
    title: "str | None",
    subtitle: "str | None",
    org: "str | None",
    date: "str | None",
    paper: str,
) -> str:
    """Compose main.typ: import the theme, apply it as a show rule with the
    document metadata, then the pandoc body."""
    args = ", ".join([
        f"title: {_typ_str(title)}",
        f"subtitle: {_typ_str(subtitle)}",
        f"org: {_typ_str(org)}",
        f"date: {_typ_str(date)}",
        f"paper: {_typ_str(paper)}",
    ])
    return (
        '#import "theme.typ": conf\n'
        '#import "blocks.typ": *\n'
        f"#show: conf.with({args})\n\n"
        f"{body}\n"
    )


# ------------------------------------------------------------------- render --

def render_pdf(
    source: "str | Path",
    output: "str | Path | None" = None,
    *,
    theme: "str | Path | None" = None,
    brand: "str | Path | None" = None,
    title: "str | None" = None,
    subtitle: "str | None" = None,
    org: "str | None" = None,
    date: "str | None" = None,
    paper: str = "a4",
    variant: str = "base",
    typst: "str | None" = None,
    pandoc: "str | None" = None,
) -> Path:
    """Render a markdown source to a themed A4 PDF via typst. Returns the output
    path. Raises TypstBackendError on any missing tool or failed step."""
    source = Path(source)
    if not source.is_file():
        raise TypstBackendError(f"source not found: {source}")

    typst = typst or find_typst()
    pandoc = pandoc or find_pandoc()
    title = title if title is not None else source.stem

    theme_src = Path(theme) if theme else DEFAULT_THEME
    if not theme_src.is_file():
        raise TypstBackendError(f"theme not found: {theme_src}")

    if output is None:
        out_dir = Path(os.environ.get("OUTPUT_DIR", "renders"))
        out_dir.mkdir(parents=True, exist_ok=True)
        output = out_dir / f"{source.stem}.pdf"
    output = Path(output)

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        generate_tokens_typ(work, Path(brand) if brand else None, variant)
        (work / "theme.typ").write_text(theme_src.read_text(encoding="utf-8"), encoding="utf-8")
        (work / "blocks.typ").write_text(BLOCKS_TYP.read_text(encoding="utf-8"), encoding="utf-8")

        # #34: expand data-bound statement blocks (compute + reconcile) before
        # pandoc; a reconciliation failure fails the render. Untouched otherwise.
        import statement_data
        raw = source.read_text(encoding="utf-8")
        try:
            expanded = statement_data.expand_markdown(raw, source.parent)
        except statement_data.StatementError as e:
            raise TypstBackendError(str(e)) from None
        md_for_pandoc = source
        if expanded != raw:
            md_for_pandoc = work / source.name
            md_for_pandoc.write_text(expanded, encoding="utf-8")
        body = md_to_typst(md_for_pandoc, pandoc, resource_path=source.parent)
        (work / "main.typ").write_text(
            compose_main(body, title=title, subtitle=subtitle, org=org, date=date, paper=paper),
            encoding="utf-8",
        )
        # --root at the source's own dir so body-relative image() paths resolve;
        # main.typ lives in work, so allow both roots via the parent that contains
        # both is impossible -- keep it simple: root = work, and pass the source
        # dir as a font/asset path is a follow-on. MVP: text + tables + rules.
        result = subprocess.run(
            [typst, "compile", "--root", str(work), str(work / "main.typ"), str(output)],
            capture_output=True, text=True, encoding="utf-8",
        )
        if result.returncode != 0:
            raise TypstBackendError(f"typst compile failed:\n{result.stderr.strip()}")

    return output


def main(argv: "list[str] | None" = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="render pdf",
        description="Render markdown to a layout-native PDF via typst (a peer of the DOCX path).",
    )
    ap.add_argument("source", help="markdown source file")
    ap.add_argument("--engine", choices=("typst",), default="typst",
                    help="layout engine (only typst today; the flag reserves the peer slot)")
    ap.add_argument("-o", "--output", default=None, help="output PDF path (default: renders/<stem>.pdf)")
    ap.add_argument("--theme", default=None, help="a typst layout file (default: the built-in theme)")
    ap.add_argument("--brand", default=None, help="a consumer brand.yaml (default: the built-in tokens)")
    ap.add_argument("--variant", default="base",
                    help="theme variant from brand.yaml [theme.variants] (default: base)")
    ap.add_argument("--title", default=None, help="document title (default: the source stem)")
    ap.add_argument("--subtitle", default=None)
    ap.add_argument("--org", default=None, help="organisation shown in the page header")
    ap.add_argument("--date", default=None, help="date shown in the page footer")
    ap.add_argument("--paper", default="a4")
    args = ap.parse_args(argv)

    try:
        out = render_pdf(
            args.source, args.output, theme=args.theme, brand=args.brand,
            title=args.title, subtitle=args.subtitle, org=args.org, date=args.date,
            paper=args.paper, variant=args.variant,
        )
    except TypstBackendError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
