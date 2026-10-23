/* BitTorrent-Lite browser GUI. Plain JavaScript, no build step.
   The page polls /api/state once a second and redraws the parts that change;
   dialogs and forms are drawn once so typing is never interrupted. */
'use strict';

const S = { open: {}, state: null, view: 'swarms', torrent: null, peer: null, exp: null, expSel: null, expRepeats: 1, create: {} };

// ---------- helpers ----------

function esc(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
// Update a region in place so buttons under the pointer survive the once-a-second redraw.
function morph(target, html) {
  if (target.__html === html) return;
  target.__html = html;
  const next = document.createElement(target.tagName);
  next.innerHTML = html;
  morphChildren(target, next);
}
function morphChildren(a, b) {
  const an = Array.from(a.childNodes); const bn = Array.from(b.childNodes);
  bn.forEach((y, i) => {
    const x = an[i];
    if (!x) return a.appendChild(y.cloneNode(true));
    if (x.nodeType !== y.nodeType || x.nodeName !== y.nodeName) return a.replaceChild(y.cloneNode(true), x);
    if (x.nodeType !== 1) { if (x.nodeValue !== y.nodeValue) x.nodeValue = y.nodeValue; return; }
    Array.from(x.attributes).forEach(at => { if (!y.hasAttribute(at.name)) x.removeAttribute(at.name); });
    Array.from(y.attributes).forEach(at => { if (x.getAttribute(at.name) !== at.value) x.setAttribute(at.name, at.value); });
    morphChildren(x, y);
  });
  for (let i = an.length - 1; i >= bn.length; i--) a.removeChild(an[i]);
}
function $(sel, root) { return (root || document).querySelector(sel); }
function $all(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }
function bytes(n) {
  if (n == null) return '–';
  const u = ['B', 'KiB', 'MiB', 'GiB']; let i = 0; n = Number(n);
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(n >= 100 ? 0 : 1) : n) + ' ' + u[i];
}
function rate(n) { return n > 0 ? bytes(n) + '/s' : '–'; }
function short(id) { return id ? id.slice(0, 6) + '…' + id.slice(-4) : ''; }
function clock(t) { const d = new Date(t * 1000); return d.toTimeString().slice(0, 8); }
function elapsed(p) {
  const end = p.ended_at || Date.now() / 1000; const s = Math.max(0, Math.round(end - p.started_at));
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}
function toast(text, isError) {
  const el = document.createElement('div');
  el.className = 'toast' + (isError ? ' err' : '');
  el.textContent = text;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), isError ? 9000 : 4000);
}
async function api(path, body) {
  const opts = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-BTL-GUI': '1' }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ error: 'bad response from the GUI server' }));
  if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
  return data;
}
async function act(path, body, okText) {
  try {
    const data = await api(path, body);
    if (data && data.peers && data.torrents) S.state = data;
    if (okText) toast(okText);
    render();
    return data;
  } catch (e) { toast(e.message, true); return null; }
}
const ICON = {
  check: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 8.5l3 3 7-7"/></svg>',
  warn: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M8 2 1.5 13.5h13z"/><path d="M8 6.5v3.2M8 11.6v.2"/></svg>',
  info: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="8" cy="8" r="6.5"/><path d="M8 7.2v4M8 4.8v.2"/></svg>',
  plus: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M7 2v10M2 7h10"/></svg>',
  close: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 3l10 10M13 3 3 13"/></svg>',
  regen: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 7a5 5 0 1 1-1.5-3.6M12 2v3h-3"/></svg>',
  minus: '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M2 6h8"/></svg>',
  more: '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M2 6h8M6 2v8"/></svg>',
  folder: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M1.5 4h5l1.5 1.5h6.5v8h-13z"/></svg>',
  file: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3.5 1.5h6l3 3v10h-9z"/></svg>',
  share: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="3.5" cy="7" r="1.8"/><circle cx="10.5" cy="3" r="1.8"/><circle cx="10.5" cy="11" r="1.8"/><path d="M5 6.1 9 3.9M5 7.9l4 2.2"/></svg>',
  join: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M7 1.5v8M3.8 6.5 7 9.7l3.2-3.2M2 12.5h10"/></svg>',
};
function note(kind, html) {
  const icon = kind === 'ok' ? ICON.check : kind === 'info' ? ICON.info : ICON.warn;
  return `<div class="note note-${kind}">${icon}<div>${html}</div></div>`;
}

// ---------- state labels ----------

const STATE = {
  STARTING: ['Starting', 'b-stop'], DOWNLOADING: ['Downloading', 'b-down'], STALLED: ['Waiting', 'b-stall'],
  SEEDING: ['Seeding', 'b-seed'], DONE: ['Done, seeding', 'b-seed'], STOPPING: ['Stopping', 'b-stop'],
  STOPPED: ['Stopped', 'b-stop'], EXITED: ['Exited', 'b-bad'], ERROR: ['Error', 'b-bad'],
};
function badge(p) {
  const [label, cls] = STATE[p.state] || [p.state, 'b-stop'];
  const hash = p.hash_check === 'ok' ? ' <span title="Whole-file SHA-256 matches the torrent">✓</span>' : p.hash_check === 'mismatch' ? ' ✗' : '';
  return `<span class="badge ${cls}">${label}${hash}</span>`;
}

// ---------- routing and polling ----------

function setView(view) {
  S.view = ['swarms', 'create', 'experiments'].includes(view) ? view : 'swarms';
  $all('[data-nav]').forEach(a => a.setAttribute('aria-current', a.dataset.nav === S.view ? 'page' : 'false'));
  drawPage();
}
document.addEventListener('toggle', e => { if (e.target.dataset && e.target.dataset.keep) S.open[e.target.dataset.keep] = e.target.open; }, true);
window.addEventListener('hashchange', () => setView(location.hash.slice(1)));

async function poll() {
  try {
    S.state = await api('/api/state' + (S.peer ? '?peer=' + encodeURIComponent(S.peer) : ''));
    if (S.view === 'experiments') S.exp = await api('/api/experiments');
    render();
  } catch (e) {
    $('#tracker-card').__html = null; $('#tracker-card').innerHTML = '<div class="cap">GUI server</div><div>Not responding. Is the terminal still open?</div>';
  }
  setTimeout(poll, 1000);
}

function render() {
  if (!S.state) return;
  drawSide();
  if (S.view === 'swarms') updateSwarms();
  if (S.view === 'create') updateCreate();
  if (S.view === 'experiments') updateExperiments();
}

// ---------- sidebar ----------

function drawSide() {
  const st = S.state; const tr = st.tracker;
  const local = tr && tr.running;
  let html = '<div class="cap">Tracker</div>';
  if (local) {
    html += `<div class="inline"><span class="dot" style="background: var(--ok-dot)"></span>Running on this computer</div>
      <div class="mono">${esc(st.tracker_url)}</div>
      <button class="btn btn-side" data-act="tracker-stop">Stop tracker</button>`;
  } else if (st.tracker_custom) {
    html += `<div class="inline"><span class="dot" style="background: #7FA4F0"></span>Another computer's</div>
      <div class="mono">${esc(st.tracker_url)}</div>
      <button class="btn btn-side" data-act="network">Change</button>`;
  } else {
    html += `<div class="inline"><span class="dot" style="background: #6B7480"></span>Not running</div>
      <div class="help" style="color: #A3ABB5">Start it on the computer that shares the file first.</div>
      <button class="btn btn-side" data-act="tracker-start">Start tracker here</button>`;
  }
  morph($('#tracker-card'), html);
  const addr = st.addresses.find(a => a.ip === st.advertise_ip) || {};
  morph($('#net-card'), `<div class="cap">This computer</div>
    <div class="inline"><span class="mono" style="color:#fff">${esc(st.advertise_ip)}</span><span class="kind ${esc(addr.kind)}">${esc(addr.kind || '')}</span></div>
    <button class="btn btn-side" data-act="network">Network settings</button>`);
}

