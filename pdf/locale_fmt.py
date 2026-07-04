"""locale_fmt.py -- project-level locale for number, date, and hyphenation (issue #35).

A financial deliverable in Belgian Dutch had every amount hand-formatted
(EUR 1.510,53 -- dot thousands, comma decimal), every date hand-written
(15 februari 2025), and hyphenation set to nl. All of it a manual typo surface.
A `locale` (e.g. nl-BE) drives:

  - number/currency separators + currency placement,
  - localized long dates (raw ISO in -> "15 februari 2025" out),
  - the hyphenation language handed to typst.

Stdlib-only and deterministic: month names are tabled here rather than relying on
the platform `locale` database (unreliable + non-reproducible across hosts).
"""

from __future__ import annotations

import datetime
import re

# Month names per language, index 1..12 (index 0 unused). FR carries its accents.
_MONTHS = {
    "nl": [None, "januari", "februari", "maart", "april", "mei", "juni",
           "juli", "augustus", "september", "oktober", "november", "december"],
    "fr": [None, "janvier", "février", "mars", "avril", "mai", "juin",
           "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
    "en": [None, "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
}

_NBSP = " "

# locale -> formatting config. thousands/decimal are the group + fraction
# separators; currency_before places the currency symbol before (True) or after
# (False) the amount; lang is the hyphenation language.
LOCALES = {
    "nl-BE": {"lang": "nl", "thousands": ".", "decimal": ",", "currency_before": True},
    "fr-BE": {"lang": "fr", "thousands": _NBSP, "decimal": ",", "currency_before": False},
    "en":    {"lang": "en", "thousands": ",", "decimal": ".", "currency_before": True},
    "en-GB": {"lang": "en", "thousands": ",", "decimal": ".", "currency_before": True},
    "en-US": {"lang": "en", "thousands": ",", "decimal": ".", "currency_before": True},
}

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


class LocaleError(RuntimeError):
    """An unknown locale was requested."""


def resolve(locale: "str | None") -> "dict | None":
    """The formatting config for a locale, or None when no locale is set (callers
    then keep their explicit/default formatting). Unknown locale is a hard error --
    silently mis-formatting a financial figure is worse than failing."""
    if locale in (None, ""):
        return None
    cfg = LOCALES.get(locale)
    if cfg is None:
        raise LocaleError(f"unknown locale: {locale!r} (known: {', '.join(sorted(LOCALES))})")
    return cfg


def number_format(locale_cfg: "dict | None") -> dict:
    """The {thousands, decimal, currency_before} a statement's amount formatter
    needs, from a locale config (empty dict when None -> caller's own defaults)."""
    if not locale_cfg:
        return {}
    return {
        "thousands": locale_cfg["thousands"],
        "decimal": locale_cfg["decimal"],
        "currency_before": locale_cfg["currency_before"],
    }


def lang(locale_cfg: "dict | None", default: str = "en") -> str:
    return locale_cfg["lang"] if locale_cfg else default


def format_date(value: "str | None", locale_cfg: "dict | None") -> "str | None":
    """Format an ISO date (YYYY-MM-DD) as a localized long date; pass anything
    else (an already-written date, or no locale) through unchanged."""
    if value is None or not locale_cfg:
        return value
    m = _ISO_DATE.match(value.strip())
    if not m:
        return value
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        datetime.date(year, month, day)  # validate (raises on 2025-13-40)
    except ValueError:
        return value
    months = _MONTHS.get(locale_cfg["lang"], _MONTHS["en"])
    return f"{day} {months[month]} {year}"
