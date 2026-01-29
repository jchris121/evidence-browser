// ─── Auth State ───
let authToken = localStorage.getItem('evidence_token');
let currentUser = null;

function authHeaders() {
  return authToken ? { 'Authorization': 'Bearer ' + authToken } : {};
}

async function handleLogin(e) {
  e.preventDefault();
  const btn = document.getElementById('login-btn');
  const errEl = document.getElementById('login-error');
  btn.disabled = true;
  errEl.style.display = 'none';

  const username = document.getElementById('login-username').value;
  const password = document.getElementById('login-password').value;

  try {
    const r = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(d.detail || 'Login failed');
    }
    const data = await r.json();
    authToken = data.token;
    currentUser = data.user;
    localStorage.setItem('evidence_token', authToken);
    showApp();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.style.display = 'block';
  }
  btn.disabled = false;
}

async function handleLogout() {
  try {
    await fetch('/api/auth/logout', { method: 'POST', headers: authHeaders() });
  } catch {}
  authToken = null;
  currentUser = null;
  localStorage.removeItem('evidence_token');
  showLogin();
}

async function checkAuth() {
  if (!authToken) { showLogin(); return; }
  try {
    const r = await fetch('/api/auth/check', { headers: authHeaders() });
    if (!r.ok) throw new Error();
    const data = await r.json();
    if (!data.authenticated) throw new Error();
    currentUser = data.user;
    showApp();
  } catch {
    authToken = null;
    localStorage.removeItem('evidence_token');
    showLogin();
  }
}

function showLogin() {
  document.getElementById('login-page').style.display = 'flex';
  document.getElementById('app-container').style.display = 'none';
}

function showApp() {
  document.getElementById('login-page').style.display = 'none';
  document.getElementById('app-container').style.display = '';

  // Update user info
  document.getElementById('user-display').textContent = currentUser?.display_name || currentUser?.username || '';
  document.getElementById('user-role-badge').textContent = currentUser?.role || '';

  // Show admin tab if admin
  const adminBtn = document.getElementById('admin-nav-btn');
  if (adminBtn) adminBtn.style.display = currentUser?.role === 'admin' ? '' : 'none';

  // Load device names and init
  fetch('/api/device-names', { headers: authHeaders() }).then(r => r.json()).then(d => { deviceNames = d; }).catch(() => {});
  initApp();
}

// Device friendly names (loaded from server)
let deviceNames = {};

function getDeviceName(id) {
    const info = deviceNames[id];
    if (info) return info.name;
    return id.replace(/_/g, ' ').replace(/nonPriv|TaintClear/g, '').trim();
}

function getDeviceOwner(id) {
    const info = deviceNames[id];
    return info ? info.owner : 'Unknown';
}

function getDeviceIcon(id) {
    const info = deviceNames[id];
    if (!info) return '📱';
    if (info.type === 'laptop') return '💻';
    if (info.type === 'desktop') return '🖥️';
    return '📱';
}

// Evidence Browser SPA — UX Overhaul
const API = '';
let state = { view: 'discoveries', devices: [], stats: {}, currentDevice: null, searchQuery: '' };
let chatHistory = [];
let chatBusy = false;

// Device view state
let deviceState = {
  cat: null,
  page: 1,
  query: '',
  dateFrom: '',
  dateTo: '',
  mediaPage: 1,
};

// --- API ---
async function api(path, opts = {}) {
  const headers = { ...authHeaders(), ...(opts.headers || {}) };
  const r = await fetch(API + path, { ...opts, headers });
  if (r.status === 401) { handleLogout(); throw new Error('Session expired'); }
  return r.json();
}

// --- Router ---
function navigate(view, params = {}) {
  state.view = view;
  Object.assign(state, params);
  if (view === 'device') {
    deviceState = { cat: params._cat || null, page: 1, query: '', dateFrom: '', dateTo: '', mediaPage: 1 };
  }
  render();
}

// --- Render ---
function render() {
  const main = document.getElementById('app');
  const views = { dashboard: renderDashboard, device: renderDevice, search: renderSearch, discoveries: renderDiscoveries, mindmap: renderMindMap, legal: renderLegalFiles, admin: renderAdmin };
  (views[state.view] || renderDashboard)(main);
  document.querySelectorAll('#nav-buttons button').forEach(b => {
    b.classList.toggle('active', b.dataset.view === state.view);
  });
}

// --- Dashboard ---
async function renderDashboard(el) {
  el.innerHTML = '<div class="loading">Loading evidence data</div>';
  if (!state.devices.length) {
    [state.devices, state.stats] = await Promise.all([api('/api/devices'), api('/api/stats')]);
  }
  const s = state.stats;
  const cats = s.categories || {};
  const lastIdx = s.last_indexed ? new Date(s.last_indexed * 1000).toLocaleString('en-US', {dateStyle:'short',timeStyle:'short'}) : 'never';

  el.innerHTML = `
    <div class="stats-grid">
      <div class="stat-card"><div class="value">${fmt(s.total_devices)}</div><div class="label">Devices</div></div>
      <div class="stat-card"><div class="value">${fmt(cats.chats || 0)}</div><div class="label">Chat Messages</div></div>
      <div class="stat-card"><div class="value">${fmt(cats.calls || 0)}</div><div class="label">Calls</div></div>
      <div class="stat-card"><div class="value">${fmt(cats.contacts || 0)}</div><div class="label">Contacts</div></div>
      <div class="stat-card"><div class="value">${fmt(cats.emails || 0)}</div><div class="label">Emails</div></div>
      <div class="stat-card"><div class="value">${fmt(cats.locations || 0)}</div><div class="label">Locations</div></div>
      <div class="stat-card"><div class="value">${fmt(s.rag_chunks || 0)}</div><div class="label">RAG Chunks</div></div>
      <div class="stat-card"><div class="value">${fmt(cats.axiom_records || 0)}</div><div class="label">AXIOM Records</div></div>
    </div>
    <div style="margin-bottom:16px;display:flex;align-items:center;gap:12px">
      <span style="color:var(--text2);font-size:12px">Last indexed: ${lastIdx}</span>
      <button onclick="doRefresh(this)" style="padding:4px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;color:var(--text);cursor:pointer;font-size:12px">🔄 Refresh Index</button>
      <span id="refresh-status" style="color:var(--accent2);font-size:12px"></span>
    </div>
    <h3 style="margin-bottom:16px;color:var(--text2)">All Devices (${state.devices.length})</h3>
    <div class="filter-bar">
      <input type="text" id="device-filter" placeholder="Filter devices..." oninput="filterDevices()">
      <select id="owner-filter" onchange="filterDevices()">
        <option value="">All Owners</option>
        ${[...new Set(state.devices.map(d => d.owner))].sort().map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('')}
      </select>
      <select id="source-filter" onchange="filterDevices()">
        <option value="">All Sources</option>
        <option value="cellebrite">Cellebrite</option>
        <option value="axiom">AXIOM</option>
      </select>
    </div>
    <div class="device-grid" id="device-grid"></div>
  `;
  filterDevices();
}

function filterDevices() {
  const q = (document.getElementById('device-filter')?.value || '').toLowerCase();
  const owner = document.getElementById('owner-filter')?.value || '';
  const source = document.getElementById('source-filter')?.value || '';
  const grid = document.getElementById('device-grid');
  const filtered = state.devices.filter(d => {
    if (q && !`${d.name} ${d.owner} ${d.type}`.toLowerCase().includes(q)) return false;
    if (owner && d.owner !== owner) return false;
    if (source && d.source !== source) return false;
    return true;
  });
  grid.innerHTML = filtered.map(d => {
    const cats = Object.entries(d.categories || {}).filter(([,v]) => v > 0).slice(0, 8);
    const extractions = d.extractions || [];
    const extractionBadges = extractions.length > 1
      ? extractions.map(e => {
          const cls = (e.suffix || '').toLowerCase().includes('taint') ? 'taint' : (e.suffix || '').toLowerCase().includes('priv') ? 'nonpriv' : 'primary';
          return `<span class="extraction-badge ${cls}">${esc(e.suffix || 'Primary')}</span>`;
        }).join(' ')
      : '';
    return `
      <div class="device-card" onclick="navigate('device', {currentDevice:'${escAttr(d.id)}'})">
        <div class="owner">${esc(d.owner)}</div>
        <div class="name">${esc(d.name || d.id)}</div>
        <div class="type">${esc(d.type)} · <span class="source-badge ${d.source}">${d.source}</span>${extractionBadges ? ' · ' + extractionBadges : ''} · ${fmt(d.total_records)} records</div>
        <div class="cat-tags">
          ${cats.map(([k,v]) => `<span class="cat-tag">${shortenCat(k)}<span class="count">${fmt(v)}</span></span>`).join('')}
        </div>
      </div>
    `;
  }).join('');
}

// --- Device Detail (UX Overhaul) ---
const CAT_ICONS = {
  chats: '💬', calls: '📞', contacts: '👥', emails: '📧',
  locations: '📍', searches: '🔍', browsing: '🌐', passwords: '🔑',
  notes: '📝', voicemails: '📞', __media__: '📁'
};

