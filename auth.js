(() => {
  'use strict';

  // ═══════════════════════════════════════════════════════════════════
  // 渊行站 · 星球会员登录门禁（2026-08-20 由管理员管理账号）
  //
  // 账号由管理员维护：在下方 MEMBERS 字典里加/删条目即可放人/踢人。
  //   MEMBERS = { "用户名": "该密码的 SHA-256 十六进制" }
  // 生成密码哈希：python -c "import hashlib;print(hashlib.sha256('密码'.encode()).hexdigest())"
  // 或任选在线 SHA-256 工具。改完 push 到 main 即生效。
  //
  // ⚠️ 纯静态站无法做服务端鉴权——这是浏览器本地软门禁（账号数据在页面内）。
  //    想更安全需后端/托管鉴权，本站受静态托管限制采用此方案。
  // ═══════════════════════════════════════════════════════════════════
  const MEMBERS = Object.freeze({
    'admin': '9c010f134b519e5e17a12ef346bf3ba811a6bc57c422fcfbdba3b491791b972b',  // AbyssYafco2026（管理员，请尽快改）
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
    return { mode: 'gated', slot: `${date}:gated`, title: '渊行 · 会员登录', message: '输入星球会员账号密码进入。' };
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
      const expected = MEMBERS[username];
      if (!expected) return showGate(current, '账号不存在，请联系星球主开通。');
      if (await digest(password) !== expected) {
        const count = (record.count || 0) + 1;
        const lockUntil = count >= 5 ? now + Math.min(300000, 30000 * (count - 4)) : 0;
        localStorage.setItem(FAILURE_KEY, JSON.stringify({ count, lockUntil }));
        return showGate(current, lockUntil ? '密码错误次数过多，已暂时锁定。' : `密码不正确，还可尝试 ${5 - count} 次。`);
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
