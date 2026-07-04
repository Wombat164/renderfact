# D8 copy-paste fallback: design spike (chunk 3.3)

Status: design spec, no implementation. Per `docs/EXECUTION-PLAN.md`, chunk 3.3 is
explicitly *not* a normal implementation chunk -- output is a written design + one
worked example, preceded by the OQ2 research pass. Implementation is chunk 3.4.

## 1. OQ2 resolution (the research pass this spike required)

Question: is D8's copy-paste pattern genuinely novel, or is there prior art under
different vocabulary? A second, differently-worded research pass (2026-07-03,
one targeted agent) found what the original 105-agent sweep missed:

- **`aider --copy-paste` mode** (Apache-2.0, `github.com/Aider-AI/aider`,
  https://aider.chat/docs/usage/copypaste.html) -- assembles file+task context to
  the clipboard, watches the clipboard for the pasted-back LLM reply, auto-detects
  the change, parses it against a fixed *edit format* grammar, and applies it. This
  is the same assemble -> clipboard -> external chat UI -> auto-detect paste-back ->
  parse -> continue loop D8 describes, built and shipped before renderfact existed.
- **`metaprompting`'s `CopyPasteLLM`** (CognitiveComputingLab,
  `github.com/CognitiveComputingLab/metaprompting`) -- an academic meta-prompting
  library whose own docstring says it exists to *"simulate an LLM API by
  copy-pasting over prompts and responses."* Same clipboard-watch UX, independently
  built.

**Verdict:** the low-level bridging *mechanism* is not novel -- cite both, and
**borrow aider's clipboard-watch auto-detect UX** rather than re-inventing it (see
`3.4` design note below). What genuinely has no prior art, confirmed again on this
pass, is D8's actual claim: a **generalized step contract** where a harness-mode
result and a copy-paste-mode result are **schema-validated against the identical
rule** and are indistinguishable to every downstream consumer. aider's contract is
narrow (code diffs only, an informal grammar, no harness/no-harness duality since
copy-paste is its *only* mode). `metaprompting`'s has no schema/validation layer at
all. So: renderfact assembles a known bridging technique into a new, more
disciplined contract -- not "invents copy-paste bridging," not "totally
unprecedented" either. Full agent transcript available on request; not duplicated
here per the existing convention of keeping cited findings in the docs, not the
raw transcript.

## 2. Design goals (recap of D8's actual constraints)

From `docs/DECISIONS.md` D8 and the dictated requirement it codifies:

1. **Identical contract.** A harness-mode result and a copy-paste-mode result must
   both validate against the exact same `OUTPUT_SCHEMA` (chunk 3.1). No
   copy-paste-only leniency, no harness-only shortcuts.
2. **No browser automation.** The OQ2 pass surfaced tools (`ChatGPT-Bridge`,
   `GPT_scraper`, session-scraping browser automation) that fake an API against a
   chat UI via Selenium/cookies -- the opposite of what D8 wants. renderfact never
   drives a browser. The human is the only thing that touches the chat UI.
3. **Self-contained prompt.** The assembled prompt must contain everything the
   target chat LLM needs -- task, input data, and the *exact* output shape -- with
   zero assumed prior context, because the user might paste it into a brand-new
   chat with no memory of renderfact.
4. **Graceful degradation, not a hard dependency.** Must work in an environment
   with no clipboard access at all (e.g. a headless SSH session) -- clipboard
   convenience is an enhancement layer on top of a baseline that always works via
   plain stdin paste.
5. **Reuse, don't re-templatize.** Chunk 3.2 already built
   `contracts/init_ai.py:render_step_instructions()`, which renders a step's
   `TASK_INTENT` + `INPUT_SCHEMA` + `OUTPUT_SCHEMA` (including nested `item_schema`
   expansion) into readable instruction text. That text is already ~95% of a
   copy-paste prompt body -- see the worked example below, which is that function's
   literal output for `vision-review`. The copy-paste path should call the *same*
   function, not duplicate the schema-to-prose rendering.

