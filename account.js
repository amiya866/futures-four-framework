/* 渊行账户前端模块（2026-08-14）：手机号注册登录 + 模拟持仓。
   后端：scripts/account_server.py（本机 127.0.0.1:8790，公网暴露后改 ACCOUNT_API）。
   离线时按钮置灰提示，不影响行情功能。 */

const ACCOUNT_API_LOCAL = 'http://127.0.0.1:8790';
const ACCOUNT_API_REMOTE = 'https://employed-inkjet-sharon-fruit.trycloudflare.com';
let ACCOUNT_API = ACCOUNT_API_LOCAL;
/* 本地模式(2026-08-16): 后端不可达时模拟仓落 localStorage, PWA/静态站也能用 */
const POS_KEY = 'yafco_positions_local';
const localPos = {
  load() { try { return JSON.parse(localStorage.getItem(POS_KEY) || '[]'); } catch (_) { return []; } },
  save(list) { localStorage.setItem(POS_KEY, JSON.stringify(list.slice(0, 60))); },
};
function useLocal() { return !account.online; }
let _acctReadyResolve; const acctReady = new Promise(r => { _acctReadyResolve = r; });
function posList() { return useLocal() ? localPos.load() : account.positions; }
const account = { token: localStorage.getItem('yafco_acct_token') || '', name: localStorage.getItem('yafco_acct_name') || '', positions: [], online: true };

async function acctReq(path, body, auth) {
  const opt = body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {};
  if (auth) opt.headers = { ...(opt.headers || {}), Authorization: `Bearer ${account.token}` };
  const r = await fetch(ACCOUNT_API + path, opt);
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.statusText);
  return d;
}

function acctOnline(off) { account.online = !off; const b = $('acctBtn'); if (b) b.title = off ? '账户服务离线（本机服务未启动）' : ''; }

async function acctInit() {
  try { await fetch(ACCOUNT_API_LOCAL + '/health', { signal: AbortSignal.timeout(1500) }); ACCOUNT_API = ACCOUNT_API_LOCAL; }
  catch (e) { ACCOUNT_API = ACCOUNT_API_REMOTE; }
  try { await fetch(ACCOUNT_API + '/health', { signal: AbortSignal.timeout(5000) }); acctOnline(false); } catch (e) { acctOnline(true); }
  if (account.token) {
    try { const me = await acctReq('/me', null, true); account.name = me.name; account.positions = me.positions || []; }
    catch (e) { account.token = ''; localStorage.removeItem('yafco_acct_token'); }
  }
  renderAcct();
  _acctReadyResolve();
}

function acctPnl() {
  return account.positions.filter(p => !p.open).reduce((s, p) => s + (p.pnl || 0), 0);
}

function renderAcct() {
  const b = $('acctBtn'); if (!b) return;
  const pb = $('posBtn'); if (pb) pb.classList.toggle('hidden', !account.token && !useLocal());
  if (account.token) {
    const open = account.positions.filter(p => p.open).length;
    const pnl = acctPnl();
    b.innerHTML = `${account.name} · 持仓${open} · 累计盈亏 <b class="${pnl >= 0 ? 'tone-up' : 'tone-down'}">${pnl >= 0 ? '+' : ''}${fmt(pnl, 0)}</b>`;
   } else if (useLocal()) {
    const list = localPos.load(), open = list.filter(p => p.open).length;
    const pnl = list.filter(p => !p.open).reduce((s, p) => s + (p.pnl || 0), 0);
    b.innerHTML = `本地模式 · 持仓${open} · 累计盈亏 <b class="${pnl >= 0 ? 'tone-up' : 'tone-down'}">${pnl >= 0 ? '+' : ''}${fmt(pnl, 0)}</b>`;
  } else {
    b.textContent = account.online ? '登录 / 注册' : '账户离线';
  }
}

function openAcctModal() {
  const m = $('acctModal'); if (!m) return;
  m.classList.remove('hidden');
  $('acctPhone').value = ''; $('acctPass').value = ''; $('acctName').value = '';
  $('acctError').textContent = ''; $('acctPhone').focus();
}

async function acctSubmit() {
  const phone = $('acctPhone').value.trim(), password = $('acctPass').value, name = $('acctName').value.trim();
  const err = $('acctError');
  err.textContent = '';
  try {
    try {
      const r = await acctReq('/login', { phone, password });
      account.token = r.token; account.name = r.name;
    } catch (e) {
      if (!/不正确/.test(e.message)) throw e;
      await acctReq('/signup', { phone, password, name });
      const r = await acctReq('/login', { phone, password });
      account.token = r.token; account.name = r.name;
    }
    localStorage.setItem('yafco_acct_token', account.token);
    localStorage.setItem('yafco_acct_name', account.name);
    const me = await acctReq('/me', null, true);
    account.positions = me.positions || [];
    $('acctModal').classList.add('hidden');
    renderAcct(); renderPosPanel();
    toast(`欢迎，${account.name}`);
  } catch (e) { err.textContent = e.message; }
}

