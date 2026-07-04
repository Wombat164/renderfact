"""statement_data.py -- data-bound, self-reconciling ledgers for the statement
block (issue #34).

The #33 `::: statement` block renders typed rows with hand-typed amounts -- and
nothing checks that a stated "Totaal" actually equals the sum of its line items.
A single transcription slip in a financial document is then silent. This module
removes that error class: a statement can SOURCE its rows from a data file
(YAML or CSV) and COMPUTE its subtotals / totals / balances; if the data also
STATES a total, the computed and stated values must reconcile or the render
FAILS.

Integration reuses the #33 render path entirely: `expand_markdown` turns a
data-bound `::: {.statement data="x.yaml"}` block into a plain `::: statement`
block whose bullet rows carry the computed, formatted amounts -- which the
existing Lua filter + blocks.typ then render. All computation and reconciliation
happens here, in Python, deterministically.
"""

from __future__ import annotations

import ast
import csv
import operator
import re
from pathlib import Path

import yaml

_BOLD_KINDS = ("subtotal", "total", "balance")
_GROUP_RESET = ("heading", "subtotal", "total", "balance")


class StatementError(RuntimeError):
    """A data file is malformed, a formula is invalid, or a stated total does not
    reconcile with its computed value."""


# ---------------------------------------------------------- safe formula eval --

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv, ast.USub: operator.neg}


def _safe_eval(expr: str, env: dict) -> float:
    """Evaluate a total's formula over subtotal ids and numeric literals, with
    + - * / and unary minus only. No names beyond the known subtotal ids; no
    calls, attributes, or other node types -- safe by whitelist, never eval()."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise StatementError(f"formula references unknown subtotal id: {node.id!r}")
            return env[node.id]
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        raise StatementError(f"unsupported expression in formula: {expr!r}")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        raise StatementError(f"invalid formula: {expr!r}") from None
    return ev(tree)


# --------------------------------------------------------------- formatting --

def _to_number(value, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise StatementError(f"row {label!r}: amount {value!r} is not a number") from None


def format_amount(value: float, fmt: dict) -> str:
    """Format a number per an explicit format block (currency + thousands/decimal
    separators). Locale-driven formatting is #35; here the data states it, e.g.
    {currency: EUR, thousands: '.', decimal: ','} -> 'EUR 8.045,77'."""
    currency = fmt.get("currency", "")
    thousands = fmt.get("thousands", "")
    decimal = fmt.get("decimal", ".")
    negative = value < 0
    cents = int(round(abs(value) * 100))
    int_part, frac = divmod(cents, 100)
    grouped = f"{int_part:,}".replace(",", thousands) if thousands else str(int_part)
    out = f"{grouped}{decimal}{frac:02d}"
    if currency:
        out = f"{currency} {out}"
    if negative:
        out = f"-{out}"
    return out


# ------------------------------------------------------------- data loading --

def load_spec(path: Path) -> dict:
    """Load a statement spec from YAML (.yaml/.yml) or CSV (.csv). YAML carries an
    optional `format` block + a `rows` list; CSV is flat columns
    kind,label,amount,id,formula with default (plain) formatting."""
    path = Path(path)
    if not path.is_file():
        raise StatementError(f"statement data not found: {path}")
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict) or "rows" not in data:
            raise StatementError(f"{path.name}: expected a mapping with a 'rows' list")
        return data
    if suffix == ".csv":
        rows = []
        with path.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                row = {k: v for k, v in r.items() if v not in (None, "")}
                rows.append(row)
        return {"rows": rows}
    raise StatementError(f"unsupported statement data format: {path.suffix} (use .yaml or .csv)")


# ------------------------------------------------------- compute + reconcile --

def compute_rows(spec: dict) -> list:
    """Walk the spec rows computing subtotals (sum of a section's items), totals
    (a formula over subtotal ids, or the running sum of all items), and balances.
    A row that also STATES an amount must reconcile with the computed value to the
    cent, else StatementError. Returns render rows: {kind, label?, amount?}."""
    fmt = spec.get("format", {}) or {}
    rows = spec.get("rows", []) or []

    env: dict = {}       # subtotal id -> computed value
    group: list = []     # item values in the current section
    grand: list = []     # every item value (for a formula-less total)
    out: list = []

    for raw in rows:
        kind = (raw.get("kind") or "item").strip()
        label = raw.get("label", "")

        if kind == "rule":
            out.append({"kind": "rule"})
            continue
        if kind == "heading":
            out.append({"kind": "heading", "label": label})
            group = []
            continue
        if kind == "item":
            value = _to_number(raw.get("amount"), label)
            group.append(value)
            grand.append(value)
            out.append({"kind": "item", "label": label, "amount": format_amount(value, fmt)})
            continue
        if kind in _BOLD_KINDS:
            formula = raw.get("formula")
            if formula is not None:
                value = _safe_eval(str(formula), env)
            elif kind == "subtotal":
                value = sum(group)
            else:  # total / balance without a formula: sum of all items so far
                value = sum(grand)

            stated = raw.get("amount")
            if stated is not None:
                stated_v = _to_number(stated, label)
                if round(stated_v, 2) != round(value, 2):
                    raise StatementError(
                        f"reconciliation failed for {label!r}: stated "
                        f"{format_amount(stated_v, fmt)} != computed {format_amount(value, fmt)}")

            if "id" in raw:
                env[str(raw["id"])] = value
            if kind == "subtotal":
                group = []
            out.append({"kind": kind, "label": label, "amount": format_amount(value, fmt)})
            continue

        raise StatementError(f"unknown statement row kind: {kind!r}")

    return out


def to_block_markdown(rows: list) -> str:
    """Emit the computed rows as the #33 statement block's `kind | label | amount`
    bullet list, so the existing Lua filter + blocks.typ render them unchanged."""
    lines = []
    for r in rows:
        if r["kind"] == "rule":
            lines.append("- rule")
        elif r["kind"] == "heading":
            lines.append(f"- heading | {r['label']}")
        else:
            lines.append(f"- {r['kind']} | {r['label']} | {r['amount']}")
    return "\n".join(lines)


# ------------------------------------------- markdown expansion (pre-pandoc) --

_OPEN_RE = re.compile(r"^:::+\s*\{(?P<attrs>.*)\}\s*$")
_CLOSE_RE = re.compile(r"^:::+\s*$")
_DATA_RE = re.compile(r'data\s*=\s*(?:"([^"]+)"|(\S+))')


def _data_attr(attrs: str) -> "str | None":
    m = _DATA_RE.search(attrs)
    if not m:
        return None
    return m.group(1) or m.group(2)


def expand_markdown(md_text: str, base_dir: Path) -> str:
    """Replace every `::: {.statement data="..."}` block with a plain
    `::: statement` block whose rows are computed + reconciled from the data file
    (paths resolved against base_dir). Blocks without a `data` attribute (hand-
    typed rows) are left untouched. Raises StatementError on any reconciliation or
    data failure -- which fails the render, by design."""
    lines = md_text.split("\n")
    out: list = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _OPEN_RE.match(line)
        if m and ".statement" in m.group("attrs"):
            data = _data_attr(m.group("attrs"))
            j = i + 1
            body = []
            while j < len(lines) and not _CLOSE_RE.match(lines[j]):
                body.append(lines[j])
                j += 1
            closing = lines[j] if j < len(lines) else ":::"
            if data:
                spec = load_spec(Path(base_dir) / data)
                rows = compute_rows(spec)
                out.append("::: statement")
                out.append(to_block_markdown(rows))
                out.append(":::")
            else:
                out.append(line)
                out.extend(body)
                out.append(closing)
            i = j + 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)