## 3. The design

### 3.1 Flow

```
render vision-review <svg> --tier <tier> --copy-paste
  |
  1. assemble_input()            <- chunk 3.1, unchanged, deterministic
  2. render_step_instructions()  <- chunk 3.2, unchanged, mode param added (3.a below)
  3. compose ONE paste-in prompt <- new: input data (as JSON) + instructions + output shape
  4. deliver the prompt          <- new: print to stdout AND write to a file AND
                                     (if `pyperclip` present) auto-copy to clipboard
  5. wait for paste-back         <- new: read multi-line stdin until a sentinel, OR
                                     (if `pyperclip` present) watch the clipboard for
                                     a change, like aider -- user's choice, both must work
  6. parse as JSON/YAML          <- new: try JSON first, then YAML (D8's own wording:
                                     "produces a json or yaml, whichever fits")
  7. validate_output()           <- chunk 3.1, unchanged
  8a. valid -> stamp reviewer_mode="copy-paste" if the model didn't set it correctly,
      continue the pipeline
  8b. invalid -> print the SPECIFIC validate_output() errors, re-show only the
      broken fields (not the whole prompt again), let the user fix and re-paste --
      bounded retry loop, not silent failure
```

### 3.2 The composed prompt (concrete shape)

```
<task instructions, from render_step_instructions() with mode="copy-paste"
 instead of "harness" in its closing line -- the ONLY change needed to that
 function; see 3.a>

---
INPUT DATA (JSON):
<json.dumps(assemble_input(...), indent=2)>

---
ATTACH the image at: <rendered_image_path>
(most chat UIs accept an image paste/upload alongside text -- attach it in
 the same message as this prompt)

---
Respond with ONLY a single JSON object matching the OUTPUT SCHEMA above.
No markdown fencing, no commentary before or after -- just the JSON object,
so it can be pasted directly back into the terminal.
```

Rationale for `INPUT DATA (JSON)` as a raw JSON block rather than prose: the
input schema already has `deterministic_metrics`, a nested dict of numeric
results (from `svg_metrics.py`/`visual_quality.py`) that reads far more reliably
to an LLM as JSON than as hand-written prose, and it keeps `assemble_input()`'s
output byte-identical to what harness mode consumes -- no lossy re-formatting
step to maintain in parallel.

Rationale for the closing "respond with ONLY a JSON object, no fencing" line:
every major chat LLM (ChatGPT, Claude.ai, Copilot) defaults to wrapping code
blocks in triple-backtick fences; the parser in step 6 must strip a fenced block
if present rather than assume raw JSON, since a strict "must be raw" instruction
alone is not reliable enough across models -- this is a **parser-side robustness
requirement for 3.4**, not something the prompt wording alone can guarantee.

### 3.3 (a) The one small change chunk 3.4 needs to make to chunk 3.2's code

`render_step_instructions()` currently hardcodes its closing line: `Set
reviewer_mode to "harness".` This needs a `mode: str` parameter
(`"harness" | "copy-paste"`) so the same function serves both callers without
duplicating the schema-to-prose logic -- the ONLY change needed to existing
code; everything else in this design is new.

### 3.4 Output capture: stdin sentinel vs. clipboard-watch

Two paste-back mechanisms, both must work (goal 4):

- **Baseline (always works): stdin sentinel.** Print `Paste the LLM's JSON/YAML
  response below, then a line containing only END:`, read lines until a line
  that is exactly `END`, join and parse. Works over SSH, in a plain terminal, in
  CI-adjacent debugging -- zero new dependencies.
