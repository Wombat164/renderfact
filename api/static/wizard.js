// wizard.js: New Project wizard, manual path only (chunk 6.5 / D18, design
// spike 5.2). Auto-choose (the manual-vs-auto toggle, chooser confidence
// panel, copy-paste escalation surface) is chunk 6.7 -- this ships with zero
// LLM machinery, exactly as the roadmap sequences it.

let selectedTemplate = null;

async function loadTemplates() {
  const el = document.getElementById('w-templates');
  const r = await jsonFetch('/templates');
  if (!r.ok) { el.innerHTML = '<p class="hint err">failed to load templates</p>'; return; }
  const rows = r.data.templates || [];
  el.innerHTML = rows.map(t => `
    <div class="card" data-name="${escapeHtml(t.name)}" onclick="selectTemplate('${escapeHtml(t.name)}')">
      <strong>${escapeHtml(t.name)}</strong>
      <span class="hint">${escapeHtml(t.doc_type || '-')}${t.builtin ? ' (builtin)' : ''}</span>
      <p class="hint">${escapeHtml(t.description || '')}</p>
    </div>`).join('');
}

function selectTemplate(name) {
  selectedTemplate = name;
  document.querySelectorAll('#w-templates .card').forEach(c => {
    c.classList.toggle('selected', c.dataset.name === name);
  });
}

async function createProject() {
  const errEl = document.getElementById('err');
  errEl.textContent = '';
  const name = document.getElementById('w-name').value.trim();
  if (!name) { showError(errEl, 'project name is required'); return; }
  const body = {
    name,
    title: document.getElementById('w-title').value.trim() || undefined,
    template: selectedTemplate || undefined,
    doc_type: document.getElementById('w-doctype').value,
    diagram_scaffold: document.getElementById('w-scaffold').value,
  };
  const r = await mutate('POST', '/projects', body);
  if (!r.ok) { showError(errEl, r.data.error || `create failed (${r.status})`); return; }
  // The Project Workspace (chunk 6.6) is not built yet: land on the
  // Dashboard, where the new project is now visible.
  window.location.href = '/ui/projects';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

loadTemplates();
