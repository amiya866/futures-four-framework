/* 渊行权益 stocks/app.js — 真数据(东财快照, CI构建) */
const $ = id => document.getElementById(id);
const state = { quotes: null, sector: null, stock: null, period: 'D', kline: null };
const SECTOR_NAMES = {CU:'铜',AL:'铝',ZN:'锌',PB:'铅',NI:'镍',SN:'锡',LC:'碳酸锂',SI:'工业硅',PS:'多晶硅',AO:'氧化铝',SS:'不锈钢',AU:'黄金',AG:'白银',RB:'螺纹钢',I:'铁矿石',J:'焦炭',JM:'焦煤',HC:'热卷',SC:'原油',BU:'沥青',FU:'燃料油',TA:'PTA',MA:'甲醇',SA:'纯碱',V:'PVC',PP:'聚丙烯',EG:'乙二醇',FG:'玻璃',UR:'尿素',C:'玉米',M:'豆粕',Y:'豆油',P:'棕榈油',OI:'菜油',RM:'菜粕',SR:'白糖',CF:'棉花',AP:'苹果',JD:'鸡蛋',LH:'生猪',PK:'花生',CJ:'红枣',SP:'纸浆',A:'豆一',B:'豆二',CS:'淀粉',EB:'苯乙烯',L:'塑料',PR:'瓶片',PX:'对二甲苯',PF:'短纤',PL:'丙烯',PG:'LPG',LU:'低硫燃油',BC:'国际铜',AD:'铸造铝合金',PD:'钯',PT:'铂',TF:'5年国债',TS:'2年国债',TL:'30年国债',T:'10年国债',IM:'中证1000',IC:'中证500',IF:'沪深300',IH:'上证50',RU:'橡胶',NR:'20号胶',SF:'硅铁',SM:'锰硅',LG:'原木',EC:'集运欧线'};
const cls = v => v > 0 ? 'up' : v < 0 ? 'down' : '';
const fmtP = v => v == null ? '—' : v >= 1000 ? v.toLocaleString('zh-CN', {maximumFractionDigits: 2}) : v;

async function boot() {
  const r = await fetch('../data/stocks/quotes.json?t=' + Date.now());
  try { const z = await fetch('../data/zsxq.json?t=' + Date.now()); state.essays = (await z.json()).by_symbol || {}; }
  catch (e) { state.essays = {}; }
  state.quotes = await r.json();
  $('updatedAt').textContent = '数据 ' + (state.quotes.updated_at || '').slice(5, 16) + ' · K线 ' + state.quotes.kline_ok + '只';
  renderSectors();
  renderOverview();
  bindNav();
}

function bindNav() {
  document.querySelectorAll('.nav-item[data-page]').forEach(el => el.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(x => x.classList.remove('active'));
    el.classList.add('active');
    $('page-overview').classList.toggle('hidden', el.dataset.page !== 'overview');
    $('page-stocks').classList.toggle('hidden', el.dataset.page !== 'stocks');
    if (el.dataset.page === 'stocks') renderSectorStocks();
  }));
  document.querySelectorAll('[data-per]').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('[data-per]').forEach(x => x.classList.remove('active'));
    b.classList.add('active'); state.period = b.dataset.per; renderKline();
  }));
}

function renderSectors() {
  const secs = Object.entries(state.quotes.sectors).sort((a, b) => b[1].chg - a[1].chg);
  $('sectorList').innerHTML = secs.map(([sym, s]) =>
    `<div class="sector-item" data-s="${sym}"><span>${SECTOR_NAMES[sym] || sym}</span><span class="${cls(s.chg)}">${s.chg > 0 ? '+' : ''}${s.chg}%</span></div>`).join('');
  document.querySelectorAll('.sector-item').forEach(el => el.addEventListener('click', () => {
    document.querySelectorAll('.sector-item').forEach(x => x.classList.remove('active'));
    el.classList.add('active');
    state.sector = el.dataset.s;
    document.querySelector('.nav-item[data-page="stocks"]').click();
  }));
}

