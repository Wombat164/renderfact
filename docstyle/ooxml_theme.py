"""
ooxml_theme.py: shared DrawingML theme parser for DOCX/XLSX/PPTX (C7 build tag).

python-docx exposes only the THEME ROLE a color references (Font.color.theme_color),
never the resolved RGB; the maintainer's own answer is "have a look directly at
the XML" (python-docx issue 1267). openpyxl has no theme API at all (zero hits in
its doc genindex). python-pptx's maintainer confirmed the same gap for that library
("you'd be starting pretty much from scratch", issue 308, open). This module fills
that gap directly against the raw OOXML instead of any of the three libraries: one
DrawingML theme structure (ECMA-376 / ISO-IEC 29500, themeElements > clrScheme +
fontScheme) is shared by all three application formats. Verified: docs/prior-art-
template-analysis.md.

The theme part is addressed via package RELATIONSHIPS (a Relationship whose Type
ends in "/theme"), not a fixed path: addressing is relationship-based by spec,
the conventional word/theme/theme1.xml (ppt/, xl/) paths are filename convention
only and used here strictly as a fallback.

The srgbClr-vs-sysClr resolution approach (use sysClr's `lastClr` attribute as the
resolved value when a theme color is tied to a system color rather than a fixed
RGB) imitates the pattern used by BrandDocs (github.com/ferdinandobons/brand-docs,
MIT licence), credited here per the C7 prior-art pass (docs/prior-art-template-
analysis.md, section 2). This implementation is written independently against the
OOXML/DrawingML spec; nothing is copied from BrandDocs' source.
"""

from __future__ import annotations

import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

# Fallback conventional theme paths (filename convention, not spec-addressing),
# keyed by the package's own file extension.
_CONVENTIONAL_PATHS = {
    ".docx": "word/theme/theme1.xml",
    ".pptx": "ppt/theme/theme1.xml",
    ".xlsx": "xl/theme/theme1.xml",
}

# The 12 clrScheme roles, in ECMA-376 document order.
_COLOR_ROLES = (
    "dk1", "lt1", "dk2", "lt2",
    "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
    "hlink", "folHlink",
)


class ThemeError(Exception):
    """Raised when a package has no resolvable DrawingML theme part, or the part
    found is not valid/parseable theme XML."""


@dataclass(frozen=True)
class Theme:
    """A resolved DrawingML theme: colours as 6-hex-no-'#' strings keyed by their
    clrScheme role (dk1/lt1/dk2/lt2/accent1-6/hlink/folHlink), fonts as the major/
    minor latin typeface names."""

    colors: dict[str, str] = field(default_factory=dict)
    fonts: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, dict[str, str]]:
        return {"colors": dict(self.colors), "fonts": dict(self.fonts)}


def _qn(tag: str) -> str:
    """Clark-notation qualified name in the DrawingML namespace, e.g. 'clrScheme' ->
    '{http://.../drawingml/2006/main}clrScheme'."""
    return f"{{{DRAWING_NS}}}{tag}"


def _owning_dir(rels_path: str) -> str:
    """The directory of the PART a .rels file describes, e.g.
    'word/_rels/document.xml.rels' -> 'word'; the package root '_rels/.rels' -> ''."""
    parent = posixpath.dirname(rels_path)  # 'word/_rels' or '_rels'
    grandparent = posixpath.dirname(parent)  # 'word' or ''
    return grandparent


def _resolve_target(owning_dir: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(owning_dir, target)) if owning_dir else posixpath.normpath(target)


def _find_theme_part_via_relationships(zf: zipfile.ZipFile) -> str | None:
    """Search every .rels part in the package for a Relationship whose Type ends
    in '/theme'; resolve its Target relative to the .rels file's owning part
    directory. Returns the candidate part path (which may or may not actually
    exist in the package; callers decide how to react to a dangling reference),
    or None if no such relationship exists anywhere in the package."""
    for name in zf.namelist():
        if not name.endswith(".rels"):
            continue
        try:
            data = zf.read(name)
        except KeyError:
            continue
        try:
            root = etree.fromstring(data)
        except etree.XMLSyntaxError:
            continue
        for rel in root.findall(f"{{{RELS_NS}}}Relationship"):
            rel_type = (rel.get("Type") or "").rstrip("/")
            if not rel_type.endswith("/theme"):
                continue
            if rel.get("TargetMode") == "External":
                continue
            target = rel.get("Target") or ""
            if not target:
                continue
            return _resolve_target(_owning_dir(name), target)
    return None


