// dashboard.js: Projects Dashboard (chunk 6.5 / D18, design spike 5.1).

async function loadProjects() {
  const cardsEl = document.getElementById('cards');
  const errEl = document.getElementById('err');
  const r = await jsonFetch('/projects');
  if (!r.ok) { showError(errEl, r.data.error || 'failed to load projects'); return; }
  const rows = r.data.projects || [];
  if (rows.length === 0) {
    cardsEl.innerHTML = '<p class="empty">No projects yet. '
      + '<a href="/ui/projects/new">Start one</a>.</p>';
    return;
  }
  cardsEl.innerHTML = rows.map(renderCard).join('');
}

function renderCard(row) {
  if (row.error) {
    return `<div class="card"><h3>${escapeHtml(row.name)}</h3>`
      + `<p class="hint err">${escapeHtml(row.error)}</p></div>`;
  }
  const last = row.last_render;
  const lastLine = last
    ? `last: ${escapeHtml(last.format || '?')} @ ${escapeHtml(last.ts || '?')}`
    : 'no renders yet';
  // The Project Workspace (chunk 6.6) is not built yet: the title links to
  // the raw GET /projects/{name} response as an honest placeholder, and will
  // point at /ui/projects/{name} once the workspace page lands.
  return `<div class="card">
    <h3><a href="/projects/${encodeURIComponent(row.name)}">${escapeHtml(row.name)}</a></h3>
    <span class="badge">${escapeHtml(row.doc_type || '-')}</span>
    <span class="badge">${escapeHtml(row.template || '-')}</span>
    <span class="badge">${escapeHtml(row.default_profile || '-')}</span>
    <p class="hint">${lastLine}</p>
  </div>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

loadProjects();
loadDoctorBadge('doctor');