// ---------- swarms page ----------

function currentTorrent() {
  const ts = S.state.torrents;
  if (!ts.length) return null;
  if (!ts.find(t => t.file_id === S.torrent)) S.torrent = ts[ts.length - 1].file_id;
  return ts.find(t => t.file_id === S.torrent);
}

function drawPage() {
  const main = $('#main');
  if (S.view === 'swarms') main.innerHTML = '<header class="topbar" id="sw-top"></header><div id="sw-body"></div>';
  if (S.view === 'create') drawCreate(main);
  if (S.view === 'experiments') drawExperiments(main);
  render();
}

function updateSwarms() {
  const st = S.state; const t = currentTorrent();
  const top = $('#sw-top'); const body = $('#sw-body');
  if (!top) return;
  const tabs = st.torrents.map(x => `<button class="tab" role="tab" aria-selected="${t && x.file_id === t.file_id}" data-torrent="${x.file_id}" title="${esc(x.filename)}">${esc(x.filename)}</button>`).join('');
  morph(top, `<div class="tabs" role="tablist" aria-label="Torrents">${tabs}
      <button class="btn btn-ghost btn-sm" data-act="open-torrent">${ICON.plus}Open .torrent.json</button>
      <button class="btn btn-ghost btn-sm" data-act="join">${ICON.join}Join swarm</button></div>
    ${t ? `<button class="btn btn-ghost" data-act="share">${ICON.share}Share</button>` : ''}`);
  if (!t) { morph(body, emptyState()); return; }
  const peers = st.peers.filter(p => p.file_id === t.file_id);
  if (S.peer && !peers.find(p => p.peer_id === S.peer)) S.peer = null;
  if (!S.peer && peers.length) S.peer = peers[0].peer_id;
  const sel = peers.find(p => p.peer_id === S.peer);
  const running = peers.filter(p => p.running);
  const downloaders = peers.filter(p => p.role === 'downloader');
  const completion = downloaders.length ? Math.round(100 * downloaders.reduce((a, p) => a + p.owned / p.total, 0) / downloaders.length) : null;
  const down = running.reduce((a, p) => a + p.down_rate, 0);
  const up = peers.reduce((a, p) => a + p.up_bytes, 0);
  const transferring = running.filter(p => p.state === 'DOWNLOADING' || p.up_rate > 0).length;
  const warn = [];
  if (!t.network_ok) warn.push(note('bad', 'Pieces in this torrent are larger than 64 KiB, which peers refuse. Recreate it on the Create torrent page.'));
  const seen = seenByTracker(t);

  morph(body, `<div class="swarm">
    <section class="swarm-main">
      <div class="titlerow">
        <div><h1>${esc(t.filename)}</h1>
          <div class="help" style="margin-top: 4px">${bytes(t.file_size)} · ${t.num_pieces} pieces × ${bytes(t.piece_size)} · file_id <span class="mono">${short(t.file_id)}</span></div></div>
        <a class="btn btn-ghost" href="/api/torrents/${t.file_id}/file" download>Download .torrent.json</a>
        <button class="btn btn-ghost" data-act="quick">Quick swarm</button>
        <button class="btn btn-primary" data-act="add-peer">${ICON.plus}Add peer</button>
      </div>
      ${warn.join('')}
      <div class="tiles">
        <div class="tile"><div class="cap">Peers here</div><div class="v">${running.length} <span>${transferring} transferring</span></div></div>
        <div class="tile"><div class="cap">Download completion</div><div class="v">${completion == null ? '–' : completion + '%'}</div></div>
        <div class="tile"><div class="cap">Download rate</div><div class="v">${down > 0 ? bytes(down).split(' ')[0] : '0'} <span>${down > 0 ? bytes(down).split(' ')[1] + '/s' : 'B/s'}</span></div></div>
        <div class="tile"><div class="cap">Uploaded</div><div class="v">${bytes(up).split(' ')[0]} <span>${bytes(up).split(' ')[1]}</span></div></div>
      </div>
      <div class="table" role="grid">
        <div class="thead"><div>Peer</div><div>State</div><div>Progress</div><div class="num">Peers</div><div class="num">Down</div><div class="num">Up</div></div>
        ${peers.length ? peers.map(peerRow).join('') : `<div style="padding: 24px 16px; border-top: 1px solid var(--line-2)" class="help">No peers on this computer for this file yet. ${t.source ? 'Add a seeder to share it.' : 'Add a downloader to fetch it.'}</div>`}
        <div class="tfoot"><div class="help" style="flex: 1">Peer IDs and ports are picked automatically. A peer that finishes keeps seeding (uploading to others) until you stop it; that is normal.</div>
          ${running.length ? '<button class="btn btn-ghost btn-sm" data-act="stop-all">Stop all</button>' : ''}</div>
      </div>
      ${seen}
    </section>
    ${sel ? peerPanel(sel, t) : ''}
  </div>`);
}

function emptyState() {
  return `<div class="empty"><div><h1>Share or download a file</h1>
    <div class="help" style="margin-top: 6px">One computer shares the file and runs the tracker. The others join it with its address.</div></div>
    <div class="choices">
      <button class="choice" data-act="goto-create"><div class="lbl" style="font-size: 15px">Share a file from this computer</div>
        <div class="help">Create a torrent from your file, start the tracker and seed it. Others then join with this computer's address, <span class="mono">${esc(S.state.share_address)}</span>.</div></button>
      <button class="choice" data-act="join"><div class="lbl" style="font-size: 15px">Download from another computer</div>
        <div class="help">Type the sharing computer's address. Its torrents and tracker are picked up for you; no curl needed.</div></button>
    </div>
    <button class="btn btn-ghost" data-act="open-torrent">Or open a .torrent.json you already have</button></div>`;
}

function peerRow(p) {
  const pct = Math.round(100 * p.owned / p.total);
  return `<button class="row" role="row" aria-selected="${p.peer_id === S.peer}" data-peer="${esc(p.peer_id)}">
    <div style="min-width: 0"><div class="pid">${esc(p.peer_id)}</div><div class="help">${p.role === 'seeder' ? 'Seeder' : 'Downloader'}${p.free_rider ? ' (free rider)' : ''} · :${p.port}</div></div>
    <div>${badge(p)}</div>
    <div class="inline" style="gap: 10px"><div class="bar" style="flex: 1"><div style="width: ${pct}%"></div></div><span class="help" style="min-width: 64px; text-align: right">${p.owned}/${p.total}</span></div>
    <div class="num">${p.connected}</div><div class="num">${rate(p.down_rate)}</div><div class="num">${bytes(p.up_bytes)}</div></button>`;
}

function seenByTracker(t) {
  const tr = S.state.tracker;
  if (!tr || !tr.running) return '';
  const rows = (tr.members[t.file_id.slice(0, 8)] || []);
  const mine = new Set(S.state.peers.map(p => p.peer_id));
  return `<div class="card card-pad seen"><div class="inline" style="margin-bottom: 6px"><div class="cap" style="flex: 1">Seen by the tracker (all computers)</div><span class="help">${rows.length} peer(s)</span></div>
    ${rows.length ? rows.map(r => `<div class="r"><span class="mono">${esc(r.peer_id)}${mine.has(r.peer_id) ? '' : ' <span class="kind tailscale">remote</span>'}</span><span class="mono">${esc(r.ip)}:${r.port}</span><span class="muted">${esc(r.event)} ${clock(r.t)}</span></div>`).join('')
      : '<div class="help">No peer has announced this file yet.</div>'}</div>`;
}

