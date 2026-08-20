(() => {
  'use strict';

  // ═══════════════════════════════════════════════════════════════════
  // 渊行站 · 会员登录门禁（2026-08-20）
  //   · 注册：开放手机号注册（存浏览器 localStorage）
  //   · 登录：优先后端 Worker(若可达) → 本地注册账号 → 管理员预置 MEMBERS
  //   · 管理员预置账号改 MEMBERS
  // ═══════════════════════════════════════════════════════════════════
  const USERS_KEY = 'yafco_users_v1';      // 本地注册用户 {手机号: sha256(密码)}
  const PHONE_RE = /^1\d{10}$/;            // 手机号格式
  const MEMBERS = Object.freeze({           // 管理员预置账号（后端不可达时兜底）
    'admin': '9c010f134b519e5e17a12ef346bf3ba811a6bc57c422fcfbdba3b491791b972b',  // AbyssYafco2026（请改）
  });
  const AUTH_API = 'https://auth.abysstrades.xyz';
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
    // 2026-08-20：暂时免费开放（登录门禁代码已备，过几天再启用）
    const p = shanghaiParts();
    const date = `${p.year}-${p.month}-${p.day}`;
    return { mode: 'free', slot: `${date}:free`, title: '渊行', message: '开放访问。' };
  }

  async function digest(value) {
    const bytes = new TextEncoder().encode(value);
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    return [...new Uint8Array(hash)].map(byte => byte.toString(16).padStart(2, '0')).join('');
  }

  function getUsers() {
    try { return JSON.parse(localStorage.getItem(USERS_KEY) || '{}'); } catch (_) { return {}; }
  }
  function saveUsers(u) { try { localStorage.setItem(USERS_KEY, JSON.stringify(u)); } catch (_) {} }

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

  async function serverLogin(username, password) {
    try {
      const resp = await fetch(`${AUTH_API}/api/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }), signal: AbortSignal.timeout(6000),
      });
      const data = await resp.json().catch(() => ({}));
      return data.ok ? { ok: true } : { ok: false, msg: data.msg || '登录失败' };
    } catch (_) { return null; }  // Worker 不可达 → 走本地
  }

  document.addEventListener('DOMContentLoaded', () => {
    let current = enforce();
    const form = document.getElementById('accessForm');
    const input = document.getElementById('accessPassword');
    const userInput = document.getElementById('accessUsername');
    const toggle = document.getElementById('accessToggle');
    const submit = document.getElementById('accessSubmit');
    const title = document.getElementById('accessTitle');
    const message = document.getElementById('accessMessage');
    let isRegister = false;
    if (!form || !input || !userInput) return;

    function renderMode() {
      submit.textContent = isRegister ? '注册并进入' : '进入渊行';
      toggle.textContent = isRegister ? '已有账号？登录' : '没有账号？注册';
      title.textContent = isRegister ? '渊行 · 会员注册' : '渊行 · 会员登录';
      message.textContent = isRegister ? '手机号注册即可进入（谁都能注册）。' : '输入手机号+密码登录。';
    }
    if (toggle) toggle.addEventListener('click', () => { isRegister = !isRegister; renderMode(); });

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

      const users = getUsers();
      let ok = false, failMsg = '';

      if (isRegister) {
        if (!PHONE_RE.test(username)) return showGate(current, '请输入正确的11位手机号。');
        if (MEMBERS[username] || users[username]) return showGate(current, '该手机号已注册，请直接登录。');
        users[username] = await digest(password);
        saveUsers(users);
        ok = true;
      } else {
        const localHash = MEMBERS[username] || users[username];
        if (localHash) {
          ok = await digest(password) === localHash;
          failMsg = '密码不正确。';
        } else {
          const srv = await serverLogin(username, password);  // 后端（未部署/被墙时 null）
          if (srv === null) failMsg = '账号不存在，请先注册。';
          else { ok = srv.ok; failMsg = srv.msg || '登录失败。'; }
        }
      }

      if (!ok) {
        const count = (record.count || 0) + 1;
        const lockUntil = count >= 5 ? now + Math.min(300000, 30000 * (count - 4)) : 0;
        localStorage.setItem(FAILURE_KEY, JSON.stringify({ count, lockUntil }));
        return showGate(current, failMsg + (lockUntil ? `（锁定 ${Math.ceil(lockUntil / 1000)} 秒）` : ''));
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
