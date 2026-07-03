#!/usr/bin/env bash
# verify-pins.sh -- assert the running image's engine versions match tools.lock.
# Run INSIDE the container: `sudo podman run --rm localhost/renderfact:latest bash verify-pins.sh`
# Exit 0 = all pins match; exit 1 = at least one drift. Advisory tools (drawio,
# libreoffice major) are reported but do NOT fail the gate (see tools.lock notes).
set -u
fail=0
check() { # name | actual | expected-substring
  local name="$1" actual="$2" want="$3"
  if printf '%s' "$actual" | grep -qF "$want"; then
    printf '  OK   %-12s %s\n' "$name" "$want"
  else
    printf '  DRIFT %-11s want=%s got=%q\n' "$name" "$want" "$actual"; fail=1
  fi
}
soft() { # advisory: report, never fail
  local name="$1" actual="$2" want="$3"
  if printf '%s' "$actual" | grep -qF "$want"; then printf '  ok   %-12s %s (advisory)\n' "$name" "$want"
  else printf '  note %-12s want=%s got=%q (advisory, not gating)\n' "$name" "$want" "$actual"; fi
}

echo "== render-toolchain verify-pins =="
check pandoc      "$(pandoc --version 2>/dev/null | head -1)"                 "pandoc 3.10"
check typst       "$(typst --version 2>/dev/null)"                            "typst 0.15.0"
check mmdc        "$(mmdc --version 2>/dev/null | tail -1)"                   "11.15.0"
check marp        "$(marp --version 2>/dev/null)"                             "v4.4.0"
check d2          "$(d2 --version 2>/dev/null)"                               "0.7.1"
check vale        "$(vale --version 2>/dev/null)"                             "3.15.1"
check cairosvg    "$(python3 -c 'import cairosvg;print(cairosvg.__version__)' 2>/dev/null)" "2.9.0"
check pypdf       "$(python3 -c 'import pypdf;print(pypdf.__version__)' 2>/dev/null)"        "6.14.2"
check docxcompose "$(python3 -c 'import docxcompose,importlib.metadata as m;print(m.version("docxcompose"))' 2>/dev/null)" "2.2.0"
check python      "$(python3 --version 2>/dev/null)"                          "3.11"
check likec4      "$(likec4 --version 2>/dev/null)"                          "1.58.0"
soft  chromium    "$(chromium --version 2>/dev/null | head -1)"               "149"
soft  libreoffice "$(soffice --version 2>/dev/null | head -1)"                "7.4"
soft  drawio      "$(dpkg-query -W -f='${Version}' drawio 2>/dev/null || echo MISSING)" "."

if [ "$fail" -eq 0 ]; then echo "== ALL CORE PINS OK =="; else echo "== PIN DRIFT DETECTED =="; fi
exit "$fail"