async function renderDevice(el) {
  const id = state.currentDevice;
  const dev = state.devices.find(d => d.id === id);
  if (!dev) { navigate('dashboard'); return; }

  const cats = Object.entries(dev.categories || {}).filter(([,v]) => v > 0);
  if (!deviceState.cat && cats.length) deviceState.cat = cats[0][0];

  // Summary card
  const catMap = dev.categories || {};
  const summaryItems = [
    catMap.chats ? `💬 ${fmt(catMap.chats)} messages` : '',
    catMap.calls ? `📞 ${fmt(catMap.calls)} calls` : '',
    catMap.contacts ? `👥 ${fmt(catMap.contacts)} contacts` : '',
    catMap.emails ? `📧 ${fmt(catMap.emails)} emails` : '',
    catMap.locations ? `📍 ${fmt(catMap.locations)} locations` : '',
    catMap.searches ? `🔍 ${fmt(catMap.searches)} searches` : '',
    catMap.browsing ? `🌐 ${fmt(catMap.browsing)} browsing` : '',
    catMap.passwords ? `🔑 ${fmt(catMap.passwords)} passwords` : '',
    catMap.notes ? `📝 ${fmt(catMap.notes)} notes` : '',
    catMap.voicemails ? `📞 ${fmt(catMap.voicemails)} voicemails` : '',
  ].filter(Boolean);

  el.innerHTML = `
    <button class="back-btn" onclick="navigate('dashboard')">← Back to devices</button>

    <div class="summary-card">
      <div class="summary-top">
        <span class="summary-icon">📱</span>
        <div>
          <div class="summary-name">${esc(dev.owner)}</div>
          <div class="summary-device">${esc(dev.name || dev.id)} · <span class="source-badge ${dev.source}">${dev.source}</span>${(dev.extractions||[]).length > 1 ? ' · ' + (dev.extractions||[]).map(e => {
            const cls = (e.suffix||'').toLowerCase().includes('taint') ? 'taint' : (e.suffix||'').toLowerCase().includes('priv') ? 'nonpriv' : 'primary';
            return `<span class="extraction-badge ${cls}">${esc(e.suffix||'Primary')}</span>`;
          }).join(' ') : ''}</div>
        </div>
      </div>
      <div class="summary-stats">${summaryItems.join(' <span class="summary-sep">|</span> ')}</div>
    </div>

    <div class="date-filter-bar">
      <label>📅 From</label>
      <input type="date" id="date-from" value="${deviceState.dateFrom}" onchange="deviceState.dateFrom=this.value;deviceState.page=1;loadDeviceData()">
      <label>To</label>
      <input type="date" id="date-to" value="${deviceState.dateTo}" onchange="deviceState.dateTo=this.value;deviceState.page=1;loadDeviceData()">
      <button class="date-quick" onclick="setDateRange('2021-06-01','2021-08-31')">Critical Period (Jun-Aug 2021)</button>
      <button class="date-quick" onclick="setDateRange('','')">All Time</button>
    </div>

    <div class="device-tabs" id="device-tabs">
      ${cats.map(([k,v]) => `<button data-cat="${escAttr(k)}" class="${k === deviceState.cat ? 'active' : ''}" onclick="switchTab('${escAttr(k)}')">${CAT_ICONS[k] || '📂'} ${shortenCat(k)}<span class="tab-badge">${fmt(v)}</span></button>`).join('')}
      <button data-cat="__media__" class="${deviceState.cat === '__media__' ? 'active' : ''}" onclick="switchTab('__media__')">📁 Media</button>
    </div>

    <div class="tab-filter-bar">
      <input type="text" id="device-search" placeholder="Filter ${shortenCat(deviceState.cat || '')}..." value="${esc(deviceState.query)}" onkeydown="if(event.key==='Enter'){deviceState.query=this.value;deviceState.page=1;loadDeviceData()}">
      <button onclick="deviceState.query=document.getElementById('device-search').value;deviceState.page=1;loadDeviceData()">Filter</button>
    </div>

    ${deviceState.cat === 'contacts' ? renderAlphaBar() : ''}

    <div id="device-pagination-top"></div>
    <div id="device-data"><div class="loading">Loading</div></div>
    <div id="device-pagination-bottom"></div>
  `;
  loadDeviceData();
}

function switchTab(cat) {
  deviceState.cat = cat;
  deviceState.page = 1;
  deviceState.query = '';
  // Update tab highlight
  document.querySelectorAll('.device-tabs button').forEach(b => {
    b.classList.toggle('active', b.dataset.cat === cat);
  });
  // Update filter placeholder
  const searchEl = document.getElementById('device-search');
  if (searchEl) { searchEl.value = ''; searchEl.placeholder = `Filter ${shortenCat(cat)}...`; }
  // Show/hide alpha bar
  const alphaBar = document.getElementById('alpha-bar');
  if (alphaBar) alphaBar.style.display = cat === 'contacts' ? 'flex' : 'none';
  loadDeviceData();
}

function setDateRange(from, to) {
  deviceState.dateFrom = from;
  deviceState.dateTo = to;
  deviceState.page = 1;
  const df = document.getElementById('date-from');
  const dt = document.getElementById('date-to');
  if (df) df.value = from;
  if (dt) dt.value = to;
  loadDeviceData();
}

function renderAlphaBar() {
  const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');
  return `<div class="alpha-bar" id="alpha-bar">${letters.map(l => `<button onclick="deviceState.query='${l}';deviceState.page=1;document.getElementById('device-search').value='${l}';loadDeviceData()">${l}</button>`).join('')}<button onclick="deviceState.query='';deviceState.page=1;document.getElementById('device-search').value='';loadDeviceData()">All</button></div>`;
}

async function loadDeviceData() {
  const el = document.getElementById('device-data');
  const cat = deviceState.cat;
  if (!cat) { el.innerHTML = '<div class="empty"><div class="icon">📂</div>No data categories</div>'; return; }

  if (cat === '__media__') { loadMediaData(); return; }

  el.innerHTML = '<div class="loading">Loading</div>';

  // For chats, load threads view
  if (cat === 'chats') {
    await loadChatThreads();
    return;
  }

  const params = new URLSearchParams({
    category: cat,
    page: deviceState.page,
    per_page: 50,
  });
  if (deviceState.query) params.set('q', deviceState.query);
  if (deviceState.dateFrom) params.set('date_from', deviceState.dateFrom);
  if (deviceState.dateTo) params.set('date_to', deviceState.dateTo);

  const data = await api(`/api/device/${encodeURIComponent(state.currentDevice)}?${params}`);

  if (!data.records || !data.records.length) {
    el.innerHTML = '<div class="empty"><div class="icon">📭</div>No records found</div>';
    clearPagination();
    return;
  }

  const dev = state.devices.find(d => d.id === state.currentDevice);
  if (dev?.source === 'cellebrite') {
    el.innerHTML = renderCellebriteData(cat, data.records);
  } else {
    el.innerHTML = renderAxiomData(cat, data.records);
  }

  renderPagination(data.total, data.page, data.per_page);
}

async function loadChatThreads() {
  const el = document.getElementById('device-data');
  const params = new URLSearchParams({
    page: deviceState.page,
    per_page: 50,
  });
  if (deviceState.query) params.set('search', deviceState.query);
  if (deviceState.dateFrom) params.set('date_from', deviceState.dateFrom);
  if (deviceState.dateTo) params.set('date_to', deviceState.dateTo);

  const data = await api(`/api/device/${encodeURIComponent(state.currentDevice)}/chat-threads?${params}`);

  if (!data.threads || !data.threads.length) {
    el.innerHTML = '<div class="empty"><div class="icon">📭</div>No chat threads found</div>';
    clearPagination();
    return;
  }

  el.innerHTML = `<div class="thread-list">${data.threads.map(t => `
    <div class="thread-row" id="thread-${t.thread_id}">
      <div class="thread-header" onclick="toggleThread(${t.thread_id})">
        <span class="thread-expand">▶</span>
        <div class="thread-info">
          <span class="thread-source">${esc(t.source)}</span>
          <span class="thread-participants">${esc(t.participants.join(', ') || 'Unknown')}</span>
          <span class="thread-count">${fmt(t.message_count)} msgs</span>
        </div>
        <div class="thread-dates">
          <span>${formatTs(t.first_date)}</span> → <span>${formatTs(t.last_date)}</span>
        </div>
        <div class="thread-preview">${esc(t.last_message_preview)}</div>
      </div>
      <div class="thread-messages" id="thread-msgs-${t.thread_id}" style="display:none"></div>
    </div>
  `).join('')}</div>`;

  renderPagination(data.total, data.page, data.per_page);
}

async function toggleThread(threadId) {
  const row = document.getElementById(`thread-${threadId}`);
  const msgsEl = document.getElementById(`thread-msgs-${threadId}`);
  const expand = row.querySelector('.thread-expand');

  if (msgsEl.style.display === 'none') {
    msgsEl.style.display = 'block';
    expand.textContent = '▼';
    if (!msgsEl.dataset.loaded) {
      msgsEl.innerHTML = '<div class="loading" style="padding:12px">Loading messages</div>';
      const data = await api(`/api/device/${encodeURIComponent(state.currentDevice)}/chat-thread/${threadId}`);
      msgsEl.dataset.loaded = '1';
      msgsEl.innerHTML = (data.messages || []).map(m => `
        <div class="chat-message">
          <span class="chat-sender">${esc(m.sender || '?')}</span>
          <span class="chat-time">${formatTs(m.timestamp)}</span>
          <div class="chat-body">${esc(m.body || '')}</div>
        </div>
      `).join('');
    }
  } else {
    msgsEl.style.display = 'none';
    expand.textContent = '▶';
  }
}

function renderPagination(total, page, perPage, mode) {
  const totalPages = Math.ceil(total / perPage);
  const html = buildPaginationHtml(total, page, perPage, totalPages, mode);
  document.getElementById('device-pagination-top').innerHTML = html;
  document.getElementById('device-pagination-bottom').innerHTML = html;
}

function clearPagination() {
  document.getElementById('device-pagination-top').innerHTML = '';
  document.getElementById('device-pagination-bottom').innerHTML = '';
}

