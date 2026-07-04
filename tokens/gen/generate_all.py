#!/usr/bin/env python3
"""
Run all four per-engine token generators against tokens/brand.yaml (chunk 0.4 / A1).

Usage:
    python tokens/gen/generate_all.py [--brand path/to/consumer/brand.yaml] [--output-dir DIR]

--output-dir, if given, is treated as a PARENT dir; each generator still writes into
its own <output-dir>/<engine>/ subfolder (mermaid/, marp/, pandoc/, typst/).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import marp_theme  # noqa: E402
import mermaid_theme  # noqa: E402
import pandoc_template_profile  # noqa: E402
import typst_tokens  # noqa: E402

GENERATORS = [mermaid_theme, marp_theme, pandoc_template_profile, typst_tokens]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", type=Path, default=None,
                         help="Consumer brand.yaml override (optional)")
    parser.add_argument("--output-dir", default=None,
                         help="Parent output directory (each generator gets its own subfolder)")
    args = parser.parse_args()

    argv = []
    if args.brand:
        argv += ["--brand", str(args.brand)]
    if args.output_dir:
        # Each generator resolves its own subdir under whatever --output-dir it's given;
        # pass the SAME parent so mermaid/marp/pandoc/typst all land under one tree.
        pass  # handled per-generator below via subdir join

    exit_code = 0
    for gen in GENERATORS:
        gen_argv = list(argv)
        if args.output_dir:
            subdir_name = {
                mermaid_theme: "mermaid",
                marp_theme: "marp",
                pandoc_template_profile: "pandoc",
                typst_tokens: "typst",
            }[gen]
            gen_argv += ["--output-dir", str(Path(args.output_dir) / subdir_name)]
        old_argv = sys.argv
        try:
            sys.argv = [gen.__name__ + ".py", *gen_argv]
            rc = gen.main()
            if rc != 0:
                exit_code = rc
        finally:
            sys.argv = old_argv

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