function peerPanel(p, t) {
  const pieces = p.pieces || '';
  const map = pieces ? pieces.split('').map(c => c === 'v' ? '<i class="v"></i>' : c === 'r' ? '<i class="r"></i>' : '<i></i>').join('') : '';
  let explain = '';
  if (p.state === 'DONE') explain = note('ok', 'Download complete. The peer now <b>seeds</b>: it stays online and uploads pieces to the others until you press Stop. This is normal.');
  if (p.state === 'STALLED' && p.role !== 'seeder') explain = note('warn', p.connected ? 'Connected, but no peer has the pieces this one still needs yet. It continues when they arrive.' : 'Waiting for peers. It needs a seeder or another peer in the swarm. Check that the tracker address is right and the seeder is running.');
  if (p.state === 'EXITED') explain = note('bad', 'The peer exited with code ' + p.exit_code + (p.last_error ? ': ' + esc(p.last_error) : '.'));
  let hash = '';
  if (p.hash_check === 'ok') hash = note('ok', `File verified: its SHA-256 matches the torrent (<span class="mono">${short(p.hash_detail)}</span>).`);
  if (p.hash_check === 'checking') hash = note('info', 'Checking the whole-file SHA-256…');
  if (p.hash_check === 'mismatch') hash = note('bad', 'The finished file does NOT match the torrent: ' + esc(p.hash_detail));
  if (p.hash_check === 'error') hash = note('bad', 'Could not hash the file: ' + esc(p.hash_detail));
  const events = (p.events || []).slice().reverse().map(e => `<div><span class="muted">${clock(e.t)}</span><span class="d"><span class="e">${esc(e.e)}</span> ${esc(e.d)}</span></div>`).join('');
  return `<aside class="panel" aria-label="Selected peer">
    <section><div class="inline" style="align-items: flex-start"><div style="flex: 1; min-width: 0"><div class="pid" style="font-size: 15px">${esc(p.peer_id)}</div>
      <div class="help">${p.role} · port ${p.port} · ${esc(p.strategy)}, window ${p.window}</div></div>${badge(p)}</div></section>
    <section><div class="stats">
      <div><div class="cap">Pieces</div><div class="v">${p.owned}/${p.total}</div></div>
      <div><div class="cap">Connected</div><div class="v">${p.connected}</div></div>
      <div><div class="cap">Pending req.</div><div class="v">${p.pending}</div></div>
      <div><div class="cap">Downloaded</div><div class="v">${bytes(p.down_bytes)}</div></div>
      <div><div class="cap">Uploaded</div><div class="v">${bytes(p.up_bytes)}</div></div>
      <div><div class="cap">${p.completion_seconds != null ? 'Finished in' : 'Elapsed'}</div><div class="v">${p.completion_seconds != null ? p.completion_seconds.toFixed(1) + ' s' : elapsed(p)}</div></div>
    </div>${p.neighbors && p.neighbors.length ? `<div class="help" style="margin-top: 10px">Connected to <span class="mono">${p.neighbors.map(esc).join(', ')}</span></div>` : ''}</section>
    ${explain || hash ? `<section style="display: flex; flex-direction: column; gap: 8px">${explain}${hash}</section>` : ''}
    <section><div class="inline"><div class="cap" style="flex: 1">Piece map</div>
      <div class="legend"><span><i style="background: var(--piece-v)"></i>Verified</span><span><i style="background: var(--piece-r)"></i>Requested</span><span><i style="background: var(--piece-m)"></i>Missing</span></div></div>
      <div class="pmap" role="img" aria-label="Piece map, ${p.owned} of ${p.total} pieces verified">${map}</div></section>
    <section><div class="cap">Live events</div><div class="events">${events || '<span class="muted">No events yet.</span>'}</div></section>
    <section class="inline" style="flex-wrap: wrap">
      ${p.running ? `<button class="btn btn-ghost" data-act="stop-peer" ${p.state === 'STOPPING' ? 'disabled' : ''}>Stop peer</button>`
        : `<button class="btn btn-primary" data-act="restart-peer">Restart (keeps verified pieces)</button><button class="btn btn-ghost" data-act="remove-peer">Remove</button>`}
      <button class="btn btn-ghost" data-act="open-folder">Open folder</button>
    </section>
    <section><details data-keep="cmd" ${S.open.cmd ? 'open' : ''}><summary class="help" style="cursor: pointer">Command and log file</summary>
      <div class="code" style="margin-top: 8px">${esc(p.command || '')}</div><div class="help mono" style="margin-top: 6px">${esc(p.log_path || '')}</div></details></section>
  </aside>`;
}

// ---------- dialogs ----------

function openDialog(html, cls) {
  const root = $('#dialog-root');
  root.innerHTML = `<div class="overlay"><div class="dialog ${cls || ''}" role="dialog" aria-modal="true">${html}</div></div>`;
  const first = root.querySelector('input, button.btn-primary, button');
  if (first) setTimeout(() => first.focus(), 30);
  return root.firstElementChild;
}
function closeDialog() { $('#dialog-root').innerHTML = ''; }
function dlgHead(title, sub) {
  return `<div class="dlg-head"><div><h2>${title}</h2>${sub ? `<div class="help" style="margin-top: 4px; font-size: 13px">${sub}</div>` : ''}</div>
    <button class="btn btn-ghost btn-icon" data-close aria-label="Close" style="border: 0">${ICON.close}</button></div>`;
}
document.addEventListener('keydown', e => { if (e.key === 'Escape' && $('#dialog-root').innerHTML) closeDialog(); });

function seg(name, options, value) {
  return `<div class="seg" role="group" data-seg="${name}">${options.map(([v, label]) =>
    `<button type="button" class="seg-b" data-v="${esc(v)}" aria-pressed="${String(v) === String(value)}">${label}</button>`).join('')}</div>`;
}
function segValue(root, name) { const b = root.querySelector(`[data-seg="${name}"] [aria-pressed="true"]`); return b ? b.dataset.v : null; }
function bindSegs(root, onChange) {
  root.addEventListener('click', e => {
    const b = e.target.closest('.seg-b'); if (!b) return;
    $all('.seg-b', b.parentElement).forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    onChange && onChange(b.parentElement.dataset.seg);
  });
}

