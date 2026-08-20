(() => {
  'use strict';

  // ═══════════════════════════════════════════════════════════════════
  // 渊行站 · 会员登录门禁（2026-08-20）
  // 登录走后端 Cloudflare Worker：https://auth.abysstrades.xyz/api/login
  //   （Worker 不可达时回退本地 MEMBERS 字典，保证离线/未部署时仍可用）
  // 账号由管理员在 Worker 网页管理界面管理（auth-worker/admin.html）。
  // ═══════════════════════════════════════════════════════════════════
  const AUTH_API = 'https://auth.abysstrades.xyz';
  // 本地回退账号（Worker 不可达时用；管理员仍可直接改这里）
  const MEMBERS = Object.freeze({
    'admin': '9c010f134b519e5e17a12ef346bf3ba811a6bc57c422fcfbdba3b491791b972b',  // AbyssYafco2026（请尽快改）
  });
  const SESSION_KEY = 'yafco_access_v2';
  const FAILURE_KEY = 'yafco_access_failures_v2';

  function shanghaiParts() {
    const parts = new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Shanghai', hour12: false,
      year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    }).formatToParts(new Date());
    return Object.fromEntries(parts.map(part => [part.type, part.value]));
  }

  function windowState() {
    const p = shanghaiParts();
    const date = `${p.year}-${p.month}-${p.day}`;
    return { mode: 'gated', slot: `${date}:gated`, title: '渊行 · 会员登录', message: '输入会员账号密码进入。' };
  }

  async function digest(value) {
    const bytes = new TextEncoder().encode(value);
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    return [...new Uint8Array(hash)].map(byte => byte.toString(16).padStart(2, '0')).join('');
  }

  function failures() {
    try { return JSON.parse(localStorage.getItem(FAILURE_KEY) || '{}'); } catch (_) { return {}; }
  }

  function isUnlocked(current) {
    if (current.mode === 'free') return true;
    if (current.mode === 'maintenance') return false;
    try { return JSON.parse(sessionStorage.getItem(SESSION_KEY) || '{}').slot === current.slot; } catch (_) { return false; }
  }

  function showGate(current, message) {
    const gate = document.getElementById('accessGate');
    const form = document.getElementById('accessForm');
    document.getElementById('accessTitle').textContent = current.title;
    document.getElementById('accessMessage').textContent = message || current.message;
    form.classList.toggle('hidden', current.mode === 'maintenance' || current.mode === 'free');
    gate.classList.remove('unlocked');
    document.documentElement.classList.add('access-locked');
  }

  function unlock(current) {
    const gate = document.getElementById('accessGate');
    gate.classList.add('unlocked');
    document.documentElement.classList.remove('access-locked');
    window.dispatchEvent(new CustomEvent('yafco:authorized', { detail: current }));
  }

  function enforce() {
    const current = windowState();
    const previous = window.__yafcoWindow;
    window.__yafcoWindow = current;
    if (previous && previous.slot !== current.slot) sessionStorage.removeItem(SESSION_KEY);
    if (isUnlocked(current)) unlock(current); else showGate(current);
    return current;
  }

  // 后端登录；失败(网络)返回 null → 回退本地
  async function serverLogin(username, password) {
    try {
      const resp = await fetch(`${AUTH_API}/api/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
        signal: AbortSignal.timeout(8000),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.status === 401) return { ok: false, msg: data.msg || '账号或密码不正确' };
      return data.ok ? { ok: true } : { ok: false, msg: data.msg || '登录失败' };
    } catch (_) { return null; }  // Worker 不可达
  }

  function localLogin(username, password) {
    const expected = MEMBERS[username];
    if (!expected) return { ok: false, msg: '账号不存在，请联系管理员开通。' };
    return digest(password).then(h => h === expected ? { ok: true } : { ok: false, msg: '密码不正确（本地回退）。' });
  }

  document.addEventListener('DOMContentLoaded', () => {
    let current = enforce();
    const form = document.getElementById('accessForm');
    const input = document.getElementById('accessPassword');
    const userInput = document.getElementById('accessUsername');
    if (!form || !input || !userInput) return;

    form.addEventListener('submit', async event => {
      event.preventDefault();
      current = windowState();
      const record = failures();
      const now = Date.now();
      if (record.lockUntil && now < record.lockUntil) {
        return showGate(current, `尝试过多，请 ${Math.ceil((record.lockUntil - now) / 1000)} 秒后再试。`);
      }
      const username = userInput.value.trim();
      const password = input.value;
      if (!username || !password) return showGate(current, '请输入账号和密码。');

      let result = await serverLogin(username, password);
      if (result === null) result = await localLogin(username, password);  // Worker 不可达 → 本地回退
      if (!result.ok) {
        const count = (record.count || 0) + 1;
        const lockUntil = count >= 5 ? now + Math.min(300000, 30000 * (count - 4)) : 0;
        localStorage.setItem(FAILURE_KEY, JSON.stringify({ count, lockUntil }));
        return showGate(current, (result.msg || '登录失败') + (lockUntil ? `（锁定 ${Math.ceil(lockUntil / 1000)} 秒）` : ''));
      }
      sessionStorage.setItem(SESSION_KEY, JSON.stringify({ slot: current.slot, at: now }));
      localStorage.removeItem(FAILURE_KEY);
      unlock(current);
    });
    setInterval(enforce, 30000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) enforce(); });
  });

  window.YAFCOAccess = { current: windowState, allowed: () => isUnlocked(windowState()) };
})();