function buildPaginationHtml(total, page, perPage, totalPages, mode) {
  if (totalPages <= 1) return `<div class="pagination"><span class="page-info">${fmt(total)} records</span></div>`;
  const start = (page - 1) * perPage + 1;
  const end = Math.min(page * perPage, total);

  const stateKey = mode === 'media' ? 'mediaPage' : 'page';
  const loadFn = mode === 'media' ? 'loadMediaData' : 'loadDeviceData';

  // Build page buttons
  let pages = [];
  const addPage = (p) => { if (!pages.includes(p) && p >= 1 && p <= totalPages) pages.push(p); };
  addPage(1);
  for (let i = Math.max(2, page - 2); i <= Math.min(totalPages - 1, page + 2); i++) addPage(i);
  addPage(totalPages);
  pages.sort((a, b) => a - b);

  let buttons = '';
  let last = 0;
  for (const p of pages) {
    if (last && p - last > 1) buttons += '<span class="page-ellipsis">…</span>';
    buttons += `<button class="page-btn ${p === page ? 'active' : ''}" onclick="deviceState.${stateKey}=${p};${loadFn}()">${p}</button>`;
    last = p;
  }

  return `
    <div class="pagination">
      <button class="page-nav" ${page <= 1 ? 'disabled' : ''} onclick="deviceState.${stateKey}=${page-1};${loadFn}()">«</button>
      ${buttons}
      <button class="page-nav" ${page >= totalPages ? 'disabled' : ''} onclick="deviceState.${stateKey}=${page+1};${loadFn}()">»</button>
      <span class="page-info">Showing ${fmt(start)}-${fmt(end)} of ${fmt(total)}</span>
    </div>
  `;
}

function goToPage(p) {
  deviceState.page = p;
  loadDeviceData();
}

// --- Cellebrite renderers ---
function renderCellebriteData(cat, records) {
  const renderers = { calls: renderCalls, contacts: renderContacts, emails: renderEmails, browsing: renderBrowsing, searches: renderSearches, locations: renderLocations, passwords: renderPasswords };
  return (renderers[cat] || renderGenericTable)(records);
}

function renderCalls(records) {
  return `<table class="data-table"><thead><tr><th>Time</th><th>Direction</th><th>Status</th><th>Duration</th><th>Details</th></tr></thead><tbody>
    ${records.map(r => `<tr>
      <td class="ts">${formatTs(r.timestamp)}</td>
      <td class="direction-${r.direction?.toLowerCase() === 'incoming' ? 'in' : r.status?.toLowerCase().includes('miss') ? 'missed' : 'out'}">${esc(r.direction)}</td>
      <td>${esc(r.status)}</td><td>${esc(r.duration)}</td><td>${esc(r.details || '')}</td>
    </tr>`).join('')}
  </tbody></table>`;
}

function renderContacts(records) {
  return `<table class="data-table"><thead><tr><th>Name</th><th>Source</th></tr></thead><tbody>
    ${records.map(r => `<tr><td>${esc(r.name)}</td><td>${esc(r.source)}</td></tr>`).join('')}
  </tbody></table>`;
}

function renderEmails(records) {
  return `<table class="data-table"><thead><tr><th>Time</th><th>Subject</th><th>From</th><th>To</th><th>Preview</th></tr></thead><tbody>
    ${records.map(r => `<tr>
      <td class="ts">${formatTs(r.timestamp)}</td>
      <td style="font-weight:600">${esc(r.subject)}</td>
      <td>${esc(r.from)}</td><td>${esc(r.to)}</td>
      <td style="max-width:300px">${esc((r.preview || '').slice(0, 100))}</td>
    </tr>`).join('')}
  </tbody></table>`;
}

function renderBrowsing(records) {
  return `<table class="data-table"><thead><tr><th>Time</th><th>Title</th><th>Browser</th></tr></thead><tbody>
    ${records.map(r => `<tr>
      <td class="ts">${formatTs(r.timestamp)}</td>
      <td><a href="${esc(r.url || '#')}" target="_blank" rel="noopener">${esc((r.title || r.url || '').slice(0, 80))}</a></td>
      <td>${esc(r.browser || '')}</td>
    </tr>`).join('')}
  </tbody></table>`;
}

function renderSearches(records) {
  return `<table class="data-table"><thead><tr><th>Time</th><th>Query</th><th>Source</th></tr></thead><tbody>
    ${records.map(r => `<tr>
      <td class="ts">${formatTs(r.timestamp)}</td>
      <td style="font-weight:600">${esc(r.query || '')}</td>
      <td>${esc(r.source || '')}</td>
    </tr>`).join('')}
  </tbody></table>`;
}

function renderLocations(records) {
  return `<table class="data-table"><thead><tr><th>Time</th><th>Address</th><th>Coords</th><th>Source</th></tr></thead><tbody>
    ${records.map(r => `<tr>
      <td class="ts">${formatTs(r.timestamp)}</td><td>${esc(r.address || '')}</td>
      <td>${esc(r.coords || '')}</td><td>${esc(r.source || '')}</td>
    </tr>`).join('')}
  </tbody></table>`;
}

function renderPasswords(records) {
  return `<table class="data-table"><thead><tr><th>Content</th></tr></thead><tbody>
    ${records.map(r => `<tr><td>${esc(r.content || r.service || '')}</td></tr>`).join('')}
  </tbody></table>`;
}

function renderAxiomData(cat, records) {
  if (!records.length) return '<div class="empty">No data</div>';
  const keys = [...new Set(records.flatMap(r => Object.keys(r)))].filter(k => !k.startsWith('_')).slice(0, 10);
  return `<table class="data-table"><thead><tr>
    ${keys.map(k => `<th>${esc(k)}</th>`).join('')}
  </tr></thead><tbody>
    ${records.map(r => `<tr>${keys.map(k => `<td>${esc(String(r[k] ?? '').slice(0, 200))}</td>`).join('')}</tr>`).join('')}
  </tbody></table>`;
}

function renderGenericTable(records) { return renderAxiomData('', records); }

// --- Search View ---
async function renderSearch(el) {
  const q = state.searchQuery || '';
  el.innerHTML = `
    <h2 style="margin-bottom:16px">Search Evidence</h2>
    <div class="filter-bar">
      <input type="text" id="global-search" placeholder="Search across all devices..." value="${esc(q)}" style="flex:1;max-width:600px" onkeydown="if(event.key==='Enter')doSearch()">
      <button onclick="doSearch()" style="padding:6px 16px;background:var(--accent);color:#000;border:none;border-radius:6px;cursor:pointer;font-weight:600">Search</button>
      <button onclick="doRagSearch()" style="padding:6px 16px;background:var(--purple);color:#000;border:none;border-radius:6px;cursor:pointer;font-weight:600" title="Semantic search using RAG embeddings">🧠 Semantic</button>
    </div>
    <div id="search-results">${q ? '<div class="loading">Searching</div>' : '<div class="empty"><div class="icon">🔍</div>Enter a search query to find evidence across all devices</div>'}</div>
  `;
  if (q) doSearch();
}

async function doSearch() {
  const q = document.getElementById('global-search').value.trim();
  if (!q) return;
  state.searchQuery = q;
  const el = document.getElementById('search-results');
  el.innerHTML = '<div class="loading">Searching</div>';
  const data = await api(`/api/search?q=${encodeURIComponent(q)}&per_page=100`);
  if (!data.results?.length) {
    el.innerHTML = '<div class="empty"><div class="icon">📭</div>No results found</div>';
    return;
  }
  el.innerHTML = `
    <div style="color:var(--text2);margin-bottom:12px">${fmt(data.total)} results found</div>
    <div class="search-results">
      ${data.results.map(r => {
        const body = highlightMatch(JSON.stringify(r.record, null, 0).slice(0, 300), q);
        return `
          <div class="result" onclick="navigate('device',{currentDevice:'${escAttr(r.device_id)}',_cat:'${escAttr(r.category)}'})">
            <div class="result-meta">
              <span>📱 ${esc(r.device_name)}</span><span>👤 ${esc(r.owner)}</span>
              <span>📂 ${esc(r.category)}</span><span class="source-badge ${r.source}">${r.source}</span>
            </div>
            <div class="result-body">${body}</div>
          </div>`;
      }).join('')}
    </div>
    ${data.total > 100 ? `<div class="pagination"><span class="page-info">Showing first 100 of ${fmt(data.total)}</span></div>` : ''}
  `;
}

async function doRagSearch() {
  const q = document.getElementById('global-search').value.trim();
  if (!q) return;
  const el = document.getElementById('search-results');
  el.innerHTML = '<div class="loading">Running semantic search (may take a few seconds)</div>';
  const data = await api(`/api/rag-search?q=${encodeURIComponent(q)}`);
  if (data.error) {
    el.innerHTML = `<div class="empty"><div class="icon">⚠️</div>${esc(data.error)}</div>`;
    return;
  }
  const results = data.results || [];
  if (!results.length) {
    el.innerHTML = '<div class="empty"><div class="icon">📭</div>No semantic results</div>';
    return;
  }
  el.innerHTML = `
    <div style="color:var(--text2);margin-bottom:12px">🧠 Semantic search: ${results.length} results ${data.stats ? `(${data.stats.total_time}s)` : ''}</div>
    <div class="search-results">
      ${results.map(r => `
        <div class="result">
          <div class="result-meta">
            <span>📄 ${esc(r.filename || r.source || '')}</span>
            ${r.score ? `<span>Score: ${(r.score * 100).toFixed(1)}%</span>` : ''}
          </div>
          <div class="result-body">${esc((r.content || '').slice(0, 400))}</div>
        </div>
      `).join('')}
    </div>
  `;
}

