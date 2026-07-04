"""
Shared token-loading + merge logic for tokens/gen/*.py generators (chunk 0.4 / A1).

One token source (tokens/brand.yaml, neutral defaults), optionally overridden by a
consumer-supplied brand.yaml (deep-merge: consumer values win, structure from the
default carries through for anything the consumer doesn't override). Generators
never hand-type a colour/font -- they read the merged result and emit per-engine
theme files. Golden Rule: one token source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TOKENS_PATH = REPO_ROOT / "tokens" / "brand.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base; override wins on scalar/list conflicts."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_tokens(consumer_brand_path: Path | None = None) -> dict[str, Any]:
    """Load tokens/brand.yaml (neutral defaults), deep-merged with a consumer override
    if one is supplied. Raises FileNotFoundError if the default source is missing --
    there is always at least the neutral default; a missing default is a real error,
    not a "use built-in fallback" situation (Golden Rule: one token source, keep it real)."""
    if not DEFAULT_TOKENS_PATH.exists():
        raise FileNotFoundError(f"default token source not found: {DEFAULT_TOKENS_PATH}")
    with DEFAULT_TOKENS_PATH.open(encoding="utf-8") as f:
        tokens = yaml.safe_load(f) or {}

    if consumer_brand_path is not None:
        if not consumer_brand_path.exists():
            raise FileNotFoundError(f"consumer brand.yaml not found: {consumer_brand_path}")
        with consumer_brand_path.open(encoding="utf-8") as f:
            override = yaml.safe_load(f) or {}
        tokens = _deep_merge(tokens, override)

    return tokens


def resolve_output_dir(explicit: str | None, default_subdir: str) -> Path:
    """Resolve where a generator writes output: explicit --output-dir, else
    tokens/gen/out/<default_subdir>/ relative to the repo root."""
    if explicit:
        out = Path(explicit)
    else:
        out = REPO_ROOT / "tokens" / "gen" / "out" / default_subdir
    out.mkdir(parents=True, exist_ok=True)
    return out
