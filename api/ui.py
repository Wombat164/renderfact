"""ui.py: the thin reference UI (E3), one self-contained HTML page.

Deliberately undecorated (D9: the API is the product, this page is a proof it
works and a template for swapping in a richer client). Vanilla JS, no build
step, no external assets; served at /ui only when the operator passes
--enable-ui (docling-serve's opt-in mount pattern).
"""

UI_HTML = """<!doctype html>
<meta charset="utf-8">
<title>renderfact reference UI</title>
<style>
  body { font-family: sans-serif; margin: 2rem; max-width: 64rem; }
  h1 { font-size: 1.3rem; } h2 { font-size: 1.05rem; margin-top: 1.6rem; }
  textarea, input, select { font-family: monospace; width: 100%; box-sizing: border-box; }
  textarea { height: 8rem; }
  pre { background: #f4f4f4; padding: .8rem; overflow-x: auto; white-space: pre-wrap; }
  button { margin-top: .4rem; }
  .hint { color: #666; font-size: .85rem; }
</style>
<h1>renderfact reference UI</h1>
<p class="hint">Thin client of the local API. Endpoint docs: <a href="/docs">/docs</a>,
machine-readable: <a href="/openapi.json">/openapi.json</a>.</p>

<h2>1. Step contracts (D8)</h2>
<select id="step"></select>
<button onclick="showSchema()">Show schema</button>
<pre id="schema">(pick a step)</pre>

<h2>2. Validate a candidate step output</h2>
<p class="hint">Paste the JSON an LLM (or a human) produced for the selected step.</p>
<textarea id="candidate">{"status": "OK", "findings": [], "summary": "Clean layout.", "reviewer_mode": "copy-paste"}</textarea>
<button onclick="validateOutput()">Validate</button>
<pre id="validation">(no result yet)</pre>

<h2>3. Project a source (F1)</h2>
<p class="hint">Paths are resolved under the server root and jailed there.</p>
<input id="src" placeholder="demo/source/signalling-it-refresh.md">
<input id="profiles" placeholder="demo/profiles.yaml">
<input id="profile" placeholder="public-tender">
<button onclick="project()">Project</button>
<pre id="projection">(no result yet)</pre>

<script>
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
    const o = document.createElement('option'); o.value = s; o.textContent = s;
    sel.appendChild(o);
  });
}
async function showSchema() {
  const s = document.getElementById('step').value;
  const r = await jsonFetch('/steps/' + s);
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
</script>
"""