// File browser. mode: 'file' | 'dir' | 'save'
function browse(mode, startPath, onPick, filter) {
  const prev = $('#dialog-root').innerHTML;
  const prevState = $('#dialog-root').firstElementChild;
  const holder = document.createElement('div');
  holder.innerHTML = `<div class="overlay" style="z-index: 30"><div class="dialog narrow" role="dialog" aria-modal="true">
    ${dlgHead(mode === 'dir' ? 'Choose a folder' : mode === 'save' ? 'Choose where to save' : 'Choose a file')}
    <div style="padding: 16px 24px; display: flex; flex-direction: column; gap: 10px">
      <div class="inline"><input class="inp mono" id="fs-path" aria-label="Path"><button class="btn btn-ghost" id="fs-go">Go</button></div>
      <div class="inline" id="fs-roots" style="flex-wrap: wrap"></div>
      <div class="fs-list" id="fs-list"></div>
      ${mode === 'save' ? '<div class="field"><label class="lbl" for="fs-name">File name</label><input class="inp mono" id="fs-name"></div>' : ''}
    </div>
    <div class="dlg-foot"><div class="grow help" id="fs-chosen"></div><button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-primary" id="fs-ok">${mode === 'dir' ? 'Use this folder' : mode === 'save' ? 'Save here' : 'Choose'}</button></div>
  </div></div>`;
  document.body.appendChild(holder);
  let current = null; let chosen = null;
  const close = () => holder.remove();
  holder.addEventListener('click', e => { if (e.target.closest('[data-close]')) close(); });
  async function load(path) {
    try {
      const data = await api('/api/fs' + (path ? '?path=' + encodeURIComponent(path) : ''));
      current = data.path; chosen = null;
      $('#fs-path', holder).value = data.path;
      $('#fs-roots', holder).innerHTML = (data.parent ? `<button class="btn btn-ghost btn-sm" data-go="${esc(data.parent)}">Up</button>` : '') +
        data.roots.map(r => `<button class="btn btn-ghost btn-sm" data-go="${esc(r)}">${esc(r)}</button>`).join('');
      const items = data.entries.filter(e => e.dir || mode !== 'dir').filter(e => e.dir || !filter || filter(e.name));
      $('#fs-list', holder).innerHTML = items.map(e => `<button class="fs-item" data-path="${esc(e.path)}" data-dir="${e.dir}" data-size="${e.size || 0}">${e.dir ? ICON.folder : ICON.file}<span>${esc(e.name)}</span>${e.dir ? '' : `<span class="sz">${bytes(e.size)}</span>`}</button>`).join('') || '<div class="help" style="padding: 12px">Empty folder.</div>';
      $('#fs-chosen', holder).textContent = mode === 'file' ? 'Double-click a folder to open it.' : '';
    } catch (e) { toast(e.message, true); }
  }
  holder.addEventListener('click', e => {
    const go = e.target.closest('[data-go]'); if (go) return load(go.dataset.go);
    const item = e.target.closest('.fs-item'); if (!item) return;
    if (item.dataset.dir === 'true') { if (mode === 'dir') { $all('.fs-item', holder).forEach(x => x.setAttribute('aria-selected', String(x === item))); chosen = { path: item.dataset.path }; } else load(item.dataset.path); return; }
    $all('.fs-item', holder).forEach(x => x.setAttribute('aria-selected', String(x === item)));
    chosen = { path: item.dataset.path, size: Number(item.dataset.size) };
    if (mode === 'save') $('#fs-name', holder).value = item.dataset.path.split(/[\\/]/).pop();
    $('#fs-chosen', holder).textContent = item.dataset.path;
  });
  holder.addEventListener('dblclick', e => { const item = e.target.closest('.fs-item'); if (item && item.dataset.dir === 'true') load(item.dataset.path); else if (item && mode === 'file') $('#fs-ok', holder).click(); });
  $('#fs-go', holder).onclick = () => load($('#fs-path', holder).value);
  $('#fs-path', holder).addEventListener('keydown', e => { if (e.key === 'Enter') load(e.target.value); });
  $('#fs-ok', holder).onclick = () => {
    const sep = current && current.includes('\\') ? '\\' : '/';
    if (mode === 'dir') { onPick((chosen && chosen.path) || current); return close(); }
    if (mode === 'save') { const name = $('#fs-name', holder).value.trim(); if (!name) return toast('type a file name', true); onPick(current.replace(/[\\/]$/, '') + sep + name); return close(); }
    if (!chosen) return toast('choose a file first', true);
    onPick(chosen.path, chosen.size); close();
  };
  if (mode === 'save' && startPath) { const parts = startPath.split(/[\\/]/); $('#fs-name', holder).value = parts.pop(); load(parts.join(startPath.includes('\\') ? '\\' : '/')); }
  else load(startPath || '');
}

// Add peer dialog (mockup screen 2)
async function addPeerDialog(opts) {
  opts = opts || {};
  const t = S.state.torrents.find(x => x.file_id === (opts.file_id || S.torrent));
  if (!t) return toast('open or create a torrent first', true);
  const role0 = opts.role || (t.source ? 'seeder' : 'downloader');
  const dlg = openDialog(`${dlgHead('Add peer to ' + esc(t.filename), 'Starts the peer as a background process. You can watch it on this page.')}
    <div class="dlg-body"><div class="dlg-cols">
      <div class="dlg-col">
        <div class="field"><div class="lbl">Role</div>${seg('role', [['downloader', 'Downloader'], ['seeder', 'Seeder']], role0)}</div>
        <div class="field" id="ap-src"><label class="lbl" for="ap-source">Source file (the original)</label>
          <div class="inline"><input id="ap-source" class="inp mono" value="${esc(opts.source || t.source || '')}"><button type="button" class="btn btn-ghost" data-browse="source">Browse</button></div>
          <div class="help">Checked against the torrent's piece hashes before seeding starts.</div></div>
        <div class="field" id="ap-count"><div class="lbl">How many downloaders</div>
          <div class="inline"><button type="button" class="btn btn-ghost btn-icon" aria-label="Fewer" data-count="-1">${ICON.minus}</button>
          <div id="ap-n" style="width: 40px; text-align: center; font-size: 16px; font-weight: 600">${opts.count || 1}</div>
          <button type="button" class="btn btn-ghost btn-icon" aria-label="More" data-count="1">${ICON.more}</button>
          <div class="help">Each gets its own ID, port and folder.</div></div></div>
        <div id="ap-ids"></div>
        <div class="field"><label class="lbl" for="ap-out">Save to</label>
          <div class="inline"><input id="ap-out" class="inp mono"><button type="button" class="btn btn-ghost" data-browse="out">Browse</button></div>
          <div class="help">Each peer writes to its own subfolder named after its ID.</div></div>
      </div>
      <div class="dlg-col">
        <div class="cap">Advanced</div>
        <div class="field"><div class="lbl">Piece selection</div>${seg('strategy', [['rarest-first', 'Rarest first'], ['random', 'Random'], ['sequential', 'Sequential']], 'rarest-first')}</div>
        <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px">
          <div class="field"><div class="lbl">Requests in flight</div>${seg('window', [[1, '1'], [2, '2'], [3, '3'], [4, '4']], 4)}</div>
          <div class="field"><div class="lbl">Upload workers</div>${seg('workers', [[0, 'Off'], [2, '2']], 0)}</div></div>
        <div style="display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 12px; align-items: end">
          <div class="field"><label class="lbl" for="ap-seed">Random seed</label><input id="ap-seed" class="inp mono" value="0" inputmode="numeric"></div>
          <label class="check" style="height: 36px"><input type="checkbox" id="ap-free">Free rider (downloads, never uploads)</label></div>
        <div id="ap-check"></div>
        <div class="field"><div class="lbl">Command that will run</div><div class="code" id="ap-cmd">…</div></div>
      </div></div></div>
    <div class="dlg-foot"><div class="grow help">Tracker <span class="mono">${esc(S.state.tracker_url)}</span></div>
      <button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-primary" id="ap-start">Start</button></div>`);
  let ids = [];
  const count = () => Number($('#ap-n', dlg).textContent);
  const role = () => segValue(dlg, 'role');
  async function suggest() {
    try {
      const data = await api('/api/peers/suggest', { file_id: t.file_id, role: role(), count: role() === 'seeder' ? 1 : count() });
      ids = data.peers;
      if (!$('#ap-out', dlg).value) $('#ap-out', dlg).value = data.output_dir;
      drawIds(); preview();
    } catch (e) { toast(e.message, true); }
  }
  function drawIds() {
    $('#ap-ids', dlg).innerHTML = ids.map((r, i) => `<div style="display: grid; grid-template-columns: minmax(0, 1fr) 110px; gap: 12px">
      <div class="field"><label class="lbl" for="ap-id${i}">Peer ID${ids.length > 1 ? ' ' + (i + 1) : ''}</label>
        <div class="inline"><input id="ap-id${i}" class="inp mono" data-id="${i}" value="${esc(r.peer_id)}">${i === 0 ? `<button type="button" class="btn btn-ghost btn-icon" aria-label="Generate new IDs" data-regen>${ICON.regen}</button>` : ''}</div></div>
      <div class="field"><label class="lbl" for="ap-port${i}">Port</label><input id="ap-port${i}" class="inp mono" data-port="${i}" value="${r.port}" inputmode="numeric"></div></div>`).join('') +
      '<div class="help">Generated so no two peers share an ID (a duplicate ID makes a peer stall silently). Ports are the next free ones.</div>';
  }
  function body() {
    $all('[data-id]', dlg).forEach(el => { ids[el.dataset.id].peer_id = el.value.trim(); });
    $all('[data-port]', dlg).forEach(el => { ids[el.dataset.port].port = Number(el.value); });
    return { file_id: t.file_id, role: role(), source: $('#ap-source', dlg).value.trim(), output_dir: $('#ap-out', dlg).value.trim(),
      strategy: segValue(dlg, 'strategy'), window: Number(segValue(dlg, 'window')), upload_workers: Number(segValue(dlg, 'workers')),
      seed: Number($('#ap-seed', dlg).value) || 0, free_rider: $('#ap-free', dlg).checked, peers: ids,
      peer_id: ids[0] && ids[0].peer_id, port: ids[0] && ids[0].port };
  }
  let timer = null;
  function preview() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const seeder = role() === 'seeder';
      $('#ap-src', dlg).classList.toggle('hidden', !seeder);
      $('#ap-count', dlg).classList.toggle('hidden', seeder);
      $('#ap-start', dlg).textContent = seeder ? 'Start seeder' : count() > 1 ? `Start ${count()} downloaders` : 'Start downloader';
      try {
        const data = await api('/api/peers/preview', body());
        $('#ap-cmd', dlg).textContent = data.command + (ids.length > 1 ? `\n(+ ${ids.length - 1} more with their own ID and port)` : '');
        $('#ap-check', dlg).innerHTML = (data.check.ok ? note('ok', esc(data.check.message) + '. Nothing has started yet.') : note('bad', esc(data.check.message))) + data.warnings.map(w => note('warn', esc(w))).join('');
      } catch (e) { $('#ap-check', dlg).innerHTML = note('bad', esc(e.message)); $('#ap-cmd', dlg).textContent = '–'; }
    }, 250);
  }
  bindSegs(dlg, name => { if (name === 'role') suggest(); else preview(); });
  dlg.addEventListener('input', preview);
  dlg.addEventListener('click', async e => {
    if (e.target.closest('[data-close]')) return closeDialog();
    const c = e.target.closest('[data-count]');
    if (c) { $('#ap-n', dlg).textContent = Math.max(1, Math.min(8, count() + Number(c.dataset.count))); return suggest(); }
    if (e.target.closest('[data-regen]')) return suggest();
    const b = e.target.closest('[data-browse]');
    if (b && b.dataset.browse === 'source') browse('file', $('#ap-source', dlg).value, p => { $('#ap-source', dlg).value = p; preview(); });
    if (b && b.dataset.browse === 'out') browse('dir', $('#ap-out', dlg).value, p => { $('#ap-out', dlg).value = p; preview(); });
  });
  $('#ap-start', dlg).onclick = async () => {
    $('#ap-start', dlg).disabled = true;
    const data = await act('/api/peers/start', body());
    if (data) { closeDialog(); S.torrent = t.file_id; S.peer = data.started[0]; toast('Started ' + data.started.join(', ')); location.hash = 'swarms'; }
    else $('#ap-start', dlg).disabled = false;
  };
  suggest();
}