// --- Chat with AI ---
function toggleChat() {
  const panel = document.getElementById('chat-panel');
  const toggle = document.getElementById('chat-toggle');
  panel.classList.toggle('open');
  toggle.classList.toggle('active');
  if (panel.classList.contains('open')) document.getElementById('chat-input').focus();
}

function getDeviceScope() {
  return (state.view === 'device' && state.currentDevice) ? state.currentDevice : null;
}

async function sendChat() {
  if (chatBusy) return;
  const input = document.getElementById('chat-input');
  const question = input.value.trim();
  if (!question) return;
  input.value = '';
  chatBusy = true;
  document.getElementById('chat-send').disabled = true;
  const model = document.getElementById('chat-model').value;
  const scope = getDeviceScope();
  chatHistory.push({ role: 'user', content: question });
  renderChatMessages();
  const loadingId = 'loading-' + Date.now();
  const messagesEl = document.getElementById('chat-messages');
  const loadingEl = document.createElement('div');
  loadingEl.id = loadingId;
  loadingEl.className = 'chat-loading';
  loadingEl.innerHTML = `<span>🔍 Searching evidence & generating response</span><span class="dots"></span>`;
  messagesEl.appendChild(loadingEl);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  try {
    const response = await api('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, model, top_k: 10, device_scope: scope })
    });
    document.getElementById(loadingId)?.remove();
    chatHistory.push({ role: 'assistant', content: response.answer, sources: response.sources, model: response.model, stats: response.stats });
    renderChatMessages();
  } catch (err) {
    document.getElementById(loadingId)?.remove();
    chatHistory.push({ role: 'assistant', content: `Error: ${err.message}`, sources: [] });
    renderChatMessages();
  }
  chatBusy = false;
  document.getElementById('chat-send').disabled = false;
}

function renderChatMessages() {
  const el = document.getElementById('chat-messages');
  const scope = getDeviceScope();
  el.innerHTML = `
    <div class="chat-msg system">Ask questions about the forensic evidence. ${scope ? `<span class="chat-scope-badge">Scoped to: ${esc(scope)}</span>` : ''}</div>
    ${chatHistory.map(msg => {
      if (msg.role === 'user') return `<div class="chat-msg user">${esc(msg.content)}</div>`;
      const sourcesHtml = msg.sources?.length ? `
        <div class="chat-sources"><details>
          <summary>📎 ${msg.sources.length} sources ${msg.stats?.total_time ? `(${msg.stats.total_time}s)` : ''}</summary>
          ${msg.sources.map(s => `<div class="source-item"><span class="score">${(s.score*100).toFixed(0)}%</span><span class="file">${esc(s.file||s.source||'')}</span><span class="snippet">${esc(s.snippet||'')}</span></div>`).join('')}
        </details></div>` : '';
      return `<div class="chat-msg assistant"><div class="answer">${formatAnswer(msg.content)}</div>${msg.model?`<span class="chat-model-badge">${esc(msg.model)}</span>`:''}${sourcesHtml}</div>`;
    }).join('')}`;
  el.scrollTop = el.scrollHeight;
}

function formatAnswer(text) {
  return esc(text).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
}

// --- Media Tab ---
async function loadMediaData() {
  const el = document.getElementById('device-data');
  el.innerHTML = '<div class="loading">Scanning media files</div>';
  const typeFilter = document.getElementById('media-type-filter')?.value || 'all';
  const page = deviceState.mediaPage || 1;
  try {
    const data = await api(`/api/media/list/${encodeURIComponent(state.currentDevice)}?media_type=${typeFilter}&page=${page}&per_page=50`);
    if (!data.files?.length) {
      el.innerHTML = '<div class="empty"><div class="icon">📂</div>No media files found</div>';
      clearPagination();
      return;
    }
    const counts = data.counts || {};
    el.innerHTML = `
      <div class="media-stats">
        <span>🖼️ ${fmt(counts.image||0)} images</span><span>🎵 ${fmt(counts.audio||0)} audio</span><span>🎬 ${fmt(counts.video||0)} video</span>
      </div>
      <div style="margin-bottom:12px"><select id="media-type-filter" onchange="deviceState.mediaPage=1;loadMediaData()">
        <option value="all" ${typeFilter==='all'?'selected':''}>All Media</option>
        <option value="image" ${typeFilter==='image'?'selected':''}>🖼️ Images</option>
        <option value="audio" ${typeFilter==='audio'?'selected':''}>🎵 Audio</option>
        <option value="video" ${typeFilter==='video'?'selected':''}>🎬 Video</option>
      </select></div>
      <div class="media-grid">${data.files.map(f => renderMediaItem(f)).join('')}</div>`;
    renderPagination(data.total, page, data.per_page, 'media');
  } catch (err) {
    el.innerHTML = `<div class="empty"><div class="icon">⚠️</div>Error: ${esc(err.message)}</div>`;
  }
}

function renderMediaItem(f) {
  const tk = localStorage.getItem('auth_token') || '';
  const mediaUrl = '/api/media/' + f.path.split('/').map(encodeURIComponent).join('/') + '?token=' + encodeURIComponent(tk);
  if (f.type === 'image') return `<div class="media-item media-image" onclick="openLightbox('${escAttr(mediaUrl)}','${escAttr(f.name)}')"><img src="${esc(mediaUrl)}" loading="lazy" alt="${esc(f.name)}" onerror="this.parentElement.classList.add('broken')"><div class="media-label">${esc(f.name)}<br><span>${f.size_human}</span></div></div>`;
  if (f.type === 'audio') return `<div class="media-item media-audio"><div class="media-label">🎵 ${esc(f.name)} <span>${f.size_human}</span></div><audio controls preload="none" src="${esc(mediaUrl)}" style="width:100%;margin-top:6px"></audio></div>`;
  if (f.type === 'video') return `<div class="media-item media-video" onclick="openVideoModal('${escAttr(mediaUrl)}','${escAttr(f.name)}')"><div class="video-play-icon">▶</div><div class="media-label">🎬 ${esc(f.name)}<br><span>${f.size_human}</span></div></div>`;
  return '';
}

// --- Lightbox ---
function openLightbox(src, name) {
  let lb = document.getElementById('lightbox-overlay');
  if (!lb) {
    lb = document.createElement('div'); lb.id = 'lightbox-overlay'; lb.className = 'lightbox-overlay';
    lb.onclick = e => { if (e.target === lb) closeLightbox(); };
    lb.innerHTML = `<div class="lb-inner"><button class="lb-close" onclick="closeLightbox()">✕</button><img id="lb-image" src=""><div class="lb-caption" id="lb-caption"></div></div>`;
    document.body.appendChild(lb);
  }
  document.getElementById('lb-image').src = src;
  document.getElementById('lb-caption').textContent = name;
  lb.classList.add('open');
  document.body.style.overflow = 'hidden';
}
function closeLightbox() { const lb = document.getElementById('lightbox-overlay'); if (lb) { lb.classList.remove('open'); document.body.style.overflow = ''; } }

function openVideoModal(src, name) {
  let vm = document.getElementById('video-modal-overlay');
  if (!vm) {
    vm = document.createElement('div'); vm.id = 'video-modal-overlay'; vm.className = 'lightbox-overlay';
    vm.onclick = e => { if (e.target === vm) closeVideoModal(); };
    vm.innerHTML = `<div class="lb-inner"><button class="lb-close" onclick="closeVideoModal()">✕</button><video id="vm-video" controls autoplay style="max-width:90vw;max-height:80vh;border-radius:8px"></video><div class="lb-caption" id="vm-caption"></div></div>`;
    document.body.appendChild(vm);
  }
  document.getElementById('vm-video').src = src;
  document.getElementById('vm-caption').textContent = name;
  vm.classList.add('open');
  document.body.style.overflow = 'hidden';
}
function closeVideoModal() { const vm = document.getElementById('video-modal-overlay'); if (vm) { vm.classList.remove('open'); const v = document.getElementById('vm-video'); v.pause(); v.src = ''; document.body.style.overflow = ''; } }
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeLightbox(); closeVideoModal(); } });

// --- Discoveries ---
let _discCache = null;
let _discCatCounts = null;

async function renderDiscoveries(el) {
  el.innerHTML = '<div class="loading">Analyzing evidence for discoveries</div>';
  if (!_discCache) {
    const data = await api('/api/discoveries?per_page=2000');
    _discCache = data.discoveries || [];
    _discCatCounts = data.category_counts || {};
  }
  const owners = [...new Set(_discCache.map(d => d.owner))].filter(Boolean).sort();
  const catEntries = Object.entries(_discCatCounts).sort((a, b) => b[1] - a[1]);
  el.innerHTML = `
    <div class="disc-header"><h2>🔥 Discoveries</h2><span class="disc-total">${fmt(_discCache.length)} findings</span></div>
    <div class="disc-filters">
      <span class="filter-pill active" data-cat="all" onclick="setDiscFilter(this,'cat')">All <span class="pill-count">${fmt(_discCache.length)}</span></span>
      ${catEntries.map(([c, n]) => `<span class="filter-pill" data-cat="${escAttr(c)}" onclick="setDiscFilter(this,'cat')">${esc(c)} <span class="pill-count">${fmt(n)}</span></span>`).join('')}
    </div>
    <div class="filter-bar" style="margin-bottom:12px">
      <select id="disc-person" onchange="filterDiscoveries()"><option value="all">All People</option>${owners.map(o => `<option value="${escAttr(o)}">${esc(o)}</option>`).join('')}</select>
      <select id="disc-sort" onchange="filterDiscoveries()"><option value="importance">Sort: Importance</option><option value="date">Sort: Newest First</option><option value="date_asc">Sort: Oldest First</option></select>
      <select id="disc-flames" onchange="filterDiscoveries()"><option value="0">All Importance</option><option value="3">🔥🔥🔥 Critical Only</option><option value="2">🔥🔥+ Important</option></select>
    </div>
    <div id="disc-grid" class="disc-grid"></div>`;
  filterDiscoveries();
}