- **Enhancement (if `pyperclip` -- or a platform tool: `xclip`/`xsel` on Linux,
  `pbpaste` on macOS, `Get-Clipboard`/`clip.exe` on Windows -- is importable):
  auto-copy the prompt to the clipboard on delivery (skip the copy step for the
  user), then poll the clipboard for a change and auto-consume it the moment the
  user pastes the LLM's reply somewhere and it lands on the clipboard -- this is
  exactly aider's UX, cited in section 1, and should be imitated rather than
  redesigned.** Still falls back to the stdin sentinel if no clipboard tool is
  importable, or if the user simply presses Enter without a clipboard change
  (e.g. because they're going to paste into stdin directly instead).

### 3.5 Validation + retry loop

`validate_output()` (chunk 3.1, unchanged) already returns `(bool, list[str])` --
specific field-level errors, not a generic failure. On a failed paste-back:

```
BLOCKED: the pasted response failed validation:
  - missing required field 'reviewer_mode'
  - field 'status'='MAYBE' not in allowed values ('OK', 'WARN', 'BLOCK')

Fix these fields in your response and paste the corrected JSON below (or Ctrl-C
to abort):
```

Bounded retry (a small fixed max, e.g. 3 attempts) rather than an infinite loop,
so a genuinely confused human or a badly-behaving LLM doesn't hang the pipeline
forever -- exact bound is a 3.4 implementation detail, not a design commitment
here.

### 3.6 Parser robustness (JSON first, then YAML, then fenced-block stripping)

Per D8's own wording ("produces a json or yaml, whichever fits"), the parser
tries, in order: (1) raw `json.loads`, (2) strip a leading/trailing triple-backtick
fence (with or without a `json`/`yaml` language tag) and retry `json.loads`, (3)
`yaml.safe_load` on the (possibly fence-stripped) text. First success wins; if all
three fail, treat it as a validation failure with a clear "could not parse as
JSON or YAML" message feeding into the same retry loop as 3.5, not a separate
error path.

## 4. Worked example: vision-review, end to end

**Step 1-2, unchanged, literal output of `render_step_instructions("vision-review",
vision_review_contract)` today** (chunk 3.2, verified by running it):

```
## vision-review

**Task:**
Assess this rendered diagram for subjective layout quality that geometry-based
metrics cannot capture: visual hierarchy (does the eye land on the right element
first), legend/label clutter, whether the flow direction reads naturally, and
whether the diagram communicates its intended message at the stated view-tier.
Deterministic metrics (edge crossings, node overlap, whitespace, palette/contrast/
a11y) are provided as context -- do not re-derive them, judge what they miss.

**Input you will receive** (assembled deterministically -- identical to what a
human's copy-paste flow would receive):
- `task_intent` (str, required): Fixed instruction text (see TASK_INTENT) --
  what judgment is wanted.
- `rendered_image_path` (str, required): Path to the rendered diagram image (PNG
  preferred -- pasteable/viewable in any chat LLM UI; SVG accepted if PNG
  unavailable).
- `tier` (str, required, one of: executive-cover, programme-planning,
  operator-handoff, procurement-annex): View-tier the diagram was rendered for; sets the
  review's strictness lens.
- `deterministic_metrics` (dict, required): svg_metrics.py + visual_quality.py
  results for the same file.

**Output you must produce** (validated by `vision_review_contract.validate_output()`
-- the same rule for every mode, harness or copy-paste):
- `status` (str, required, one of: OK, WARN, BLOCK): Overall verdict -- same
  three-state vocabulary as visual_quality.py.
- `findings` (list, required): Per-criterion findings.
  Each item is an object with:
  - `criterion` (str, required): e.g. visual-hierarchy, legend-clarity,
    label-legibility, flow-readability
  - `severity` (str, required, one of: info, warn, block): Per-finding severity.
  - `comment` (str, required): One sentence, specific.
- `summary` (str, required): One-paragraph human-readable verdict.
- `reviewer_mode` (str, required, one of: harness, copy-paste): Which D8 mode
  produced this output -- provenance, not a quality signal.

Set `reviewer_mode` to `"copy-paste"`.  <- (3.3.a's parameterization, "copy-paste"
                                           instead of today's hardcoded "harness")
```

**Step 3, the full composed prompt (steps 1-2's text, plus the new parts from
3.2):**

```
<...the block above, verbatim...>

---
INPUT DATA (JSON):
{
  "task_intent": "Assess this rendered diagram for subjective layout quality ...",
  "rendered_image_path": "renders/fog-edge-tenancy-hero.png",
  "tier": "operator-handoff",
  "deterministic_metrics": {
    "edge_crossings": 3,
    "node_overlap_pairs": 0,
    "whitespace_pct": 41.2,
    "wong_palette_pass": true,
    "svg_a11y_pass": true,
    "wcag_contrast_pass": true
  }
}

---
ATTACH the image at: renders/fog-edge-tenancy-hero.png
(most chat UIs accept an image paste/upload alongside text -- attach it in the
same message as this prompt)

---
Respond with ONLY a single JSON object matching the OUTPUT SCHEMA above. No
markdown fencing, no commentary before or after -- just the JSON object, so it
can be pasted directly back into the terminal.
```

**Step 4-5:** printed to stdout, written to
`.renderfact-copy-paste-prompt.txt`, auto-copied to clipboard if `pyperclip`
is importable; script then either watches the clipboard (aider-style) or
prints the stdin-sentinel prompt from 3.4.

**Step 6, a plausible pasted-back reply (fenced, as most chat UIs default to):**

````
```json
{
  "status": "WARN",
  "findings": [
    {
      "criterion": "legend-clarity",
      "severity": "warn",
      "comment": "The tenancy-tier legend overlaps the DCINet OOB node label in the lower-right quadrant."
    }
  ],
  "summary": "Overall layout is clear and the flow reads top-to-bottom naturally, but the legend placement needs to move to avoid overlapping a node label.",
  "reviewer_mode": "copy-paste"
}
```
````

**Step 6-7:** fence stripped (3.6), parsed as JSON, `validate_output()` returns
`(True, [])` -- all required fields present, `status` and each finding's
`severity` are in their allowed-value sets, `reviewer_mode` is
`"copy-paste"`. Pipeline continues exactly as it would have with a harness-mode
result.

## 5. Explicitly out of scope for this spike (deferred to chunk 3.4)

- Actual code: `contracts/copy_paste.py`, the `mode` param on
  `render_step_instructions()`, the stdin-sentinel reader, the optional
  clipboard-watch loop, the JSON/YAML/fence-stripped parser, the bounded retry
  loop, and the `render.py` CLI wiring (e.g. a `--copy-paste` flag or a
  standalone `render <step> --copy-paste` invocation shape -- exact CLI surface
  is a 3.4 decision, not fixed here).
- Whether `pyperclip` becomes a new pinned dependency (`tools.lock`) or whether
  renderfact shells out to the platform-native clip tool directly (`xclip`/
  `pbpaste`/`clip.exe`) to avoid adding a Python dependency for a convenience
  layer that already has a working fallback -- open question for 3.4, not
  resolved here.
- The exact retry bound (this doc says "a small fixed max, e.g. 3" -- 3.4 picks
  the real number).
- Whether the `.renderfact-copy-paste-prompt.txt` scratch file (mentioned in
  step 4 above as a convenience for very long prompts that are awkward to
  re-read from a scrolled terminal) needs to be `.gitignore`d -- yes, trivially,
  but that's a 3.4 implementation detail, not a design decision.

## 6. Why this is enough to unblock 3.4

Chunk 3.4's "Done" bar (`docs/EXECUTION-PLAN.md`) is "the 3.1 step works
end-to-end in copy-paste mode; both modes now proven on one real step." Every
piece of that flow is now specified above with a concrete worked example against
the real vision-review contract (not a hypothetical), the one prior-art gap
(OQ2) is resolved with two citable adoptable-pattern references, and the only
change to existing chunk-3.1/3.2 code is identified precisely (the `mode`
param). 3.4 is scoping and implementation from here, not further design.