function joinDialog() {
  const dlg = openDialog(`${dlgHead('Join a swarm on another computer', 'On the sharing computer the GUI shows its address in the sidebar under "This computer".')}
    <div style="padding: 20px 24px; display: flex; flex-direction: column; gap: 14px">
      <div class="field"><label class="lbl" for="jn-addr">Sharing computer's address</label>
        <div class="inline"><input id="jn-addr" class="inp mono" placeholder="100.101.102.103" value="${esc(S.state.last_host)}"><button class="btn btn-primary" id="jn-go">Connect</button></div>
        <div class="help">A Tailscale address (100.x.y.z) works across cities; a LAN address works on the same Wi-Fi.</div></div>
      <div id="jn-out"></div>
    </div>
    <div class="dlg-foot"><div class="grow"></div><button class="btn btn-ghost" data-close>Close</button></div>`, 'narrow');
  dlg.addEventListener('click', e => { if (e.target.closest('[data-close]')) closeDialog(); });
  const go = async () => {
    const address = $('#jn-addr', dlg).value.trim();
    $('#jn-out', dlg).innerHTML = '<div class="help">Connecting…</div>';
    try {
      const data = await api('/api/join', { address });
      const trackerNote = !data.tracker ? note('warn', 'That computer is not running a tracker. Ask them to press "Start tracker here".')
        : data.tracker_check.ok ? note('ok', `Tracker at <span class="mono">${esc(data.tracker)}</span> is reachable and saved; your peers will use it.`)
        : note('bad', `Tracker <span class="mono">${esc(data.tracker)}</span> did not answer: ${esc(data.tracker_check.message)}`);
      $('#jn-out', dlg).innerHTML = `${trackerNote}<div class="card" style="margin-top: 12px"><div class="cap" style="padding: 12px 16px">Shared by ${esc(data.machine)}</div>
        ${data.torrents.length ? data.torrents.map(x => `<div class="cfg" style="cursor: default"><div style="flex: 1; min-width: 0"><div style="font-weight: 500">${esc(x.filename)}</div><div class="help">${bytes(x.file_size)} · ${x.num_pieces} pieces</div></div>
          <button class="btn btn-primary btn-sm" data-fetch="${x.file_id}">Download</button></div>`).join('') : '<div class="help" style="padding: 0 16px 14px">Nothing shared yet. Ask them to create a torrent first.</div>'}</div>`;
      render();
    } catch (e) { $('#jn-out', dlg).innerHTML = note('bad', esc(e.message)); }
  };
  $('#jn-go', dlg).onclick = go;
  $('#jn-addr', dlg).addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
  dlg.addEventListener('click', async e => {
    const f = e.target.closest('[data-fetch]'); if (!f) return;
    f.disabled = true;
    try {
      const data = await api('/api/join/fetch', { address: $('#jn-addr', dlg).value.trim(), file_id: f.dataset.fetch });
      S.state = await api('/api/state');
      S.torrent = data.torrent.file_id;
      closeDialog(); location.hash = 'swarms'; setView('swarms');
      addPeerDialog({ file_id: data.torrent.file_id, role: 'downloader' });
    } catch (err) { toast(err.message, true); f.disabled = false; }
  });
}