function acctLogout() {
  account.token = ''; account.positions = [];
  localStorage.removeItem('yafco_acct_token');
  renderAcct(); renderPosPanel(); toast('已退出账户');
}

async function openPaperPosition(side) {
  await acctReady;
  if (!account.token && !useLocal()) { openAcctModal(); return; }
  const d = state.detail; if (!d) return;
  const sym = d.product.product, price = d.quote.last;
  if (useLocal() && !account.token) {
    const list = localPos.load();
    list.unshift({ id: 'L' + Date.now().toString(36), symbol: sym, side, price, lots: 1, opened_at: new Date().toISOString(), open: true });
    localPos.save(list); renderAcct(); renderPosPanel();
    toast(`已开${side === 'long' ? '模拟多单' : '模拟空单'} ${sym} @ ${fmt(price)}（本地）`);
    return;
  }
  try {
    const r = await acctReq('/positions/open', { symbol: sym, side, price, lots: 1 }, true);
    account.positions = r.positions || account.positions;
    renderAcct(); renderPosPanel();
    toast(`已开${side === 'long' ? '模拟多单' : '模拟空单'} ${sym} @ ${fmt(price)}`);
  } catch (e) { toast(e.message); }
}

async function closePaperPosition(id) {
  if (useLocal() && !account.token) {
    const list = localPos.load();
    const p = list.find(x => x.id === id);
    if (p && p.open) {
      const cur = state.detail?.quote?.last || (state.products.find(x => x.symbol === p.symbol) || {}).last || p.price;
      p.open = false; p.close_price = cur; p.closed_at = new Date().toISOString();
      p.pnl = (p.side === 'long' ? 1 : -1) * (cur - p.price) * p.lots;
      localPos.save(list);
    }
    renderAcct(); renderPosPanel(); toast('已平仓（本地）');
    return;
  }
  try {
    const r = await acctReq('/positions/close', { id, price: state.detail?.quote?.last || 0 }, true);
    account.positions = r.positions || account.positions;
    renderAcct(); renderPosPanel(); toast('已平仓');
  } catch (e) { toast(e.message); }
}

function renderPosPanel() {
  const el = $('posBody'); if (!el) return;
  const list = posList();
  if (!account.token && !useLocal()) { el.innerHTML = '<div class="pos-empty">登录后可使用模拟持仓</div>'; return; }
  if (!list.length) { el.innerHTML = '<div class="pos-empty">暂无持仓记录。在品种详情页可开模拟仓。</div>'; return; }
  el.innerHTML = list.slice(0, 30).map(p => {
    const cur = (state.products.find(x => x.symbol === p.symbol) || {}).last;
    const floatPnl = p.open && cur ? (p.side === 'long' ? 1 : -1) * (cur - p.price) * p.lots : p.pnl;
    return `<div class="pos-row ${p.open ? '' : 'closed'}"><div><b>${p.symbol}</b><small>${p.side === 'long' ? '多' : '空'} ×${p.lots} · ${p.opened_at.slice(0, 10)}</small></div>
    <span>开 ${fmt(p.price)}${p.open ? (cur ? ` · 现 ${fmt(cur)}` : '') : ` · 平 ${fmt(p.close_price)}`}</span>
    <b class="${(floatPnl || 0) >= 0 ? 'tone-up' : 'tone-down'}">${floatPnl != null ? (floatPnl >= 0 ? '+' : '') + fmt(floatPnl, 0) : '—'}</b>
    ${p.open ? `<button class="pos-close" data-id="${p.id}">平仓</button>` : '<small>已平</small>'}</div>`;
  }).join('');
}

async function togglePosPanel() {
  await acctReady;
  const p = $('posPanel'); if (!p) return;
  if (!account.token && !useLocal()) { openAcctModal(); return; }
  p.classList.toggle('hidden'); renderPosPanel();
}

/* CSP 修复(2026-08-16): script-src 'self' 拦截全部 inline onclick, 改为事件绑定。
   DOMContentLoaded 时 $ 已由 app.js 定义(script顺序 auth→account→app)。 */
window.addEventListener('DOMContentLoaded', () => {
  const on = (id, fn) => { const e = $(id); if (e) e.addEventListener('click', fn); };
  on('acctBtn', openAcctModal);
  on('posBtn', togglePosPanel);
  on('posClose', togglePosPanel);
  on('paperLong', () => openPaperPosition('long'));
  on('paperShort', () => openPaperPosition('short'));
  on('acctEnter', acctSubmit);
  on('acctCancel', () => $('acctModal').classList.add('hidden'));
  on('acctLogoutBtn', acctLogout);
  const pb = $('posBody');
  if (pb) pb.addEventListener('click', e => {
    const b = e.target.closest('.pos-close');
    if (b) closePaperPosition(b.dataset.id);
  });
});
