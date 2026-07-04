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
<h1>renderfact studio</h1>
<p class="hint">Thin client of the local API. Docs: <a href="/docs">/docs</a>,
machine-readable: <a href="/openapi.json">/openapi.json</a>.</p>

<h2>Render (Track H)</h2>
<div class="controls">
  <input id="r-title" placeholder="title" value="Notulen Algemene Vergadering">
  <input id="r-org" placeholder="org (header)" value="VME Voorbeeld">
  <input id="r-date" placeholder="date / ISO" value="2025-02-15">
  <select id="r-variant"><option value="base">base</option><option value="financial">financial</option></select>
  <select id="r-locale">
    <option value="">no locale</option><option value="nl-BE" selected>nl-BE</option>
    <option value="fr-BE">fr-BE</option><option value="en">en</option>
  </select>
  <button onclick="doRender('pdf')">Download PDF</button>
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
    <div class="preview"><img id="preview" alt="(preview renders here)"></div>
    <div id="r-err" class="err"></div>
  </div>
</div>

<div class="below">
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

function renderBody(fmt) {
  const b = { markdown: mdEl.value, format: fmt, title: val('r-title'), org: val('r-org'),
              date: val('r-date'), variant: val('r-variant'), locale: val('r-locale') };
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
  if (fmt === 'png') { img.src = url; errEl.textContent = ''; }
  else { const a = document.createElement('a'); a.href = url; a.download = 'render.pdf'; a.click(); }
}
let previewTimer;
function schedulePreview() { clearTimeout(previewTimer); previewTimer = setTimeout(() => doRender('png'), 600); }
['r-title','r-org','r-date','r-variant','r-locale'].forEach(
  id => document.getElementById(id).addEventListener('change', () => doRender('png')));

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
doRender('png');
</script>
"""