function shareDialog() {
  const st = S.state; const t = currentTorrent();
  const local = st.tracker && st.tracker.running;
  const link = `http://${st.share_address.includes(':') ? st.share_address : st.share_address + ':' + st.gui_port}/share/${t.file_id}.torrent.json`;
  const warn = [];
  if (!st.share) warn.push(note('bad', 'Sharing is off (the GUI was started with --no-share). Send the .torrent.json yourself.'));
  if (!local && !st.tracker_custom) warn.push(note('warn', 'No tracker yet. Press "Start tracker here" in the sidebar so the others can find this computer.'));
  const kind = (st.addresses.find(a => a.ip === st.advertise_ip) || {}).kind;
  if (kind === 'loopback') warn.push(note('bad', 'This computer\'s address is 127.0.0.1, which other computers cannot use. Pick another in Network settings.'));
  const dlg = openDialog(`${dlgHead('Share ' + esc(t.filename))}
    <div style="padding: 20px 24px; display: flex; flex-direction: column; gap: 14px">
      <div class="help" style="font-size: 13px">On each other computer: open the GUI, click <b>Join swarm</b> and type this address.</div>
      <div class="share-big">${esc(st.share_address)}</div>
      <div class="inline"><button class="btn btn-ghost" data-copy="${esc(st.share_address)}">Copy address</button><button class="btn btn-ghost" data-copy="${esc(link)}">Copy torrent link</button></div>
      ${warn.join('')}
      <div class="kv"><span class="muted">Tracker</span><span class="mono">${esc(st.tracker_url)}</span></div>
      <div class="kv"><span class="muted">Torrent link</span><span class="mono small">${esc(link)}</span></div>
      <div class="help">Both computers need Tailscale running (or the same Wi-Fi). On Windows, allow Python through the firewall the first time it asks.</div>
    </div>
    <div class="dlg-foot"><div class="grow"></div><button class="btn btn-primary" data-close>Done</button></div>`, 'narrow');
  dlg.addEventListener('click', e => {
    if (e.target.closest('[data-close]')) return closeDialog();
    const c = e.target.closest('[data-copy]');
    if (c) copyText(c.dataset.copy);
  });
}

function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(() => toast('Copied'), () => toast(text));
  else { const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); toast('Copied'); }
}

function networkDialog() {
  const st = S.state;
  const dlg = openDialog(`${dlgHead('Network settings', 'Which address other computers use to reach this one, and which tracker your peers announce to.')}
    <div style="padding: 20px 24px; display: flex; flex-direction: column; gap: 16px">
      <div class="field"><div class="lbl">This computer's address</div>
        ${st.addresses.map(a => `<label class="addr"><input type="radio" name="addr" value="${esc(a.ip)}" ${a.ip === st.advertise_ip ? 'checked' : ''}><span class="mono" style="flex: 1">${esc(a.ip)}</span><span class="kind ${esc(a.kind)}">${esc(a.kind)}</span></label>`).join('')}
        <div class="help">Tailscale is picked first when it is running. Peers always listen on all addresses, so a wrong choice can no longer cause "Errno 49"; this choice only decides what the tracker tells others.</div>
        <button class="btn btn-ghost btn-sm" data-refresh style="align-self: flex-start">Look again (after starting Tailscale)</button></div>
      <div class="field"><label class="lbl" for="nw-tracker">Tracker address</label>
        <div class="inline"><input id="nw-tracker" class="inp mono" placeholder="this computer's tracker" value="${esc(st.tracker_custom ? st.tracker_url : '')}"><button class="btn btn-ghost" data-test>Test</button></div>
        <div class="help">Leave empty to use the tracker on this computer (<span class="mono">http://${esc(st.advertise_ip)}:${esc((st.tracker && st.tracker.port) || 8000)}</span>). Join swarm fills this in for you.</div>
        <div id="nw-test"></div></div>
    </div>
    <div class="dlg-foot"><div class="grow help">Saved in <span class="mono">${esc(st.workdir)}</span></div><button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-primary" data-save>Save</button></div>`, 'narrow');
  dlg.addEventListener('click', async e => {
    if (e.target.closest('[data-close]')) return closeDialog();
    if (e.target.closest('[data-refresh]')) { await act('/api/addresses/refresh', {}); closeDialog(); return networkDialog(); }
    if (e.target.closest('[data-test]')) {
      $('#nw-test', dlg).innerHTML = '<div class="help">Testing…</div>';
      try { const r = await api('/api/tracker/test', { url: $('#nw-tracker', dlg).value.trim() || null }); $('#nw-test', dlg).innerHTML = note(r.ok ? 'ok' : 'bad', `<span class="mono">${esc(r.url)}</span>: ${esc(r.message)}`); }
      catch (err) { $('#nw-test', dlg).innerHTML = note('bad', esc(err.message)); }
    }
    if (e.target.closest('[data-save]')) {
      const ip = (dlg.querySelector('input[name="addr"]:checked') || {}).value;
      const ok = await act('/api/settings', { advertise_ip: ip, tracker_url: $('#nw-tracker', dlg).value.trim() }, 'Network settings saved');
      if (ok) closeDialog();
    }
  });
}

function openTorrentDialog() {
  const dlg = openDialog(`${dlgHead('Open a .torrent.json')}
    <div style="padding: 20px 24px; display: flex; flex-direction: column; gap: 14px">
      <div class="field"><label class="lbl" for="ot-path">From this computer</label>
        <div class="inline"><input id="ot-path" class="inp mono" placeholder="path to file.torrent.json"><button class="btn btn-ghost" data-browse>Browse</button><button class="btn btn-primary" data-open>Open</button></div></div>
      <div class="field"><label class="lbl" for="ot-file">Or upload one you received (chat, email, USB)</label><input id="ot-file" type="file" accept=".json,application/json"></div>
      <div class="help">To get it straight from the sharing computer instead, use Join swarm.</div>
    </div>
    <div class="dlg-foot"><div class="grow"></div><button class="btn btn-ghost" data-close>Cancel</button></div>`, 'narrow');
  const done = data => { if (data) { S.torrent = data.torrent.file_id; closeDialog(); toast('Opened ' + data.torrent.filename); } };
  dlg.addEventListener('click', async e => {
    if (e.target.closest('[data-close]')) return closeDialog();
    if (e.target.closest('[data-browse]')) browse('file', '', p => { $('#ot-path', dlg).value = p; }, n => n.endsWith('.json'));
    if (e.target.closest('[data-open]')) done(await act('/api/torrents/open', { path: $('#ot-path', dlg).value.trim() }));
  });
  $('#ot-file', dlg).onchange = async e => {
    const file = e.target.files[0]; if (!file) return;
    done(await act('/api/torrents/upload', { name: file.name, text: await file.text() }));
  };
}

async function quickSwarm() {
  const t = currentTorrent();
  if (!t.source) return toast('Quick swarm needs the original file on this computer (it starts a seeder and 3 downloaders).', true);
  if (!S.state.tracker || !S.state.tracker.running) {
    if (S.state.tracker_custom) { /* using another computer's tracker */ }
    else if (!await act('/api/tracker/start', {})) return;
  }
  const seed = await act('/api/peers/start', { file_id: t.file_id, role: 'seeder', source: t.source });
  if (seed) await act('/api/peers/start', { file_id: t.file_id, role: 'downloader', count: 3 }, 'Started a seeder and 3 downloaders');
}

// ---------- create torrent page (mockup screen 3) ----------

