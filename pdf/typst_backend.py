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
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
THEME_DIR = Path(__file__).resolve().parent / "theme"
DEFAULT_THEME = THEME_DIR / "default.typ"
BLOCKS_TYP = THEME_DIR / "blocks.typ"           # #33 semantic-block render functions
_IMAGE_RE = re.compile(r'image\("([^"]+)"')     # typst image() calls in pandoc output
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

def _project_markdown(source: Path, profile_name: str, profiles_path: "str | Path | None") -> str:
    """Run the Track F projection engine and return the projected markdown for one
    audience/clearance/disclosure profile, so a governed source can render one
    branded PDF per profile. Raises TypstBackendError on a config/profile error."""
    if not profiles_path:
        raise TypstBackendError("--project requires --profiles <ladders+profiles.yaml>")
    profiles_path = Path(profiles_path)
    if not profiles_path.is_file():
        raise TypstBackendError(f"profiles config not found: {profiles_path}")
    sys.path.insert(0, str(REPO_ROOT / "projection"))
    import projector  # projection/projector.py

    try:
        ladders, profiles = projector.load_config(profiles_path)
        if profile_name not in profiles:
            raise TypstBackendError(
                f"unknown profile {profile_name!r} (available: {', '.join(sorted(profiles))})")
        bank = projector.load_terms(None)
        text, _dropped = projector.project(source, profiles[profile_name], ladders, bank)
    except projector.ProjectionError as e:
        raise TypstBackendError(str(e)) from None
    return text