def _find_theme_part(path: Path, zf: zipfile.ZipFile) -> str | None:
    """Resolve the theme part path: relationship-based first (spec-correct),
    falling back to the conventional path for the package's own extension, then
    (as a last resort) every other format's conventional path (a mislabeled
    extension shouldn't hide a theme that is genuinely present)."""
    via_rel = _find_theme_part_via_relationships(zf)
    if via_rel is not None:
        return via_rel
    names = set(zf.namelist())
    suffix = path.suffix.lower()
    ordered = [_CONVENTIONAL_PATHS[suffix]] if suffix in _CONVENTIONAL_PATHS else []
    ordered += [p for p in _CONVENTIONAL_PATHS.values() if p not in ordered]
    for candidate in ordered:
        if candidate in names:
            return candidate
    return None


def _resolve_color(role_el: etree._Element) -> str | None:
    srgb = role_el.find(_qn("srgbClr"))
    if srgb is not None:
        val = srgb.get("val")
        if val:
            return val.upper()
    sys_clr = role_el.find(_qn("sysClr"))
    if sys_clr is not None:
        last = sys_clr.get("lastClr")
        if last:
            return last.upper()
    return None


def _parse_color_scheme(theme_root: etree._Element) -> dict[str, str]:
    colors: dict[str, str] = {}
    clr_scheme = theme_root.find(f".//{_qn('clrScheme')}")
    if clr_scheme is None:
        return colors
    for role in _COLOR_ROLES:
        role_el = clr_scheme.find(_qn(role))
        if role_el is None:
            continue
        value = _resolve_color(role_el)
        if value:
            colors[role] = value
    return colors


def _parse_font_scheme(theme_root: etree._Element) -> dict[str, str]:
    fonts: dict[str, str] = {}
    font_scheme = theme_root.find(f".//{_qn('fontScheme')}")
    if font_scheme is None:
        return fonts
    major = font_scheme.find(f"{_qn('majorFont')}/{_qn('latin')}")
    minor = font_scheme.find(f"{_qn('minorFont')}/{_qn('latin')}")
    if major is not None and major.get("typeface"):
        fonts["major"] = major.get("typeface")
    if minor is not None and minor.get("typeface"):
        fonts["minor"] = minor.get("typeface")
    return fonts


def read_theme(path: str | Path) -> Theme:
    """Read and resolve the DrawingML theme (colours + fonts) from a .docx/.xlsx/
    .pptx package. Raises ThemeError (never a bare exception) when the package has
    no resolvable theme part, the referenced part is missing, or the part found
    is not valid theme XML."""
    path = Path(path)
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ThemeError(f"'{path}' is not a readable OOXML package: {exc}") from exc

    with zf:
        theme_part = _find_theme_part(path, zf)
        if theme_part is None:
            raise ThemeError(f"no theme part found in '{path}' (no /theme relationship, "
                            "and no conventional theme1.xml path present)")
        try:
            data = zf.read(theme_part)
        except KeyError as exc:
            raise ThemeError(
                f"theme part '{theme_part}' is referenced by '{path}' but missing from the package"
            ) from exc

    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError as exc:
        raise ThemeError(f"theme part '{theme_part}' in '{path}' is not valid XML: {exc}") from exc

    colors = _parse_color_scheme(root)
    fonts = _parse_font_scheme(root)
    if not colors and not fonts:
        raise ThemeError(f"theme part '{theme_part}' in '{path}' contains no clrScheme or fontScheme")
    return Theme(colors=colors, fonts=fonts)