function drawCreate(main) {
  const c = S.create;
  main.innerHTML = `<div class="page">
    <div><h1>Create torrent</h1><div class="help" style="margin-top: 4px; font-size: 13px">Split a file into pieces, hash each one and save a <span class="mono">.torrent.json</span> that peers use to find and verify it.</div></div>
    <div class="two">
      <section class="grow card card-pad" style="display: flex; flex-direction: column; gap: 20px">
        <div class="field"><div class="lbl">Source file</div>
          <div class="drop"><div class="ico">${ICON.file}</div><div style="flex: 1; min-width: 0"><div style="font-weight: 500; word-break: break-all" id="ct-name">${esc(c.name || 'No file chosen')}</div><div class="help" id="ct-meta">${c.size != null ? bytes(c.size) + ' (' + Number(c.size).toLocaleString() + ' bytes)' : 'Choose the file you want to share.'}</div></div>
            <button class="btn btn-ghost" data-act="ct-browse">${c.path ? 'Choose another' : 'Choose file'}</button></div>
          <input class="inp mono" id="ct-path" placeholder="or paste a full path" value="${esc(c.path || '')}" aria-label="Source file path"></div>
        <div class="field"><div class="lbl">Piece size</div>${seg('psize', [[16384, '16 KiB'], [32768, '32 KiB'], [65536, '64 KiB']], c.psize || 65536)}
          <div class="help">64 KiB is the project default and the largest size peers accept. Smaller pieces mean more hashes and messages, but peers can start sharing sooner.</div></div>
        <div class="field"><label class="lbl" for="ct-out">Save torrent as</label>
          <div class="inline"><input id="ct-out" class="inp mono" value="${esc(c.out || '')}" placeholder="${esc(S.state ? S.state.workdir : '')}/torrents/…"><button class="btn btn-ghost" data-act="ct-save">Browse</button></div></div>
        <div class="inline"><button class="btn btn-primary" data-act="ct-create" id="ct-create">Create torrent</button><span class="help" id="ct-busy"></span></div>
      </section>
      <aside>
        <div class="card card-pad"><div class="cap" style="margin-bottom: 8px">Preview</div><div id="ct-preview"></div></div>
        <div id="ct-done"></div>
        <div class="card card-pad"><div class="cap" style="margin-bottom: 4px">Your torrents</div><div id="ct-recent"></div></div>
      </aside>
    </div></div>`;
  const page = main.firstElementChild;
  bindSegs(page, () => { S.create.psize = Number(segValue(page, 'psize')); updateCreate(); });
  $('#ct-path').addEventListener('change', e => { setSource(e.target.value.trim(), null); });
  $('#ct-out').addEventListener('input', e => { S.create.out = e.target.value; });
}

function setSource(path, size) {
  const c = S.create;
  c.path = path; c.name = path.split(/[\\/]/).pop(); c.size = size; c.done = null;
  const sep = S.state.workdir.includes('\\') ? '\\' : '/';
  c.out = S.state.workdir + sep + 'torrents' + sep + c.name + '.torrent.json';
  drawCreate($('#main'));
  updateCreate();
  if (size == null && path) {
    api('/api/fs?path=' + encodeURIComponent(path)).then(d => {
      const hit = d.entries.find(e => e.path === path || e.name === c.name);
      if (hit && !hit.dir) { c.size = hit.size; drawCreate($('#main')); updateCreate(); }
      else toast('that file does not exist', true);
    }).catch(e => toast(e.message, true));
  }
}

function updateCreate() {
  const c = S.create; const ps = c.psize || 65536;
  const el = $('#ct-preview'); if (!el) return;
  morph(el, `<div class="kv"><span class="muted">File name</span><span>${esc(c.name || '–')}</span></div>
    <div class="kv"><span class="muted">File size</span><span>${c.size != null ? Number(c.size).toLocaleString() + ' bytes' : '–'}</span></div>
    <div class="kv"><span class="muted">Piece size</span><span>${ps / 1024} KiB (${ps.toLocaleString()} bytes)</span></div>
    <div class="kv"><span class="muted">Pieces</span><span style="font-weight: 600">${c.size != null ? Math.max(1, Math.ceil(c.size / ps)) : '–'}</span></div>
    <div class="kv"><span class="muted">Hash</span><span>SHA-256 per piece</span></div>
    <div class="kv"><span class="muted">file_id</span><span class="mono">${c.done ? short(c.done.file_id) : 'after hashing'}</span></div>`);
  morph($('#ct-done'), c.done ? `<div class="card card-pad" style="border-color: #9ED6C0; display: flex; flex-direction: column; gap: 12px">
      <div class="inline" style="color: var(--ok); font-weight: 600">${ICON.check}Torrent saved</div>
      <div class="help">All ${c.done.num_pieces} pieces hashed. Seed it now; other computers then get it with Join swarm.</div>
      <div class="inline"><button class="btn btn-primary" data-act="ct-seed" style="flex: 1">Seed this file now</button><button class="btn btn-ghost" data-act="ct-folder">Show in folder</button></div></div>` : '');
  morph($('#ct-recent'), S.state.torrents.slice().reverse().map(x => `<div class="kv"><span class="mono small" style="text-align: left">${esc(x.filename)}</span><span class="muted">${bytes(x.file_size)}</span></div>`).join('') || '<div class="help">None yet.</div>');
}

async function createTorrent() {
  const c = S.create;
  c.path = $('#ct-path').value.trim() || c.path;
  if (!c.path) return toast('choose a source file first', true);
  $('#ct-create').disabled = true; $('#ct-busy').textContent = 'Hashing pieces…';
  try {
    const data = await api('/api/torrents/create', { source: c.path, piece_size: c.psize || 65536, output: $('#ct-out').value.trim() || null });
    c.done = data.torrent; c.size = data.torrent.file_size; S.torrent = data.torrent.file_id;
    S.state = await api('/api/state');
    toast('Torrent saved');
  } catch (e) { toast(e.message, true); }
  $('#ct-create').disabled = false; $('#ct-busy').textContent = '';
  updateCreate();
}

async function seedCreated() {
  const t = S.create.done; if (!t) return;
  if (!S.state.tracker || !S.state.tracker.running) {
    if (!S.state.tracker_custom && !await act('/api/tracker/start', {}, 'Tracker started on this computer')) return;
  }
  location.hash = 'swarms';
  setTimeout(() => addPeerDialog({ file_id: t.file_id, role: 'seeder', source: t.source }), 50);
}

// ---------- experiments page (mockup screen 4) ----------

function drawExperiments(main) {
  main.innerHTML = `<div class="page">
    <div class="titlerow"><div><h1>Experiments</h1><div class="help" style="margin-top: 4px; font-size: 13px">Runs the assignment experiments on a 32 MiB test file on this computer, then collects the logs and draws the figures.</div></div>
      <button class="btn btn-ghost" data-act="ex-folder">Open results folder</button></div>
    <div id="ex-warn"></div>
    <div class="two" style="flex-direction: row-reverse">
      <section class="grow" style="display: flex; flex-direction: column; gap: 16px">
        <div class="card card-pad"><div class="inline" style="margin-bottom: 12px"><div style="flex: 1; font-weight: 600">Distribution time (s)</div><div class="help" id="ex-sample"></div></div><div id="ex-bars"></div></div>
        <div class="card card-pad"><div class="inline" style="margin-bottom: 12px"><div style="flex: 1; font-weight: 600">Figures</div></div><div id="ex-figs" class="figs"></div></div>
      </section>
      <aside><section class="card" style="overflow: hidden">
        <div class="inline" style="padding: 16px"><div class="cap" style="flex: 1">Configurations</div><div class="help" id="ex-count"></div></div>
        <div id="ex-cfgs"></div>
        <div class="inline" style="padding: 14px 16px; border-top: 1px solid var(--line-2)"><div style="flex: 1; font-size: 13px">Repeats per config</div>
          <button class="btn btn-ghost btn-icon btn-sm" aria-label="Fewer repeats" data-rep="-1">${ICON.minus}</button><div id="ex-rep" style="width: 24px; text-align: center; font-weight: 600"></div><button class="btn btn-ghost btn-icon btn-sm" aria-label="More repeats" data-rep="1">${ICON.more}</button></div>
        <div style="padding: 0 16px 16px; display: flex; flex-direction: column; gap: 10px">
          <div class="help" id="ex-est"></div><div id="ex-prog"></div>
          <div class="inline"><button class="btn btn-primary" style="flex: 1" data-act="ex-run" id="ex-run">Run selected</button><button class="btn btn-ghost" data-act="ex-stop">Stop</button></div>
        </div></section></aside>
    </div></div>`;
  const page = main.firstElementChild;
  page.addEventListener('change', e => {
    const box = e.target.closest('[data-cfg]'); if (!box) return;
    if (box.checked) S.expSel.add(box.dataset.cfg); else S.expSel.delete(box.dataset.cfg);
    updateExperiments(true);
  });
  page.addEventListener('click', e => {
    const r = e.target.closest('[data-rep]'); if (r) { S.expRepeats = Math.max(1, Math.min(5, S.expRepeats + Number(r.dataset.rep))); updateExperiments(true); }
  });
  api('/api/experiments').then(d => { S.exp = d; updateExperiments(true); }).catch(e => toast(e.message, true));
}