function setDiscFilter(pill) {
  pill.parentElement.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
  pill.classList.add('active');
  filterDiscoveries();
}

function filterDiscoveries() {
  const activePill = document.querySelector('.disc-filters .filter-pill.active');
  const cat = activePill?.dataset.cat || 'all';
  const person = document.getElementById('disc-person')?.value || 'all';
  const sortBy = document.getElementById('disc-sort')?.value || 'importance';
  const minFlames = parseInt(document.getElementById('disc-flames')?.value || '0');
  const grid = document.getElementById('disc-grid');
  if (!grid) return;
  let filtered = [...(_discCache || [])];
  if (cat !== 'all') filtered = filtered.filter(d => d.category === cat);
  if (person !== 'all') filtered = filtered.filter(d => d.owner === person);
  if (minFlames > 0) filtered = filtered.filter(d => d.flames >= minFlames);
  if (sortBy === 'importance') filtered.sort((a, b) => b.flames !== a.flames ? b.flames - a.flames : (b.timestamp || '').localeCompare(a.timestamp || ''));
  else if (sortBy === 'date') filtered.sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''));
  else filtered.sort((a, b) => (a.timestamp || 'z').localeCompare(b.timestamp || 'z'));
  const shown = filtered.slice(0, 500);
  if (!shown.length) { grid.innerHTML = '<div class="empty"><div class="icon">🔍</div>No discoveries match filters</div>'; return; }
  grid.innerHTML = shown.map((d, i) => `
    <div class="disc-card flames-${d.flames} ${d.verified ? 'verified' : ''}">
      <div class="disc-top">
        <span class="disc-flames">${'🔥'.repeat(d.flames)}</span>
        <span class="disc-title">${esc(d.title)}</span>
        ${d.verified ? '<span class="disc-verified">✓ Verified</span>' : ''}
      </div>
      <div class="disc-meta">
        <span>📂 ${esc(d.category)}</span><span>👤 ${esc(d.owner)}</span>
        ${d.timestamp ? `<span>🕐 ${formatTs(d.timestamp)}</span>` : ''}
      </div>
      <div class="disc-content" id="disc-content-${i}">${esc(d.content)}</div>
      ${d.content && d.content.length > 200 ? `<button class="disc-expand" onclick="event.stopPropagation();toggleDiscContent(${i})">Show more ▾</button>` : ''}
      <div class="disc-tags">${(d.tags || []).map(t => `<span class="disc-tag">${esc(t)}</span>`).join('')}</div>
      <div class="disc-actions">
        ${d.device_id ? `<button onclick="event.stopPropagation();navigate('device',{currentDevice:'${escAttr(d.device_id)}',_cat:'${escAttr(d.data_type || '')}'})">📱 View Device</button>` : ''}
        <button onclick="event.stopPropagation();askChatAbout('${escAttr(d.title)}')">🧠 Ask AI</button>
      </div>
    </div>
  `).join('') + (filtered.length > 500 ? `<div class="pagination"><span class="page-info">Showing first 500 of ${fmt(filtered.length)}</span></div>` : '');
}

function toggleDiscContent(i) {
  const el = document.getElementById('disc-content-' + i);
  if (el) { el.classList.toggle('expanded'); const btn = el.nextElementSibling; if (btn?.classList.contains('disc-expand')) btn.textContent = el.classList.contains('expanded') ? 'Show less ▴' : 'Show more ▾'; }
}

async function doRefresh(btn) {
  btn.disabled = true;
  btn.textContent = '⏳ Refreshing...';
  const statusEl = document.getElementById('refresh-status');
  try {
    const r = await api('/api/refresh', { method: 'POST' });
    if (r.changed > 0) {
      statusEl.textContent = `✅ Re-indexed ${r.changed} files in ${r.time}s`;
      state.devices = []; state.stats = {}; _discCache = null;
    } else {
      statusEl.textContent = '✅ No changes detected';
    }
  } catch (e) { statusEl.textContent = '❌ Error: ' + e.message; }
  btn.disabled = false;
  btn.textContent = '🔄 Refresh Index';
}

function askChatAbout(title) {
  const panel = document.getElementById('chat-panel');
  if (!panel.classList.contains('open')) toggleChat();
  const input = document.getElementById('chat-input');
  input.value = `Tell me more about: ${title}`;
  input.focus();
}

// --- Helpers ---
function fmt(n) { return Number(n || 0).toLocaleString(); }
function esc(s) { if (s == null) return ''; const d = document.createElement('div'); d.textContent = String(s); return d.innerHTML; }
function escAttr(s) { return String(s || '').replace(/'/g, "\\'").replace(/"/g, '&quot;'); }
function formatTs(ts) {
  if (!ts) return '';
  try { return new Date(ts).toLocaleString('en-US', { dateStyle: 'short', timeStyle: 'short' }); } catch { return ts; }
}
function shortenCat(name) {
  return name.replace(/[_-]/g, ' ').split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ').slice(0, 30);
}
function highlightMatch(text, query) {
  const escaped = esc(text);
  const re = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
  return escaped.replace(re, '<mark>$1</mark>');
}

// --- Init ---
function initApp() {
  document.querySelectorAll('#nav-buttons button').forEach(b => b.addEventListener('click', () => navigate(b.dataset.view)));
  document.getElementById('header-search')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { state.searchQuery = e.target.value; navigate('search'); }
  });
  // chat-toggle onclick is in HTML, don't double-bind
  api('/api/models').then(models => {
    const sel = document.getElementById('chat-model');
    if (sel && models.length) sel.innerHTML = models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
    else if (sel) sel.innerHTML = '<option value="deepseek-r1:70b">deepseek-r1:70b</option>';
  }).catch(() => {});
  render();
}

document.addEventListener('DOMContentLoaded', () => {
  checkAuth();
});

// ─── Mind Map / Network Graph ───
let networkInstance = null;
let networkData = null;

const EDGE_COLORS = {
  phone_call: '#4A90D9',
  text_message: '#27AE60',
  chat: '#27AE60',
  email: '#E67E22',
  shared_contact: '#8E44AD',
  signal_group: '#E74C3C',
};

const ROLE_COLORS = {
  defendant: '#E74C3C',
  associate: '#E67E22',
  colleague: '#3498DB',
  family: '#27AE60',
  contact: '#95A5A6',
  chat_contact: '#95A5A6',
};

async function renderMindMap(el) {
  el.innerHTML = `
    <div class="mindmap-container">
      <div class="mindmap-controls">
        <!-- Search -->
        <div class="control-group">
          <label>🔍 Search</label>
          <input type="text" id="mm-search" placeholder="Find person..." oninput="searchNetwork(this.value)" class="input-field">
        </div>

        <!-- Path Finder -->
        <div class="control-group">
          <label>🔗 Find Path</label>
          <div class="flex gap-2">
            <select id="mm-path-from" class="input-field text-sm">
              <option value="">From...</option>
            </select>
            <select id="mm-path-to" class="input-field text-sm">
              <option value="">To...</option>
            </select>
            <button onclick="findAndHighlightPath()" class="btn-sm">Find</button>
          </div>
        </div>

        <!-- Connection Strength -->
        <div class="control-group">
          <label>Min Connection Strength</label>
          <input type="range" id="mm-strength" min="1" max="50" value="1" oninput="updateMindMap()">
          <span id="mm-strength-val">1</span>
        </div>

        <!-- Edge Types -->
        <div class="control-group">
          <label>Edge Types</label>
          <label class="toggle"><input type="checkbox" checked data-edge="shared_contact" onchange="updateMindMap()"> 🟣 Shared Contacts</label>
          <label class="toggle"><input type="checkbox" checked data-edge="chat" onchange="updateMindMap()"> 🟢 Chats</label>
          <label class="toggle"><input type="checkbox" checked data-edge="phone_call" onchange="updateMindMap()"> 🔵 Calls</label>
          <label class="toggle"><input type="checkbox" checked data-edge="email" onchange="updateMindMap()"> 🟠 Emails</label>
          <label class="toggle"><input type="checkbox" checked data-edge="signal_group" onchange="updateMindMap()"> 🔴 Signal</label>
        </div>

        <!-- View Options -->
        <div class="control-group">
          <label class="toggle"><input type="checkbox" id="mm-secondary" checked onchange="updateMindMap()"> Show Secondary Nodes</label>
        </div>

        <!-- Analysis Tools -->
        <div class="control-group">
          <label>Analysis</label>
          <button onclick="showNetworkStats()" class="btn-sm">📊 Statistics</button>
          <button onclick="colorByCommunity()" class="btn-sm">🎨 Communities</button>
          <button onclick="exportNetwork()" class="btn-sm">💾 Export PNG</button>
        </div>

        <!-- View Controls -->
        <div class="control-group">
          <button onclick="networkInstance&&networkInstance.fit()" class="btn-sm">🔍 Fit View</button>
          <button onclick="networkInstance&&networkInstance.stabilize(100)" class="btn-sm">⚡ Stabilize</button>
          <button onclick="resetNetworkColors()" class="btn-sm">🔄 Reset Colors</button>
        </div>
      </div>
      <div class="mindmap-body">
        <div id="network-graph" style="width:100%;height:100%;"></div>
        <div class="mindmap-sidebar" id="mm-sidebar">
          <h3>🕸️ Network Graph</h3>
          <p class="text-sm text-gray-400">Click a node or edge for details.</p>
          <div id="mm-details"></div>
          <div id="mm-stats" style="display:none;"></div>
        </div>
      </div>
    </div>
  `;

  if (!networkData) {
    document.getElementById('network-graph').innerHTML = '<div class="loading">Building network graph...</div>';
    networkData = await api('/api/network');
  }
  buildGraph();
  populatePathSelectors();
}

