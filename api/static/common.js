// common.js: shared fetch + CSRF helpers for the Track J workspace screens
// (chunk 6.5 / D23). Vanilla JS, no build step -- same discipline as api/ui.py.

let _csrfToken = null;

async function jsonFetch(url, opts) {
  const r = await fetch(url, opts || {});
  const text = await r.text();
  try { return { ok: r.ok, status: r.status, data: JSON.parse(text) }; }
  catch { return { ok: r.ok, status: r.status, data: { raw: text } }; }
}

async function csrfToken() {
  if (_csrfToken) return _csrfToken;
  const r = await jsonFetch('/session');
  _csrfToken = r.data.csrf_token;
  return _csrfToken;
}

// A mutating call (POST/PUT): attaches the CSRF token every truly-mutating
// route requires (D15). One call site so every workspace screen enforces it
// the same way -- a screen cannot forget the header.
async function mutate(method, url, body) {
  const token = await csrfToken();
  return jsonFetch(url, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
    body: JSON.stringify(body),
  });
}

function showError(el, message) {
  el.textContent = message;
}

async function loadDoctorBadge(elId) {
  const el = document.getElementById(elId);
  if (!el) return;
  const r = await jsonFetch('/doctor');
  const ok = r.data.render_pdf_ready;
  el.textContent = ok ? '(PDF backend ready)' : '(PDF backend unavailable - need typst + pandoc)';
  el.style.color = ok ? '#2E7D32' : '#b00';
}
