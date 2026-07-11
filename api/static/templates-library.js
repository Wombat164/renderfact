// templates-library.js: Template Library screen (chunk 6.5 / D23, design
// spike 5.6). GET /templates listing + a POST /templates/import form.

async function loadTemplates() {
  const cardsEl = document.getElementById('cards');
  const errEl = document.getElementById('err');
  const r = await jsonFetch('/templates');
  if (!r.ok) { showError(errEl, r.data.error || 'failed to load templates'); return; }
  const rows = r.data.templates || [];
  if (rows.length === 0) { cardsEl.innerHTML = '<p class="empty">No templates yet.</p>'; return; }
  cardsEl.innerHTML = rows.map(renderCard).join('');
}

function renderCard(t) {
  const provenance = t.derived_from
    ? `derived from ${escapeHtml(t.derived_from)}` : 'no DOCX derivation';
  return `<div class="card">
    <strong>${escapeHtml(t.name)}</strong>
    <span class="tag">${escapeHtml(t.doc_type || '-')}</span>
    <span class="tag">${t.builtin ? 'builtin' : 'custom'}</span>
    <p class="hint">${escapeHtml(t.description || '')}</p>
    <p class="hint">${provenance}</p>
    <a href="/ui/projects/new">Use in new project &rarr;</a>
  </div>`;
}

async function importTemplate() {
  const errEl = document.getElementById('err');
  errEl.textContent = '';
  const name = document.getElementById('t-name').value.trim();
  const source = document.getElementById('t-source').value.trim();
  if (!name || !source) { showError(errEl, 'name and source path are both required'); return; }
  const body = {
    name, source,
    doc_type: document.getElementById('t-doctype').value.trim() || undefined,
    description: document.getElementById('t-description').value.trim() || undefined,
  };
  const r = await mutate('POST', '/templates/import', body);
  if (!r.ok) { showError(errEl, r.data.error || `import failed (${r.status})`); return; }
  document.getElementById('t-name').value = '';
  document.getElementById('t-source').value = '';
  document.getElementById('t-doctype').value = '';
  document.getElementById('t-description').value = '';
  await loadTemplates();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

loadTemplates();