function renderOverview() {
  const idx = state.quotes.indices;
  $('indexGrid').innerHTML = Object.entries(idx).map(([n, v]) =>
    `<div class="metric"><div class="metric-label">${n}</div><div class="metric-value">${fmtP(v.price)}</div><div class="${cls(v.chg)}">${v.chg > 0 ? '▲ +' : '▼ '}${v.chg}%</div></div>`).join('') +
    `<div class="metric"><div class="metric-label">股票池</div><div class="metric-value">${state.quotes.stocks.length}</div><div class="muted">56商品权益篮子</div></div>`;
  const secs = Object.entries(state.quotes.sectors).sort((a, b) => b[1].chg - a[1].chg);
  const chart = echarts.init($('sectorBar'));
  chart.setOption({
    grid: {left: 70, right: 40, top: 10, bottom: 24},
    xAxis: {type: 'value', axisLabel: {color: '#9ca3af'}, splitLine: {lineStyle: {color: '#1f2937'}}},
    yAxis: {type: 'category', inverse: true, data: secs.map(([s]) => SECTOR_NAMES[s] || s), axisLabel: {color: '#e5e7eb'}},
    series: [{type: 'bar', data: secs.map(([, v]) => ({value: v.chg, itemStyle: {color: v.chg >= 0 ? '#ef4444' : '#10b981'}})),
      label: {show: true, position: 'right', color: '#9ca3af', formatter: p => p.value + '%'}}],
    tooltip: {trigger: 'axis'}
  });
  // 冷热榜: 综合分 = 涨跌 + 流入权重 + 放量家数
  const sc = Object.entries(state.quotes.sectors).map(([s, v]) => {
    const score = v.chg + (v.inflow || 0) * 0.3 + (v.hot_n || 0) * 0.3;
    return {sym: s, ...v, score};
  }).sort((x, y) => y.score - x.score);
  const row = v => `<div class="sector-item" data-s="${v.sym}" style="cursor:pointer"><span>${SECTOR_NAMES[v.sym] || v.sym}</span><span class="muted">${(v.inflow || 0) >= 0 ? '+' : ''}${v.inflow}亿 · 放量${v.hot_n || 0}家</span><span class="${cls(v.chg)}">${v.chg > 0 ? '+' : ''}${v.chg}%</span></div>`;
  $('hotList').innerHTML = sc.slice(0, 6).map(row).join('');
  $('coldList').innerHTML = sc.slice(-6).reverse().map(row).join('');
  document.querySelectorAll('#hotList .sector-item,#coldList .sector-item').forEach(el => el.addEventListener('click', () => {
    state.sector = el.dataset.s;
    document.querySelector('.nav-item[data-page="stocks"]').click();
  }));
  renderStockTable($('allStockBody'), state.quotes.stocks);
}

function stockRow(s) {
  return `<tr class="stock-row" data-c="${s.code}"><td>${s.code.slice(2)}</td><td>${s.name}</td>` +
    ('sec' in s ? `<td>${(s.sectors || []).map(x => SECTOR_NAMES[x] || x).join('/')}</td>` : '') +
    `<td>${fmtP(s.price)}</td><td class="${cls(s.chg)}">${s.chg != null ? (s.chg > 0 ? '+' : '') + s.chg + '%' : '—'}</td>` +
    `<td>${s.turnover ?? '—'}</td><td>${s.vol_ratio ?? '—'}</td><td>${s.pe != null ? Math.round(s.pe) : '—'}</td></tr>`;
}

function renderStockTable(tbody, list) {
  const rows = [...list].sort((a, b) => (b.chg ?? -99) - (a.chg ?? -99));
  tbody.innerHTML = rows.map(s => stockRow({...s, sec: 1})).join('');
  tbody.querySelectorAll('.stock-row').forEach(r => r.addEventListener('click', () => {
    document.querySelector('.nav-item[data-page="stocks"]').click();
    loadKline(r.dataset.c);
  }));
}

function renderEssays(sym) {
  const es = (state.essays[sym] || []).slice(0, 5);
  $('essayInfo').textContent = es.length ? `${es.length} 条 · ${es[0].date}` : '';
  $('essayBody').innerHTML = es.length
    ? es.map(x => `<div style="padding:8px 0;border-bottom:1px solid var(--border)"><small class="muted">${x.date} · ${x.source || '知识星球'}</small><div><b>${x.title}</b></div><div class="muted">${(x.summary || '').slice(0, 80)}${(x.summary || '').length > 80 ? '…' : ''} <a href="${x.url}" target="_blank" style="color:var(--blue)">全文 ↗</a></div></div>`).join('')
    : '<div class="muted">该板块近半月无相关小作文</div>';
}

function renderSectorStocks() {
  const sym = state.sector || Object.keys(state.quotes.sectors)[0];
  state.sector = sym;
  $('sectorStockTitle').textContent = (SECTOR_NAMES[sym] || sym) + '板块个股';
  renderEssays(sym);
  const list = state.quotes.stocks.filter(s => (s.sectors || []).includes(sym));
  const tbody = $('sectorStockBody');
  tbody.innerHTML = list.map(s => stockRow(s)).join('');
  tbody.querySelectorAll('.stock-row').forEach(r => r.addEventListener('click', () => loadKline(r.dataset.c)));
}

async function loadKline(code) {
  const r = await fetch('../data/stocks/kline/' + code + '.json?t=' + Date.now());
  if (!r.ok) return;
  state.kline = await r.json();
  state.stock = code;
  $('klineTitle').textContent = '📈 ' + state.kline.name + ' ' + code.slice(2);
  renderKline();
}