function updateExperiments(full) {
  const x = S.exp; if (!x || !$('#ex-bars')) return;
  if (!S.expSel) S.expSel = new Set(x.configs.map(c => c.name));
  const job = x.job || {};
  const warn = [];
  if (!x.available) warn.push(note('bad', 'Experiments need the project folder (run the GUI from the repository checkout).'));
  if (x.missing.length) warn.push(note('warn', `Install the experiment libraries first: <span class="mono">python -m pip install -e ".[experiments]"</span> (missing ${x.missing.map(esc).join(', ')}).`));
  morph($('#ex-warn'), warn.join(''));
  if (full || !$('#ex-cfgs').innerHTML) {
    $('#ex-cfgs').innerHTML = x.configs.map(c => `<label class="cfg"><input type="checkbox" data-cfg="${c.name}" ${S.expSel.has(c.name) ? 'checked' : ''}><span class="mono" style="flex: 1; font-size: 12px">${c.name}</span><span class="help">${esc(c.desc)}</span></label>`).join('');
  }
  const n = S.expSel.size;
  $('#ex-count').textContent = `${n} of ${x.configs.length} selected`;
  $('#ex-rep').textContent = S.expRepeats;
  $('#ex-est').textContent = `${n * S.expRepeats} runs, about ${Math.max(1, Math.round(n * S.expRepeats * 30 / 60))} min. Keep the laptop plugged in and idle; stop your peers first.`;
  const running = job.status === 'running';
  const pct = job.planned ? Math.round(100 * job.done / job.planned) : 0;
  morph($('#ex-prog'), job.status && job.status !== 'idle' ? `<div class="progress"><div class="inline small"><span style="flex: 1">${running ? `Run ${Math.min(job.done + 1, job.planned)} of ${job.planned}` : esc(job.status)} · ${esc(job.message || '')}</span></div>
      <div class="bar"><div style="width: ${pct}%"></div></div>${job.lines && job.lines.length ? `<div class="lines">${esc(job.lines.slice(-6).join('\n'))}</div>` : ''}</div>` : '');
  $('#ex-run').disabled = running || !n || !x.available || x.missing.length > 0;
  const max = Math.max(1, ...x.results.map(r => r.max));
  $('#ex-sample').textContent = x.results.length ? `mean of successful repeats; line shows min to max` : '';
  morph($('#ex-bars'), x.results.length ? `<div class="bars" role="img" aria-label="Distribution time per configuration">${x.results.map(r => `<div><span class="mono" style="color: var(--ink-2)">${esc(r.name)}</span>
      <div class="track"><div class="fill" style="width: ${100 * r.mean / max}%"></div>${r.n > 1 ? `<div class="whisk" style="left: ${100 * r.min / max}%; width: ${100 * (r.max - r.min) / max}%"></div>` : ''}</div>
      <span class="num">${r.mean.toFixed(1)} <span class="muted">×${r.n}</span></span></div>`).join('')}</div>` : '<div class="help">No results yet. Run some configurations.</div>');
  const figs = x.figures.map(f => `<button class="fig" data-fig="${esc(f)}"><img src="/api/experiments/figures/${encodeURIComponent(f)}?v=${esc(job.status || '')}${job.done || 0}" alt="${esc(f)}" loading="lazy"><span>${esc(f.replace(/^fig(\d)_/, '$1 · ').replace(/_/g, ' ').replace('.png', ''))}</span></button>`).join('');
  morph($('#ex-figs'), figs || '<div class="help">Figures appear here after a run.</div>');
}

function figureDialog(name) {
  const dlg = openDialog(`${dlgHead(esc(name))}<div class="lightbox" style="padding: 16px"><img src="/api/experiments/figures/${encodeURIComponent(name)}" alt="${esc(name)}"></div>`);
  dlg.addEventListener('click', e => { if (e.target.closest('[data-close]') || e.target === dlg) closeDialog(); });
}

// ---------- one click handler for the page ----------

document.addEventListener('click', async e => {
  const tab = e.target.closest('[data-torrent]');
  if (tab) { S.torrent = tab.dataset.torrent; S.peer = null; return render(); }
  const row = e.target.closest('[data-peer]');
  if (row) { S.peer = row.dataset.peer; S.state = await api('/api/state?peer=' + encodeURIComponent(S.peer)); return render(); }
  const fig = e.target.closest('[data-fig]');
  if (fig) return figureDialog(fig.dataset.fig);
  const btn = e.target.closest('[data-act]'); if (!btn) return;
  const a = btn.dataset.act; const t = S.state && currentTorrent();
  const sel = S.state && S.state.peers.find(p => p.peer_id === S.peer);
  switch (a) {
    case 'tracker-start': return act('/api/tracker/start', {}, 'Tracker started on this computer');
    case 'tracker-stop': return act('/api/tracker/stop', {}, 'Tracker stopped');
    case 'network': return networkDialog();
    case 'join': return joinDialog();
    case 'share': return shareDialog();
    case 'open-torrent': return openTorrentDialog();
    case 'add-peer': return addPeerDialog();
    case 'quick': return quickSwarm();
    case 'stop-all': return act('/api/peers/stop_all', { file_id: t.file_id }, 'Stopping all peers');
    case 'stop-peer': return act('/api/peers/stop', { peer_id: S.peer });
    case 'restart-peer': return act('/api/peers/restart', { peer_id: S.peer }, 'Restarted ' + S.peer);
    case 'remove-peer': S.peer = null; return act('/api/peers/remove', { peer_id: sel.peer_id });
    case 'open-folder': return act('/api/open_folder', { path: sel.folder });
    case 'goto-create': location.hash = 'create'; return;
    case 'ct-browse': return browse('file', S.create.path || '', (p, size) => setSource(p, size));
    case 'ct-save': return browse('save', $('#ct-out').value, p => { S.create.out = p; $('#ct-out').value = p; });
    case 'ct-create': return createTorrent();
    case 'ct-seed': return seedCreated();
    case 'ct-folder': return act('/api/open_folder', { path: S.create.done.path });
    case 'ex-run': { const d = await act('/api/experiments/run', { configs: Array.from(S.expSel), repeats: S.expRepeats }, 'Experiments started'); if (d) { S.exp = d; updateExperiments(); } return; }
    case 'ex-stop': { const d = await act('/api/experiments/stop', {}); if (d) { S.exp = d; updateExperiments(); } return; }
    case 'ex-folder': return S.exp && S.exp.results_dir && act('/api/open_folder', { path: S.exp.results_dir });
  }
});

setView(location.hash.slice(1) || 'swarms');
poll();