function buildGraph() {
  const container = document.getElementById('network-graph');
  if (!container || !networkData) return;

  const minStrength = parseInt(document.getElementById('mm-strength')?.value || 1);
  const showSecondary = document.getElementById('mm-secondary')?.checked ?? true;
  const enabledEdgeTypes = new Set();
  document.querySelectorAll('[data-edge]').forEach(cb => {
    if (cb.checked) enabledEdgeTypes.add(cb.dataset.edge);
  });

  document.getElementById('mm-strength-val').textContent = minStrength;

  // Filter nodes and edges
  const filteredEdges = networkData.edges.filter(e => {
    if (e.weight < minStrength) return false;
    return e.types.some(t => enabledEdgeTypes.has(t.type));
  });

  const connectedNodeIds = new Set();
  filteredEdges.forEach(e => { connectedNodeIds.add(e.source); connectedNodeIds.add(e.target); });

  const filteredNodes = networkData.nodes.filter(n => {
    if (n.type === 'secondary' && !showSecondary) return false;
    if (n.type === 'primary') return true;
    return connectedNodeIds.has(n.id);
  });

  const nodeIds = new Set(filteredNodes.map(n => n.id));
  const visEdges = filteredEdges
    .filter(e => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map(e => {
      const mainType = e.types[0]?.type || 'shared_contact';
      return {
        from: e.source,
        to: e.target,
        value: Math.log2(e.weight + 1),
        color: { color: EDGE_COLORS[mainType] || '#95A5A6', opacity: 0.7 },
        title: e.types.map(t => `${t.type}: ${t.count || t.message_count || 0}`).join('\n'),
        _data: e,
      };
    });

  const maxWeight = Math.max(...filteredNodes.map(n => n.contact_count + n.message_count + n.call_count), 1);

  const visNodes = filteredNodes.map(n => {
    const totalWeight = n.contact_count + n.message_count + n.call_count;
    const size = n.type === 'primary' ? 25 + (totalWeight / maxWeight) * 35 : 8 + (totalWeight / maxWeight) * 15;
    return {
      id: n.id,
      label: n.name,
      size: size,
      color: {
        background: n.type === 'primary' ? ROLE_COLORS[n.role] || '#E67E22' : '#BDC3C7',
        border: n.type === 'primary' ? '#2C3E50' : '#95A5A6',
        highlight: { background: '#F39C12', border: '#E67E22' },
      },
      font: {
        size: n.type === 'primary' ? 14 : 10,
        color: '#ECF0F1',
        strokeWidth: 2,
        strokeColor: '#2C3E50',
      },
      shape: n.type === 'primary' ? 'dot' : 'dot',
      borderWidth: n.type === 'primary' ? 3 : 1,
      _data: n,
    };
  });

  const data = {
    nodes: new vis.DataSet(visNodes),
    edges: new vis.DataSet(visEdges),
  };

  const options = {
    physics: {
      solver: 'forceAtlas2Based',
      forceAtlas2Based: {
        gravitationalConstant: -80,
        centralGravity: 0.01,
        springLength: 150,
        springConstant: 0.04,
        damping: 0.4,
      },
      stabilization: { iterations: 150 },
    },
    interaction: {
      hover: true,
      tooltipDelay: 200,
      zoomView: true,
      dragView: true,
    },
    nodes: { shadow: true },
    edges: {
      smooth: { type: 'continuous' },
      scaling: { min: 1, max: 8 },
    },
  };

  if (networkInstance) networkInstance.destroy();
  networkInstance = new vis.Network(container, data, options);

  networkInstance.on('click', params => {
    if (params.nodes.length > 0) {
      const nodeId = params.nodes[0];
      showNodeDetails(nodeId);
    } else if (params.edges.length > 0) {
      const edgeId = params.edges[0];
      const edge = visEdges.find(e => `${e.from}-${e.to}` === edgeId || data.edges.get(edgeId));
      const edgeData = data.edges.get(edgeId);
      if (edgeData?._data) showEdgeDetails(edgeData._data);
    }
  });
}

function updateMindMap() {
  buildGraph();
}

async function showNodeDetails(nodeId) {
  const sidebar = document.getElementById('mm-details');
  if (!sidebar) return;
  sidebar.innerHTML = '<div class="loading">Loading...</div>';

  try {
    const details = await api(`/api/network/person/${nodeId}`);
    if (details.error) {
      sidebar.innerHTML = '<p>Person not found</p>';
      return;
    }
    const p = details.person;
    let html = `
      <h3 style="color:${ROLE_COLORS[p.role] || '#ccc'}">${esc(p.name)}</h3>
      <div class="mm-badge ${p.type}">${p.type} · ${p.role}</div>
      <div class="mm-stats">
        <div>📱 Devices: ${p.devices.length ? p.devices.map(esc).join(', ') : 'N/A'}</div>
        <div>👥 Contacts: ${p.contact_count}</div>
        <div>📞 Calls: ${p.call_count}</div>
        <div>💬 Messages: ${p.message_count}</div>
        <div>📧 Emails: ${p.email_count}</div>
        ${p.appears_on?.length ? `<div>📋 Appears on: ${p.appears_on.map(esc).join(', ')}</div>` : ''}
        ${p.case_file_count ? `<div>⚖️ Legal mentions: ${p.total_mentions} across ${p.case_file_count} files</div>` : ''}
      </div>
    `;

    // Case files section
    if (p.case_files && p.case_files.length > 0) {
      html += `<h4>📁 Case Files (${p.case_file_count})</h4><div class="mm-case-files">`;
      for (const cf of p.case_files.slice(0, 15)) {
        const caseLabel = cf.case || '';
        const pdfLink = cf.pdf_path ? `onclick="openLegalPdf('${esc(cf.pdf_path)}')"` : `onclick="openLegalTxt('${esc(cf.path)}')"`;
        html += `<div class="mm-case-file" ${pdfLink}>
          <div class="mm-cf-name">${esc(cf.filename)}</div>
          <div class="mm-cf-meta"><span class="mm-cf-case">${esc(caseLabel)}</span> · ${cf.mentions} mentions</div>
        </div>`;
      }
      if (p.case_file_count > 15) html += `<div class="mm-cf-more">+ ${p.case_file_count - 15} more files</div>`;
      html += '</div>';
    }

    html += `<h4>Connections (${details.total_connections})</h4>
      <div class="mm-connections">
    `;
    for (const conn of details.connections.slice(0, 20)) {
      const cp = conn.person;
      const types = conn.edge.types.map(t => t.type).join(', ');
      html += `<div class="mm-conn" onclick="showNodeDetails('${cp.id}')">
        <strong>${esc(cp.name)}</strong>
        <span class="mm-conn-weight">w:${conn.edge.weight}</span>
        <div class="mm-conn-types">${types}</div>
      </div>`;
    }
    html += '</div>';
    sidebar.innerHTML = html;
  } catch (e) {
    sidebar.innerHTML = '<p>Error loading details</p>';
  }
}

function openLegalPdf(path) {
  window.open(`/api/legal/pdf?path=${encodeURIComponent(path)}`, '_blank');
}

async function openLegalTxt(path) {
  try {
    const data = await api(`/api/legal/file?path=${encodeURIComponent(path)}`);
    if (data.error) { alert(data.error); return; }
    // Open in modal
    showLegalModal(path.split('/').pop(), data.content);
  } catch(e) { alert('Error loading file'); }
}

function showLegalModal(title, content) {
  let modal = document.getElementById('legal-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'legal-modal';
    modal.className = 'legal-modal-overlay';
    document.body.appendChild(modal);
  }
  modal.innerHTML = `
    <div class="legal-modal">
      <div class="legal-modal-header">
        <h3>${esc(title)}</h3>
        <button onclick="document.getElementById('legal-modal').style.display='none'" class="close-btn">✕</button>
      </div>
      <div class="legal-modal-body"><pre>${esc(content)}</pre></div>
    </div>
  `;
  modal.style.display = 'flex';
}

// ─── Legal Files View ───
let legalCases = null;

// Mind Map Enhanced Features - Insert into app.js before renderLegalFiles

// Populate path finder dropdowns
function populatePathSelectors() {
  if (!networkData) return;
  
  const primaryNodes = networkData.nodes
    .filter(n => n.type === 'primary')
    .sort((a, b) => a.name.localeCompare(b.name));
  
  const fromSelect = document.getElementById('mm-path-from');
  const toSelect = document.getElementById('mm-path-to');
  
  if (!fromSelect || !toSelect) return;
  
  const options = primaryNodes.map(n => 
    `<option value="${n.id}">${esc(n.name)}</option>`
  ).join('');
  
  fromSelect.innerHTML = '<option value="">From...</option>' + options;
  toSelect.innerHTML = '<option value="">To...</option>' + options;
}

// Search and highlight
function searchNetwork(query) {
  if (!networkInstance || !networkData) return;
  
  query = query.toLowerCase().trim();
  if (!query) {
    networkInstance.selectNodes([]);
    return;
  }

  const matches = networkData.nodes
    .filter(n => n.name.toLowerCase().includes(query))
    .map(n => n.id);
  
  if (matches.length > 0) {
    networkInstance.selectNodes(matches);
    networkInstance.focus(matches[0], { scale: 1.5, animation: { duration: 1000, easingFunction: 'easeInOutQuad' } });
  }
}

// Find shortest path (BFS)
function findPath(fromId, toId) {
  if (!networkData) return null;
  
  const graph = new Map();
  networkData.edges.forEach(e => {
    if (!graph.has(e.source)) graph.set(e.source, []);
    if (!graph.has(e.target)) graph.set(e.target, []);
    graph.get(e.source).push(e.target);
    graph.get(e.target).push(e.source);
  });

  const queue = [[fromId]];
  const visited = new Set([fromId]);

  while (queue.length > 0) {
    const path = queue.shift();
    const current = path[path.length - 1];

    if (current === toId) return path;

    const neighbors = graph.get(current) || [];
    for (const node of neighbors) {
      if (!visited.has(node)) {
        visited.add(node);
        queue.push([...path, node]);
      }
    }
  }

  return null;
}

// Highlight path
function findAndHighlightPath() {
  const fromId = document.getElementById('mm-path-from')?.value;
  const toId = document.getElementById('mm-path-to')?.value;
  
  if (!fromId || !toId) {
    alert('Please select both people');
    return;
  }

  const path = findPath(fromId, toId);
  
  if (!path) {
    alert('No path found between these people');
    return;
  }

  // Highlight nodes in path
  networkInstance.selectNodes(path);

  // Find and highlight edges in path
  const pathEdges = [];
  for (let i = 0; i < path.length - 1; i++) {
    const connectedEdges = networkInstance.getConnectedEdges(path[i]);
    for (const edgeId of connectedEdges) {
      const edge = networkInstance.body.data.edges.get(edgeId);
      if ((edge.from === path[i] && edge.to === path[i + 1]) ||
          (edge.to === path[i] && edge.from === path[i + 1])) {
        pathEdges.push(edgeId);
      }
    }
  }

  networkInstance.selectEdges(pathEdges);

  // Show path in sidebar
  const names = path.map(id => networkData.nodes.find(n => n.id === id)?.name || '?');
  document.getElementById('mm-details').innerHTML = `
    <h3>🔗 Path Found</h3>
    <div class="path-display">
      ${names.map((name, i) => `
        <div class="path-node">${esc(name)}</div>
        ${i < names.length - 1 ? '<div class="path-arrow">↓</div>' : ''}
      `).join('')}
    </div>
    <p class="text-sm text-gray-400 mt-3">Length: ${path.length - 1} hop${path.length !== 2 ? 's' : ''}</p>
  `;
}

// Detect communities
function detectCommunities() {
  if (!networkData) return {};

  const adj = new Map();
  networkData.nodes.forEach(n => adj.set(n.id, []));
  networkData.edges.forEach(e => {
    adj.get(e.source).push(e.target);
    adj.get(e.target).push(e.source);
  });

  const labels = new Map();
  networkData.nodes.forEach(n => labels.set(n.id, n.id));

  for (let iter = 0; iter < 10; iter++) {
    let changed = false;
    networkData.nodes.forEach(n => {
      const neighbors = adj.get(n.id);
      if (neighbors.length === 0) return;

      const labelCounts = new Map();
      neighbors.forEach(nbr => {
        const lbl = labels.get(nbr);
        labelCounts.set(lbl, (labelCounts.get(lbl) || 0) + 1);
      });

      const mostCommon = [...labelCounts.entries()]
        .sort((a, b) => b[1] - a[1])[0][0];

      if (labels.get(n.id) !== mostCommon) {
        labels.set(n.id, mostCommon);
        changed = true;
      }
    });

    if (!changed) break;
  }

  const communities = new Map();
  labels.forEach((community, nodeId) => {
    if (!communities.has(community)) communities.set(community, []);
    communities.get(community).push(nodeId);
  });

  return communities;
}

// Color by community
function colorByCommunity() {
  if (!networkInstance || !networkData) return;

  const communities = detectCommunities();
  const colors = [
    '#E74C3C', '#3498DB', '#2ECC71', '#F39C12', '#9B59B6',
    '#1ABC9C', '#E67E22', '#16A085', '#2980B9', '#8E44AD'
  ];

  let colorIdx = 0;
  const communityColors = new Map();
  const communityNames = new Map();
  
  communities.forEach((members, commId) => {
    communityColors.set(commId, colors[colorIdx % colors.length]);
    // Find the primary node in this community for naming
    const primaryInCommunity = members
      .map(id => networkData.nodes.find(n => n.id === id))
      .find(n => n?.type === 'primary');
    communityNames.set(commId, primaryInCommunity?.name || `Community ${colorIdx + 1}`);
    colorIdx++;
  });

  const updates = networkData.nodes.map(n => {
    const community = Array.from(communities.entries())
      .find(([_, members]) => members.includes(n.id))?.[0];
    const color = communityColors.get(community) || '#95A5A6';
    
    return {
      id: n.id,
      color: {
        background: color,
        border: '#2C3E50',
        highlight: { background: color, border: '#E67E22' }
      }
    };
  });

  networkInstance.body.data.nodes.update(updates);

  // Show communities in sidebar
  document.getElementById('mm-details').innerHTML = `
    <h3>🎨 Communities Detected</h3>
    <div class="community-list">
      ${Array.from(communities.entries()).map(([commId, members], idx) => `
        <div class="community-item" style="border-left: 4px solid ${communityColors.get(commId)}">
          <strong>${esc(communityNames.get(commId))}</strong>
          <div class="text-sm text-gray-400">${members.length} nodes</div>
        </div>
      `).join('')}
    </div>
  `;
}

// Reset colors
function resetNetworkColors() {
  if (!networkInstance) return;
  buildGraph(); // Rebuild with original colors
}

// Calculate centrality
function calculateCentrality() {
  if (!networkData) return {};

  const adj = new Map();
  networkData.nodes.forEach(n => adj.set(n.id, []));
  networkData.edges.forEach(e => {
    adj.get(e.source).push(e.target);
    adj.get(e.target).push(e.source);
  });

  // Degree centrality
  const degree = new Map();
  networkData.nodes.forEach(n => degree.set(n.id, adj.get(n.id).length));

  // Betweenness (simplified)
  const betweenness = new Map();
  networkData.nodes.forEach(n => betweenness.set(n.id, 0));

  return { degree, betweenness };
}

// Show network statistics
function showNetworkStats() {
  if (!networkData) return;

  const { degree } = calculateCentrality();

  const stats = {
    totalNodes: networkData.nodes.length,
    totalEdges: networkData.edges.length,
    primaryNodes: networkData.nodes.filter(n => n.type === 'primary').length,
    secondaryNodes: networkData.nodes.filter(n => n.type === 'secondary').length,
    avgConnections: networkData.edges.length > 0 ? (networkData.edges.length * 2 / networkData.nodes.length).toFixed(1) : 0,
  };

  const topConnected = [...degree.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([id, deg]) => {
      const node = networkData.nodes.find(n => n.id === id);
      return { name: node?.name || '?', degree: deg };
    });

  document.getElementById('mm-details').innerHTML = `
    <h3>📊 Network Statistics</h3>
    <div class="stats-list">
      <div class="stat-row"><span>Total Nodes:</span> <strong>${stats.totalNodes}</strong></div>
      <div class="stat-row"><span>Primary Nodes:</span> <strong>${stats.primaryNodes}</strong></div>
      <div class="stat-row"><span>Secondary Nodes:</span> <strong>${stats.secondaryNodes}</strong></div>
      <div class="stat-row"><span>Total Connections:</span> <strong>${stats.totalEdges}</strong></div>
      <div class="stat-row"><span>Avg Connections:</span> <strong>${stats.avgConnections}</strong></div>
    </div>
    <h4 class="mt-4">Most Connected</h4>
    <div class="top-nodes">
      ${topConnected.map((n, i) => `
        <div class="top-node-item">
          <span class="rank">${i + 1}.</span>
          <span class="name">${esc(n.name)}</span>
          <span class="degree">${n.degree} connections</span>
        </div>
      `).join('')}
    </div>
  `;
}

// Export as PNG
async function exportNetwork() {
  if (!networkInstance) return;

  const canvas = networkInstance.canvas.frame.canvas;
  const dataUrl = canvas.toDataURL('image/png');
  
  const link = document.createElement('a');
  link.download = `network-graph-${new Date().toISOString().split('T')[0]}.png`;
  link.href = dataUrl;
  link.click();
}
async function renderLegalFiles(el) {
  el.innerHTML = '<div class="loading">Loading legal case files...</div>';
  if (!legalCases) {
    legalCases = await api('/api/legal/cases');
  }

  const caseIds = Object.keys(legalCases);
  const CASE_ICONS = { criminal: '⚖️', appeal: '📜', habeas: '🏛️', analysis: '🤖' };

  let html = `<div class="legal-view">
    <h2>⚖️ Legal Case Files</h2>
    <div class="legal-cases">`;

  for (const cid of caseIds) {
    const c = legalCases[cid];
    const icon = CASE_ICONS[c.case_type] || '📄';
    html += `
      <div class="legal-case-card">
        <div class="legal-case-header" onclick="toggleLegalCase('${cid}')">
          <span>${icon} ${esc(c.label)}</span>
          <span class="legal-case-count">${c.file_count} files</span>
        </div>
        <div class="legal-case-files" id="legal-files-${cid}" style="display:none">
          <div class="legal-search">
            <input type="text" placeholder="Filter files..." oninput="filterLegalFiles('${cid}', this.value)">
          </div>
          <div class="legal-file-list" id="legal-list-${cid}">
    `;
    for (const f of c.files) {
      const action = f.pdf_path
        ? `onclick="openLegalPdf('${esc(f.pdf_path)}')" title="Open PDF"`
        : `onclick="openLegalTxt('${esc(f.txt_path)}')" title="View text"`;
      const icon2 = f.pdf_path ? '📕' : '📄';
      html += `<div class="legal-file-row" data-name="${esc(f.filename.toLowerCase())}" ${action}>
        <span class="legal-file-icon">${icon2}</span>
        <span class="legal-file-name">${esc(f.filename)}</span>
      </div>`;
    }
    html += `</div></div></div>`;
  }
  html += '</div></div>';
  el.innerHTML = html;
}

function toggleLegalCase(caseId) {
  const el = document.getElementById(`legal-files-${caseId}`);
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function filterLegalFiles(caseId, query) {
  const q = query.toLowerCase();
  document.querySelectorAll(`#legal-list-${caseId} .legal-file-row`).forEach(row => {
    row.style.display = row.dataset.name.includes(q) ? '' : 'none';
  });
}

// ─── Admin Portal ───
async function renderAdmin(el) {
  if (!currentUser || currentUser.role !== 'admin') {
    el.innerHTML = '<div class="empty"><div class="icon">🔒</div>Admin access required</div>';
    return;
  }
  el.innerHTML = '<div class="loading">Loading admin panel</div>';

  const [users, history] = await Promise.all([
    api('/api/admin/users'),
    api('/api/admin/login-history?limit=50')
  ]);

  el.innerHTML = `
    <div class="admin-view">
      <h2>⚙️ Admin Portal</h2>

      <div class="admin-section">
        <h3>Create User</h3>
        <div class="admin-form" id="create-user-form">
          <div><label>Username</label><input type="text" id="new-username" placeholder="username"></div>
          <div><label>Display Name</label><input type="text" id="new-displayname" placeholder="Display Name"></div>
          <div><label>Email</label><input type="email" id="new-email" placeholder="email@example.com"></div>
          <div><label>Role</label><select id="new-role"><option value="viewer">Viewer</option><option value="analyst">Analyst</option><option value="legal">Legal</option><option value="admin">Admin</option></select></div>
          <div><label>Password</label><input type="password" id="new-password" placeholder="Min 8 characters"></div>
          <div style="display:flex;align-items:end"><button onclick="createUser()">Create User</button></div>
          <div class="full-width" id="create-user-msg" style="font-size:12px"></div>
        </div>
      </div>

      <div class="admin-section">
        <h3>Users (${users.length})</h3>
        <table class="admin-table">
          <thead><tr><th>Username</th><th>Display Name</th><th>Role</th><th>Last Login</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            ${users.map(u => `<tr>
              <td>${esc(u.username)}</td>
              <td>${esc(u.display_name || '')}</td>
              <td><span class="user-role-badge">${esc(u.role)}</span></td>
              <td style="font-size:11px;color:var(--text2)">${u.last_login ? formatTs(u.last_login) : 'Never'}</td>
              <td><span class="${u.is_active ? 'status-active' : 'status-inactive'}">${u.is_active ? '● Active' : '● Inactive'}</span></td>
              <td class="admin-actions">
                <button onclick="editUserRole('${esc(u.id)}','${esc(u.role)}')">Role</button>
                <button onclick="resetUserPassword('${esc(u.id)}')">Reset PW</button>
                ${u.is_active ? `<button class="danger" onclick="toggleUserActive('${esc(u.id)}',false)">Deactivate</button>` : `<button onclick="toggleUserActive('${esc(u.id)}',true)">Activate</button>`}
              </td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>

      <div class="admin-section">
        <h3>Login History (Recent 50)</h3>
        <table class="admin-table">
          <thead><tr><th>Time</th><th>Username</th><th>IP</th><th>Result</th></tr></thead>
          <tbody>
            ${history.map(h => `<tr>
              <td style="font-size:11px;color:var(--text2)">${formatTs(h.timestamp)}</td>
              <td>${esc(h.username || '')}</td>
              <td style="font-family:monospace;font-size:11px">${esc(h.ip_address || '')}</td>
              <td><span class="${h.success ? 'status-active' : 'status-inactive'}">${h.success ? '✓ Success' : '✗ Failed'}</span></td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>

      <div class="admin-section">
        <h3>📋 Server Logs</h3>
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
          <select id="log-type" onchange="loadLogs()" style="padding:4px 8px;border-radius:4px;background:var(--surface2);color:var(--text);border:1px solid var(--border)">
            <option value="auth">Auth</option>
            <option value="app">App</option>
            <option value="access">Access</option>
          </select>
          <label style="font-size:12px;display:flex;align-items:center;gap:4px">
            <input type="checkbox" id="log-auto-refresh" onchange="toggleLogRefresh()"> Auto-refresh
          </label>
          <button onclick="loadLogs()" style="font-size:12px;padding:4px 10px">Refresh</button>
        </div>
        <pre id="log-output" style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:12px;font-family:'JetBrains Mono',monospace;font-size:11px;max-height:400px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;color:var(--text2)">Select a log type and click Refresh</pre>
      </div>
    </div>
  `;
}

async function createUser() {
  const msg = document.getElementById('create-user-msg');
  const data = {
    username: document.getElementById('new-username').value,
    password: document.getElementById('new-password').value,
    display_name: document.getElementById('new-displayname').value || undefined,
    email: document.getElementById('new-email').value || undefined,
    role: document.getElementById('new-role').value,
  };
  if (!data.username || !data.password) { msg.innerHTML = '<span style="color:var(--red)">Username and password required</span>'; return; }
  try {
    await api('/api/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data)
    });
    msg.innerHTML = '<span style="color:var(--accent2)">✓ User created</span>';
    document.getElementById('new-username').value = '';
    document.getElementById('new-password').value = '';
    document.getElementById('new-displayname').value = '';
    document.getElementById('new-email').value = '';
    setTimeout(() => renderAdmin(document.getElementById('app')), 1000);
  } catch (e) {
    msg.innerHTML = `<span style="color:var(--red)">${esc(e.message)}</span>`;
  }
}

async function editUserRole(userId, currentRole) {
  const newRole = prompt(`Change role (current: ${currentRole}).\nOptions: admin, analyst, viewer, legal`, currentRole);
  if (!newRole || newRole === currentRole) return;
  try {
    await api(`/api/admin/users/${userId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ role: newRole })
    });
    renderAdmin(document.getElementById('app'));
  } catch (e) { alert('Error: ' + e.message); }
}

async function resetUserPassword(userId) {
  const pw = prompt('Enter new password (min 8 chars):');
  if (!pw) return;
  try {
    await api(`/api/admin/users/${userId}/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ password: pw })
    });
    alert('Password reset successfully');
  } catch (e) { alert('Error: ' + e.message); }
}