function aggregate(bars, per) {
  if (per === 'D') return bars;
  const out = [];
  let cur = null, key = null;
  const wk = t => { const d = new Date(t); const day = (d.getDay() + 6) % 7; const th = new Date(d); th.setDate(d.getDate() - day + 3); return th.getFullYear() + '-W' + Math.ceil(((th - new Date(th.getFullYear(), 0, 1)) / 864e5 + 1) / 7); };
  for (const b of bars) {
    const k = per === 'W' ? wk(b.t) : b.t.slice(0, 7);
    if (k !== key) { if (cur) out.push(cur); key = k; cur = {t: b.t, o: b.o, c: b.c, h: b.h, l: b.l, v: b.v}; }
    else { cur.c = b.c; cur.h = Math.max(cur.h, b.h); cur.l = Math.min(cur.l, b.l); cur.v += b.v; }
  }
  if (cur) out.push(cur);
  return out;
}

function maArr(vals, n) {
  return vals.map((_, i) => i < n - 1 ? null : +(vals.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n).toFixed(2));
}

function renderKline() {
  if (!state.kline) return;
  const bars = aggregate(state.kline.bars, state.period);
  const closes = bars.map(b => b.c);
  const chart = echarts.init($('klineChart'));
  chart.setOption({
    animation: false,
    grid: [{left: 60, right: 20, top: 30, height: 250}, {left: 60, right: 20, top: 320, height: 90}],
    xAxis: [{type: 'category', data: bars.map(b => b.t), gridIndex: 0, axisLabel: {color: '#9ca3af'}},
            {type: 'category', data: bars.map(b => b.t), gridIndex: 1, axisLabel: {show: false}}],
    yAxis: [{scale: true, gridIndex: 0, axisLabel: {color: '#9ca3af'}, splitLine: {lineStyle: {color: '#1f2937'}}},
            {scale: true, gridIndex: 1, axisLabel: {color: '#9ca3af'}, splitLine: {show: false}}],
    dataZoom: [{type: 'inside', xAxisIndex: [0, 1]}, {type: 'slider', xAxisIndex: [0, 1], bottom: 0, height: 18}],
    series: [
      {type: 'candlestick', name: 'K线', data: bars.map(b => [b.o, b.c, b.l, b.h]),
       itemStyle: {color: '#ef4444', color0: '#10b981', borderColor: '#ef4444', borderColor0: '#10b981'}},
      {type: 'line', name: 'MA5', data: maArr(closes, 5), showSymbol: false, lineStyle: {width: 1, color: '#f59e0b'}},
      {type: 'line', name: 'MA20', data: maArr(closes, 20), showSymbol: false, lineStyle: {width: 1, color: '#3b82f6'}},
      {type: 'line', name: 'MA60', data: maArr(closes, 60), showSymbol: false, lineStyle: {width: 1, color: '#a855f7'}},
      {type: 'bar', name: '成交量', xAxisIndex: 1, yAxisIndex: 1, data: bars.map(b => ({value: b.v, itemStyle: {color: b.c >= b.o ? '#ef444466' : '#10b98166'}}))}
    ],
    tooltip: {trigger: 'axis'},
    legend: {textStyle: {color: '#9ca3af'}, top: 4}
  }, true);
  // MACD/RSI 副图(仅日线原生序列)
  const d = state.kline;
  const ind = echarts.init($('indicatorChart'));
  ind.setOption({
    animation: false,
    grid: [{left: 60, right: 20, top: 20, height: 150}, {left: 60, right: 20, top: 210, height: 90}],
    xAxis: [{type: 'category', data: d.bars.map(b => b.t), gridIndex: 0, axisLabel: {show: false}},
            {type: 'category', data: d.bars.map(b => b.t), gridIndex: 1, axisLabel: {color: '#9ca3af'}}],
    yAxis: [{scale: true, gridIndex: 0, axisLabel: {color: '#9ca3af'}}, {scale: true, gridIndex: 1, axisLabel: {color: '#9ca3af'}}],
    dataZoom: [{type: 'inside', xAxisIndex: [0, 1]}],
    series: [
      {type: 'bar', name: 'MACD柱', data: d.macd.map(v => ({value: v, itemStyle: {color: v >= 0 ? '#ef4444' : '#10b981'}}))},
      {type: 'line', name: 'DIF', data: d.dif, showSymbol: false, lineStyle: {width: 1, color: '#f59e0b'}},
      {type: 'line', name: 'DEA', data: d.dea, showSymbol: false, lineStyle: {width: 1, color: '#3b82f6'}},
      {type: 'line', name: 'RSI14', xAxisIndex: 1, yAxisIndex: 1, data: d.rsi, showSymbol: false, lineStyle: {width: 1.2, color: '#a855f7'}}
    ],
    tooltip: {trigger: 'axis'},
    legend: {textStyle: {color: '#9ca3af'}, top: 0}
  }, true);
}

boot().catch(e => { $('updatedAt').textContent = '数据加载失败: ' + e.message; });
