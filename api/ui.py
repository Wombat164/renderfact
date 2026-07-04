"""ui.py: the reference UI (E3 + #45), one self-contained HTML page.

Vanilla JS, no build step, no external assets; served at /ui only when the
operator passes --enable-ui. The render studio (edit markdown -> live PNG
preview / download PDF) is the headline: it exercises the whole Track H pipeline
(typst backend, theme variants, semantic blocks, data statements, locale) over
POST /render/pdf. The D8 contract + projection panels remain below as before.
"""

UI_HTML = """<!doctype html>
<meta charset="utf-8">
<title>renderfact studio</title>
<style>
  body { font-family: sans-serif; margin: 1.5rem; max-width: 78rem; }
  h1 { font-size: 1.3rem; } h2 { font-size: 1.05rem; margin-top: 1.6rem; }
  textarea, input, select { font-family: monospace; box-sizing: border-box; }
  .hint { color: #666; font-size: .85rem; }
  .studio { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; align-items: start; }
  .studio textarea { width: 100%; height: 22rem; }
  .controls { display: flex; flex-wrap: wrap; gap: .4rem; margin: .4rem 0; }
  .controls input, .controls select { width: auto; }
  .preview { border: 1px solid #ccc; min-height: 22rem; background: #fafafa;
             display: flex; align-items: flex-start; justify-content: center; overflow: auto; }
  .preview img { max-width: 100%; box-shadow: 0 1px 6px rgba(0,0,0,.15); }
  .err { color: #b00; font-family: monospace; white-space: pre-wrap; font-size: .85rem; }
  pre { background: #f4f4f4; padding: .8rem; overflow-x: auto; white-space: pre-wrap; }
  button { margin-top: .3rem; }
  .below { max-width: 64rem; }
</style>
<h1>renderfact studio <span id="doctor" class="hint"></span></h1>
<p class="hint">Thin client of the local API. Docs: <a href="/docs">/docs</a>,
machine-readable: <a href="/openapi.json">/openapi.json</a>.</p>

<h2>Render (Track H)</h2>
<div class="controls">
  <input id="r-title" placeholder="title" value="Notulen Algemene Vergadering">
  <input id="r-org" placeholder="org (header)" value="VME Voorbeeld">
  <input id="r-date" placeholder="date / ISO" value="2025-02-15">
  <select id="r-variant"><option value="base">base</option></select>
  <select id="r-locale"><option value="">no locale</option></select>
  <button onclick="doRender('pdf')">Download PDF</button>
  <button onclick="downloadDocx()">Download DOCX</button>
</div>
<div class="controls">
  <span class="hint">insert block:</span>
  <button onclick="insertBlock('attendance')">attendance</button>
  <button onclick="insertBlock('statement')">statement</button>
  <button onclick="insertBlock('signatures')">signatures</button>
</div>
<div class="studio">
  <textarea id="md" oninput="schedulePreview()">## Aanwezigheid

::: attendance
- present | A. Janssens (voorzitter)
- proxy   | C. De Wit, via A. Janssens
- quorum  | 3 van de 5 leden aanwezig: quorum bereikt
:::

## Financieel overzicht

::: statement
- heading  | Ontvangsten
- item     | Bijdragen leden | EUR 8.045,77
- subtotal | Totaal ontvangsten | EUR 8.045,77
- rule
- total    | Saldo boekjaar | EUR 1.510,53
:::

## Ondertekening

::: signatures
- A. Janssens | Voorzitter
- B. Peeters  | Secretaris
:::</textarea>
  <div>
    <div class="controls">
      <button onclick="changePage(-1)">&#8592; prev</button>
      <span id="pager" class="hint">page 1 / 1</span>
      <button onclick="changePage(1)">next &#8594;</button>
    </div>
    <div class="preview"><img id="preview" alt="(preview renders here)"></div>
    <div id="r-err" class="err"></div>
  </div>
</div>

<div class="below">
<h2>Statement reconciliation (no render)</h2>
<p class="hint">Paste a statement data spec (YAML). Computes + reconciles via <code>/statement/check</code> -
a stated total that disagrees with the sum of its items is an error, before you render.</p>
<textarea id="stmt" style="width:100%;height:8rem">format: { currency: EUR }
rows:
  - { kind: heading, label: Ontvangsten }
  - { kind: item, label: Bijdragen leden, amount: 8000.00 }
  - { kind: item, label: Interesten, amount: 45.77 }
  - { kind: subtotal, id: ontvangsten, label: Totaal ontvangsten, amount: 8045.77 }
  - { kind: item, label: Onderhoud, amount: 6535.24 }
  - { kind: subtotal, id: uitgaven, label: Totaal uitgaven }
  - { kind: total, label: Saldo, formula: "ontvangsten - uitgaven" }</textarea>
<button onclick="checkStatement()">Check</button>
<pre id="stmt-out">(no result yet)</pre>

<h2>Step contracts (D8)</h2>
<select id="step"></select>
<button onclick="showSchema()">Show schema</button>
<pre id="schema">(pick a step)</pre>

<h2>Validate a candidate step output</h2>
<p class="hint">Paste the JSON an LLM (or a human) produced for the selected step.</p>
<textarea id="candidate" style="width:100%;height:6rem">{"status": "OK", "findings": [], "summary": "Clean layout.", "reviewer_mode": "copy-paste"}</textarea>
<button onclick="validateOutput()">Validate</button>
<pre id="validation">(no result yet)</pre>

<h2>Project a source (F1)</h2>
<p class="hint">Paths are resolved under the server root and jailed there.</p>
<input id="src" style="width:100%" placeholder="demo/source/signalling-it-refresh.md">
<input id="profiles" style="width:100%" placeholder="demo/profiles.yaml">
<input id="profile" style="width:100%" placeholder="public-tender">
<button onclick="project()">Project</button>
<pre id="projection">(no result yet)</pre>
</div>

<script>
const mdEl = document.getElementById('md');
const img = document.getElementById('preview');
const errEl = document.getElementById('r-err');
const val = id => document.getElementById(id).value;

let curPage = 1, totalPages = 1;
function renderBody(fmt) {
  const b = { markdown: mdEl.value, format: fmt, title: val('r-title'), org: val('r-org'),
              date: val('r-date'), variant: val('r-variant'), locale: val('r-locale') };
  if (fmt === 'png') b.page = curPage;
  Object.keys(b).forEach(k => (b[k] === '' && k !== 'markdown') && delete b[k]);
  return JSON.stringify(b);
}
async function doRender(fmt) {
  errEl.textContent = 'rendering...';
  const r = await fetch('/render/pdf', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: renderBody(fmt) });
  if (!r.ok) {
    let msg = 'render failed';
    try { msg = (await r.json()).error; } catch (e) {}
    errEl.textContent = msg;
    return;
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  if (fmt === 'png') {
    img.src = url; errEl.textContent = '';
    totalPages = parseInt(r.headers.get('X-Total-Pages') || '1', 10) || 1;
    if (curPage > totalPages) curPage = totalPages;
    document.getElementById('pager').textContent = 'page ' + curPage + ' / ' + totalPages;
  } else { const a = document.createElement('a'); a.href = url; a.download = 'render.pdf'; a.click(); }
}
function changePage(delta) {
  const next = Math.min(Math.max(curPage + delta, 1), totalPages);
  if (next !== curPage) { curPage = next; doRender('png'); }
}
async function downloadDocx() {
  errEl.textContent = 'rendering DOCX...';
  const r = await fetch('/render/docx', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ markdown: mdEl.value }) });
  if (!r.ok) {
    let msg = 'render failed';
    try { msg = (await r.json()).error; } catch (e) {}
    errEl.textContent = msg;
    return;
  }
  const blob = await r.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'render.docx'; a.click();
  errEl.textContent = '';
}
let previewTimer;
function schedulePreview() {
  curPage = 1;  // edits can change pagination; go back to the first page
  clearTimeout(previewTimer); previewTimer = setTimeout(() => doRender('png'), 600);
}
['r-title','r-org','r-date','r-variant','r-locale'].forEach(
  id => document.getElementById(id).addEventListener('change', () => doRender('png')));

const BLOCKS = {
  attendance: '\\n::: attendance\\n- present | Name\\n- proxy | Name, via X\\n- quorum | 3/5 present: quorum met\\n:::\\n',
  statement: '\\n::: statement\\n- heading | Section\\n- item | Line item | EUR 0,00\\n- total | Total | EUR 0,00\\n:::\\n',
  signatures: '\\n::: signatures\\n- Name | Role\\n- Name | Role\\n:::\\n',
};
function insertBlock(kind) {
  const t = BLOCKS[kind], at = mdEl.selectionStart;
  mdEl.value = mdEl.value.slice(0, at) + t + mdEl.value.slice(at);
  mdEl.focus(); schedulePreview();
}
async function checkStatement() {
  const out = document.getElementById('stmt-out');
  const r = await fetch('/statement/check', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data: document.getElementById('stmt').value, locale: val('r-locale') }) });
  const d = await r.json();
  if (r.ok) {
    out.style.color = '';
    out.textContent = d.rows.map(x => x.kind === 'rule' ? '----'
      : (x.label || '') + (x.amount ? '\\t' + x.amount : '')).join('\\n');
  } else { out.style.color = '#b00'; out.textContent = d.error; }
}
async function loadDoctor() {
  const r = await jsonFetch('/doctor');
  const el = document.getElementById('doctor');
  const ok = r.data.render_pdf_ready;
  el.textContent = ok ? '(PDF backend ready)' : '(PDF backend unavailable - need typst + pandoc)';
  el.style.color = ok ? '#2E7D32' : '#b00';
}
async function loadVariants() {
  const r = await jsonFetch('/theme/variants');
  const sel = document.getElementById('r-variant'); sel.innerHTML = '';
  (r.data.variants || ['base']).forEach(v => sel.add(new Option(v, v)));
}
async function loadLocales() {
  const r = await jsonFetch('/locales');
  const sel = document.getElementById('r-locale'); sel.innerHTML = '';
  sel.add(new Option('no locale', ''));
  (r.data.locales || []).forEach(l => sel.add(new Option(l.code, l.code)));
  sel.value = 'nl-BE';
}

async function jsonFetch(url, opts) {
  const r = await fetch(url, opts);
  const text = await r.text();
  try { return { ok: r.ok, data: JSON.parse(text) }; }
  catch { return { ok: r.ok, data: { raw: text } }; }
}
async function loadSteps() {
  const r = await jsonFetch('/steps');
  const sel = document.getElementById('step');
  (r.data.steps || []).forEach(s => {
    const o = document.createElement('option'); o.value = s; o.textContent = s; sel.appendChild(o);
  });
}
async function showSchema() {
  const r = await jsonFetch('/steps/' + document.getElementById('step').value);
  document.getElementById('schema').textContent = JSON.stringify(r.data, null, 2);
}
async function validateOutput() {
  const s = document.getElementById('step').value;
  const r = await jsonFetch('/steps/' + s + '/validate-output', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: document.getElementById('candidate').value });
  document.getElementById('validation').textContent = JSON.stringify(r.data, null, 2);
}
async function project() {
  const body = JSON.stringify({
    source: document.getElementById('src').value,
    profiles: document.getElementById('profiles').value,
    profile: document.getElementById('profile').value });
  const r = await jsonFetch('/project', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body });
  const d = r.data;
  document.getElementById('projection').textContent =
    d.text !== undefined ? ('blocks_dropped: ' + d.blocks_dropped + '\\n\\n' + d.text)
                         : JSON.stringify(d, null, 2);
}
loadSteps();
loadDoctor();
Promise.all([loadVariants(), loadLocales()]).then(() => doRender('png'));
</script>
"""