async function toggleUserActive(userId, active) {
  if (!active) {
    if (!confirm('Deactivate this user? Their sessions will be revoked.')) return;
    try {
      await api(`/api/admin/users/${userId}`, { method: 'DELETE', headers: authHeaders() });
      renderAdmin(document.getElementById('app'));
    } catch (e) { alert('Error: ' + e.message); }
  } else {
    try {
      await api(`/api/admin/users/${userId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ is_active: true })
      });
      renderAdmin(document.getElementById('app'));
    } catch (e) { alert('Error: ' + e.message); }
  }
}

// ─── Log Viewer ───
let _logRefreshInterval = null;

async function loadLogs() {
  const type = document.getElementById('log-type')?.value || 'auth';
  const out = document.getElementById('log-output');
  if (!out) return;
  try {
    const data = await api(`/api/admin/logs?type=${type}&lines=100`);
    if (!data.lines || data.lines.length === 0) {
      out.innerHTML = '<span style="color:var(--text2)">No log entries yet</span>';
      return;
    }
    out.innerHTML = data.lines.map(line => {
      if (line.includes('[ERROR]')) return `<span style="color:var(--red)">${esc(line)}</span>`;
      if (line.includes('[WARNING]')) return `<span style="color:var(--accent)">${esc(line)}</span>`;
      return esc(line);
    }).join('\n');
    out.scrollTop = out.scrollHeight;
  } catch (e) {
    out.textContent = 'Error loading logs: ' + e.message;
  }
}

function toggleLogRefresh() {
  const on = document.getElementById('log-auto-refresh')?.checked;
  if (_logRefreshInterval) { clearInterval(_logRefreshInterval); _logRefreshInterval = null; }
  if (on) { loadLogs(); _logRefreshInterval = setInterval(loadLogs, 5000); }
}

function showEdgeDetails(edge) {
  const sidebar = document.getElementById('mm-details');
  if (!sidebar) return;

  const srcNode = networkData.nodes.find(n => n.id === edge.source);
  const tgtNode = networkData.nodes.find(n => n.id === edge.target);

  let html = `
    <h3>${esc(srcNode?.name || '?')} ↔ ${esc(tgtNode?.name || '?')}</h3>
    <div class="mm-stats"><div>Total weight: ${edge.weight}</div></div>
    <h4>Connection Types</h4>
  `;
  for (const t of edge.types) {
    const color = EDGE_COLORS[t.type] || '#95A5A6';
    html += `<div class="mm-edge-type" style="border-left:3px solid ${color};padding-left:8px;margin:6px 0">
      <strong>${t.type}</strong>
      ${t.count ? `<div>Count: ${t.count}</div>` : ''}
      ${t.message_count ? `<div>Messages: ${t.message_count}</div>` : ''}
      ${t.platform ? `<div>Platform: ${t.platform}</div>` : ''}
      ${t.appears_on_devices ? `<div>Devices: ${t.appears_on_devices.join(', ')}</div>` : ''}
      ${t.date_range ? `<div>Date: ${t.date_range}</div>` : ''}
    </div>`;
  }
  sidebar.innerHTML = html;
}