def stage_images(body: str, source_dir: Path, work: Path, image_root: "Path | None" = None) -> str:
    """typst resolves image() paths relative to the compiled .typ (the build dir),
    not the markdown source -- so copy every referenced image the source dir can
    resolve into the build dir under a flat _img/ name, and rewrite the reference
    to point there. Remote URLs are left untouched. When `image_root` is set (the
    API's server root), an image resolving outside it is left as-is rather than
    copied, so an untrusted document cannot pull a server file into the PDF."""
    counter = 0
    mapping: dict[str, str] = {}

    def repl(match):
        nonlocal counter
        ref = match.group(1)
        if ref in mapping:
            return f'image("{mapping[ref]}"'
        if ref.startswith(("http://", "https://")):
            return match.group(0)
        src = Path(ref)
        if not src.is_absolute():
            src = source_dir / ref
        src = src.resolve()
        if image_root is not None:
            try:
                src.relative_to(Path(image_root).resolve())
            except ValueError:
                return match.group(0)  # outside the jail: do not stage
        if not src.is_file():
            return match.group(0)  # missing: let typst report it
        counter += 1
        staged = f"_img/{counter}{src.suffix}"
        (work / "_img").mkdir(exist_ok=True)
        shutil.copyfile(src, work / staged)
        mapping[ref] = staged
        return f'image("{staged}"'

    return _IMAGE_RE.sub(repl, body)


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
    lang: str = "en",
) -> str:
    """Compose main.typ: import the theme, apply it as a show rule with the
    document metadata, then the pandoc body."""
    args = ", ".join([
        f"title: {_typ_str(title)}",
        f"subtitle: {_typ_str(subtitle)}",
        f"org: {_typ_str(org)}",
        f"date: {_typ_str(date)}",
        f"paper: {_typ_str(paper)}",
        f"lang: {_typ_str(lang)}",
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
    locale: "str | None" = None,
    project: "str | None" = None,
    profiles: "str | Path | None" = None,
    fmt: str = "pdf",
    ppi: int = 144,
    page: int = 1,
    page_count: "list | None" = None,
    data_root: "Path | None" = None,
    typst: "str | None" = None,
    pandoc: "str | None" = None,
) -> Path:
    """Render a markdown source to a themed A4 PDF (fmt='pdf') or a single-page PNG
    preview (fmt='png', 1-indexed `page`, clamped) via typst. Returns the output
    path; for png, a caller-supplied `page_count` list receives the total page
    count. `data_root`, when set, jails every statement `data=` path under it (the
    API passes its server root for untrusted sources). Raises TypstBackendError on
    any missing tool or failed step."""
    if fmt not in ("pdf", "png"):
        raise TypstBackendError(f"unsupported output format: {fmt!r} (use pdf or png)")
    source = Path(source)
    if not source.is_file():
        raise TypstBackendError(f"source not found: {source}")

    # #35: a project locale drives number separators (statement amounts), the
    # hyphenation language, and long-date formatting (raw ISO -> localized).
    # Resolved first so a bad locale fails before any tool/render work.
    import locale_fmt
    try:
        locale_cfg = locale_fmt.resolve(locale)
    except locale_fmt.LocaleError as e:
        raise TypstBackendError(str(e)) from None
    number_defaults = locale_fmt.number_format(locale_cfg)
    text_lang = locale_fmt.lang(locale_cfg, "en")
    date = locale_fmt.format_date(date, locale_cfg)

    typst = typst or find_typst()
    pandoc = pandoc or find_pandoc()
    title = title if title is not None else source.stem

    theme_src = Path(theme) if theme else DEFAULT_THEME
    if not theme_src.is_file():
        raise TypstBackendError(f"theme not found: {theme_src}")

    if output is None:
        out_dir = Path(os.environ.get("OUTPUT_DIR", "renders"))
        out_dir.mkdir(parents=True, exist_ok=True)
        output = out_dir / f"{source.stem}.{fmt}"
    output = Path(output)

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        generate_tokens_typ(work, Path(brand) if brand else None, variant)
        (work / "theme.typ").write_text(theme_src.read_text(encoding="utf-8"), encoding="utf-8")
        (work / "blocks.typ").write_text(BLOCKS_TYP.read_text(encoding="utf-8"), encoding="utf-8")

        md_text = source.read_text(encoding="utf-8")
        # Optional projection: emit the audience/clearance-projected markdown first
        # (Track F), so a governed source renders one branded PDF per profile.
        if project:
            md_text = _project_markdown(source, project, profiles)

        # #34: expand data-bound statement blocks (compute + reconcile) before
        # pandoc; a reconciliation failure fails the render. Untouched otherwise.
        # Paths in the (possibly-projected) text stay relative to the ORIGINAL
        # source dir, so base_dir + resource_path + image staging all use it.
        import statement_data
        try:
            md_text = statement_data.expand_markdown(md_text, source.parent, number_defaults,
                                                     data_root=data_root)
        except statement_data.StatementError as e:
            raise TypstBackendError(str(e)) from None
        md_for_pandoc = work / f"{source.stem}.md"
        md_for_pandoc.write_text(md_text, encoding="utf-8")
        body = md_to_typst(md_for_pandoc, pandoc, resource_path=source.parent)
        # copy referenced images into the build dir so typst can resolve them
        # (jailed under data_root for untrusted API sources).
        body = stage_images(body, source.parent, work, image_root=data_root)
        (work / "main.typ").write_text(
            compose_main(body, title=title, subtitle=subtitle, org=org, date=date,
                         paper=paper, lang=text_lang),
            encoding="utf-8",
        )
        # root = work; referenced images were staged into work/_img above. For a
        # PNG preview, typst writes one file per page to a zero-padded template; we
        # return the first page (the preview). For PDF, a single file.
        if fmt == "png":
            page_tmpl = work / "_page-{0p}.png"
            cmd = [typst, "compile", "--format", "png", "--ppi", str(ppi),
                   "--root", str(work), str(work / "main.typ"), str(page_tmpl)]
        else:
            cmd = [typst, "compile", "--root", str(work), str(work / "main.typ"), str(output)]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            raise TypstBackendError(f"typst compile failed:\n{result.stderr.strip()}")
        if fmt == "png":
            pages = sorted(work.glob("_page-*.png"))
            if not pages:
                raise TypstBackendError("typst produced no PNG pages")
            if page_count is not None:
                page_count.append(len(pages))
            idx = min(max(page - 1, 0), len(pages) - 1)  # 1-indexed, clamped
            shutil.copyfile(pages[idx], output)

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
    ap.add_argument("--locale", default=None,
                    help="project locale (e.g. nl-BE) driving number/date formatting + hyphenation")
    ap.add_argument("--project", default=None, metavar="PROFILE",
                    help="project the source through this audience profile before rendering (Track F)")
    ap.add_argument("--profiles", default=None, metavar="CONFIG",
                    help="ladders+profiles yaml for --project")
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
            paper=args.paper, variant=args.variant, locale=args.locale,
            project=args.project, profiles=args.profiles,
        )
    except TypstBackendError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
