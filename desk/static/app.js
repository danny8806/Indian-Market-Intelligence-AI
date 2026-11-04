const state = { data: null, selected: '', historyOffset: 0, historyRevision: null, equityPoints: [], equityCurve: [], candleRange: '60', candleHover: null, scannerSort: 'symbol' };
const APP_BASE = '';
const appUrl = (path) => `${APP_BASE}${path.startsWith('/') ? path : `/${path}`}`;
const TRADE_PAGE_SIZE = 25;
const byId = (id) => document.getElementById(id);
const escapeHtml = (v) => String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
async function apiFetch(url, options = {}) {
  const response = await fetch(appUrl(url), options);
  if (response.status === 401) { window.location.replace(appUrl('/login')); throw new Error('Login required'); }
  return response;
}
const fmt = (value, digits = 2) => value === null || value === undefined || Number.isNaN(Number(value)) ? '—' : Number(value).toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const rupee = (value, digits = 2) => value === null || value === undefined || Number.isNaN(Number(value)) ? '—' : `₹${fmt(value, digits)}`;
const clsPnl = (value) => Number(value) > 0 ? 'positive' : Number(value) < 0 ? 'negative' : 'neutral';
const signalClass = (signal) => signal === 'BUY' ? 'buy' : signal === 'SELL' ? 'sell' : 'wait';
const tickTime = (value) => {
  if (!value) return '';
  const dt = new Date(value);
  return new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false }).format(dt);
};

function render(data) {
  state.data = data;
  const metrics = data.metrics || {};
  const symbols = data.symbols || [];
  const selected = symbols.find((item) => item.symbol === state.selected) || symbols[0];
  if (selected) state.selected = selected.symbol;

  byId('capitalMetric').textContent = rupee(metrics.capital, 0);
  const dayPnl = byId('dayPnlMetric');
  dayPnl.textContent = rupee(metrics.day_pnl);
  dayPnl.className = `metric-value ${clsPnl(metrics.day_pnl)}`;
  byId('pnlBreakdown').textContent = `Realized ${rupee(metrics.realized_today)} · Open ${rupee(metrics.open_pnl)}`;
  byId('exposureMetric').textContent = `${rupee(metrics.deployed, 0)} / ₹10L`;
  byId('exposureMeter').style.width = `${Math.min(100, (metrics.deployed || 0) / (metrics.max_notional || 1) * 100)}%`;
  byId('positionsMetric').textContent = `${metrics.open_count || 0} / ${metrics.max_positions || 10}`;
  byId('tradesMetric').textContent = `${metrics.trade_count || 0} trades today`;
  byId('openPnlMini').textContent = rupee(metrics.open_pnl);
  byId('openPnlMini').className = clsPnl(metrics.open_pnl);
  byId('realizedPnl').textContent = rupee(metrics.realized_today);
  byId('realizedPnl').className = clsPnl(metrics.realized_today);

  renderConnection(data.connection || {});
  renderStorage(data.storage || {});
  renderScanner(symbols);
  renderChart(selected);
  renderActivity(data.activity || [], data.server_time);
  renderPositions(symbols, metrics, data.closed_trades || []);
  renderPerformance(data.performance || {});
  renderPortfolio(data.strategy || {});
  const dhanAuth = data.dhan_auth || {};
  byId('dhanAuthText').textContent = `DHAN: ${dhanAuth.state || 'UNKNOWN'}`;
  byId('dhanAuthChip').title = `${dhanAuth.message || 'Dhan token status unavailable'}${dhanAuth.expires_at ? ` · expires ${dhanAuth.expires_at}` : ''}${dhanAuth.next_refresh ? ` · refresh ${dhanAuth.next_refresh}` : ''}`;
  populateTradeSymbols(symbols);
  const revision = `${data.performance?.trade_count || 0}:${data.closed_trades?.[0]?.closed_at || ''}`;
  if (state.historyRevision !== revision) { state.historyRevision = revision; loadTradeHistory(); }
  const paperState = byId('paperState');
  const ledgerHealthy = data.storage?.ok && !data.storage?.dirty;
  paperState.textContent = !ledgerHealthy ? 'LEDGER ISSUE' : !data.strategy?.runtime_ready ? 'SIGNALS NOT READY' : data.paper_enabled ? 'ENTRIES ON' : 'ENTRIES PAUSED';
  paperState.className = ledgerHealthy && data.paper_enabled && data.strategy?.runtime_ready ? 'paper-state' : 'paper-state paused';
  paperState.title = data.storage?.message || 'Paper ledger status unavailable';
  byId('pauseButton').textContent = data.paper_enabled ? 'Pause entries' : 'Resume entries';
  byId('pauseButton').disabled = !data.strategy?.runtime_ready;
  byId('pauseButton').title = data.strategy?.runtime_ready ? '' : 'Verified news signals or market data are unavailable.';
  byId('clockText').textContent = `${tickTime(data.server_time)}:${new Date(data.server_time).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', second: '2-digit', hour12: false }).split(':').pop()} IST`;
  renderMarketStatus(data.server_time, selected?.last_tick);
}

function renderPortfolio(strategy) {
  const ready = Boolean(strategy.runtime_ready);
  const badge = byId('portfolioRuntimeState');
  badge.textContent = ready ? 'VERIFIED NEWS SIGNALS READY' : 'AWAITING VALID REPORT / DATA';
  badge.className = ready ? 'safe-chip' : 'safe-chip runtime-blocked';
  const body = byId('portfolioConfigBody');
  const rows = strategy.positions || [];
  if (!rows.length) { body.innerHTML = '<tr><td colspan="5" class="empty-row">No verified news candidates for this session.</td></tr>'; return; }
  body.innerHTML = rows.map(row => '<tr><td><b>'+escapeHtml(row.symbol)+'</b></td><td><span class="'+(row.side === 'LONG' ? 'positive' : 'negative')+'">'+escapeHtml(row.side)+' #'+Number(row.rank)+'</span></td><td>'+fmt(row.stop_loss_pct,1)+'%</td><td class="num">'+rupee(strategy.capital_per_stock,0)+'</td><td title="'+escapeHtml(row.reason || '')+'">'+escapeHtml((row.news_summary || row.reason || 'Verified event').slice(0,155))+'</td></tr>').join('');
}

function renderStorage(storage) {
  const dot = byId('storageDot');
  const label = byId('storageText');
  const chip = byId('storageChip');
  const healthy = storage.ok && !storage.dirty;
  dot.className = `status-dot${healthy ? '' : ' red'}`;
  label.textContent = healthy ? 'Ledger saved' : storage.dirty ? 'Ledger retrying' : 'Ledger unavailable';
  chip.title = storage.message || 'Paper ledger status unavailable';
  chip.setAttribute('aria-label', chip.title);
}

function renderConnection(connection) {
  const status = state.data?.strategy?.runtime_ready ? (connection.status || 'Unknown') : 'Signal feed not ready';
  const ok = status === 'Connected';
  const bad = ['Error', 'Needs login', 'Needs setup', 'History unavailable'].includes(status);
  const dotClass = ok ? '' : bad ? ' red' : ' amber';
  byId('connectionDot').className = `status-dot${dotClass}`;
  byId('footerLed').className = `status-dot${dotClass}`;
  byId('connectionText').textContent = ok ? 'Live data connected' : status;
  byId('footerStatus').textContent = state.data?.strategy?.runtime_ready ? (connection.message || 'Waiting for Dhan') : 'Waiting for verified news report or Dhan data';
  const hist = state.data?.symbols || [];
  const ready = hist.filter((item) => item.history_ready).length;
  byId('historyStatus').textContent = `15m chart data ${ready}/${hist.length || 10}`;
}

function renderMarketStatus(serverTime, lastTick) {
  const dt = new Date(serverTime);
  const parts = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(dt);
  const get = (type) => parts.find((item) => item.type === type)?.value;
  const weekday = get('weekday');
  const hour = Number(get('hour'));
  const minute = Number(get('minute'));
  const total = hour * 60 + minute;
  const open = weekday !== 'Sat' && weekday !== 'Sun' && total >= 555 && total < 930;
  byId('marketText').textContent = open ? 'Market open' : 'Market closed';
  const ageMs = lastTick ? new Date(serverTime).getTime() - new Date(lastTick).getTime() : Infinity;
  const live = open && ageMs >= 0 && ageMs <= 120_000;
  const feed = byId('chartFeedState');
  feed.className = `chart-live${live ? '' : ' historical'}`;
  feed.lastChild.textContent = live ? ' LIVE' : open ? ' NO TICK' : ' HISTORY';
}

function renderScanner(items) {
  const query = byId('searchInput').value.trim().toUpperCase();
  const filter = byId('signalFilter').value;
  const forecast = byId('forecastFilter').value;
  const positionFilter = byId('positionFilter').value;
  state.scannerSort = byId('scannerSort').value;
  const shown = items.filter((item) => (!query || `${escapeHtml(item.label)} ${escapeHtml(item.symbol)}`.toUpperCase().includes(query)) &&
    (filter === 'ALL' || item.signal === filter) && (forecast === 'ALL' || item.prediction === forecast) &&
    (positionFilter === 'ALL' || (positionFilter === 'OPEN' ? Boolean(item.position) : !item.position)));
  const sorters = {
    symbol: (a, b) => a.label.localeCompare(b.label),
    change_desc: (a, b) => compareNumeric(a.change_pct, b.change_pct, -1),
    change_asc: (a, b) => compareNumeric(a.change_pct, b.change_pct, 1),
    ltp_desc: (a, b) => compareNumeric(a.ltp, b.ltp, -1),
    pnl_desc: (a, b) => compareNumeric(a.mark?.net, b.mark?.net, -1),
  };
  shown.sort(sorters[state.scannerSort] || sorters.symbol);
  const signals = shown.filter((item) => item.signal === 'BUY' || item.signal === 'SELL').length;
  const openPositions = shown.filter((item) => item.position).length;
  byId('scannerCaption').textContent = `${shown.length} of ${items.length} stocks · ${signals} active signals · ${openPositions} open positions`;
  const body = byId('scannerBody');
  if (!shown.length) {
    body.innerHTML = '<tr><td colspan="9" class="empty-row">No symbols match those filters.</td></tr>';
    return;
  }
  body.innerHTML = shown.map((item, index) => {
    const position = item.position;
    const mark = item.mark;
    const pnl = mark?.net;
    let status = 'WAITING';
    let statusClass = '';
    if (position) { status = 'OPEN'; statusClass = 'open'; }
    else if (item.entered_today) { status = 'DONE'; statusClass = 'entered'; }
    else if (item.signal === 'BUY' || item.signal === 'SELL') { status = 'SIGNAL'; statusClass = 'entered'; }
    if (!item.ltp && item.data_error) { status = 'DATA ERROR'; statusClass = 'error'; }
    const selectedRow = item.symbol === state.selected;
    return `<tr data-symbol="${escapeHtml(item.symbol)}" tabindex="0" aria-selected="${selectedRow}" class="${selectedRow ? 'selected' : ''}">
      <td>${String(index + 1).padStart(2, '0')}</td><td class="symbol-cell">${escapeHtml(item.label)}</td>
      <td class="num">${item.ltp ? fmt(item.ltp) : '—'}</td>
      <td class="num ${clsPnl(item.change_pct)}">${item.change_pct === null || item.change_pct === undefined ? '—' : `${Number(item.change_pct) > 0 ? '+' : ''}${fmt(item.change_pct)}%`}</td>
      <td><span class="signal-chip ${signalClass(item.signal)}">${item.signal || 'WAIT'}</span></td>
      <td>${position ? `<span class="${position.side === 'LONG' ? 'positive' : 'negative'}">${position.side}</span>` : '—'}</td>
      <td class="num">${position ? fmt(position.entry_price) : '—'}</td>
      <td class="num ${mark ? clsPnl(pnl) : ''}">${mark ? `${Number(pnl) > 0 ? '+' : ''}${fmt(pnl)}` : '—'}</td>
      <td><span class="state-text ${statusClass}">${status}</span></td>
    </tr>`;
  }).join('');
  body.querySelectorAll('tr[data-symbol]').forEach((row) => {
    const selectSymbol = () => {
      state.selected = row.dataset.symbol;
      state.candleHover = null;
      render(state.data);
      byId('scannerBody').querySelector(`[data-symbol="${state.selected}"]`)?.focus();
    };
    row.addEventListener('click', selectSymbol);
    row.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectSymbol(); }
    });
  });
}

function compareNumeric(left, right, direction) {
  const leftMissing = left === null || left === undefined || !Number.isFinite(Number(left));
  const rightMissing = right === null || right === undefined || !Number.isFinite(Number(right));
  if (leftMissing !== rightMissing) return leftMissing ? 1 : -1;
  return leftMissing ? 0 : direction * (Number(left) - Number(right));
}

function renderChart(item) {
  if (!item) return;
  byId('chartSymbol').innerHTML = `${escapeHtml(item.label)} <span>· NSE · 15m</span>`;
  byId('chartPrice').textContent = item.ltp ? rupee(item.ltp) : '—';
  const changeText = item.change_pct === null || item.change_pct === undefined ? '—' : `${Number(item.change) > 0 ? '+' : ''}${rupee(item.change)} (${Number(item.change_pct) > 0 ? '+' : ''}${fmt(item.change_pct)}%)`;
  byId('chartChange').textContent = changeText;
  byId('chartChange').className = clsPnl(item.change_pct);
  byId('chartVolume').textContent = item.volume ? `VOL ${Number(item.volume).toLocaleString('en-IN')}` : 'VOL —';
  const signal = byId('chartSignal');
  signal.textContent = item.signal || 'WAIT';
  signal.className = `signal-chip ${signalClass(item.signal)}`;
  signal.title = item.signal_note || '';

  const position = item.position;
  const mark = item.mark;
  byId('positionTitle').textContent = `${escapeHtml(item.label)} · ${position ? 'Paper position' : 'No paper position'}`;
  byId('autoExit').textContent = position ? 'Stop or EOD exit 15:00 IST' : item.entered_today ? 'Daily entry used' : 'EOD exit 15:00 IST';
  byId('detailSide').textContent = position?.side || '—';
  byId('detailSide').className = position ? (position.side === 'LONG' ? 'positive' : 'negative') : '';
  byId('detailQty').textContent = position ? Number(position.quantity).toLocaleString('en-IN') : '—';
  byId('detailEntry').textContent = position ? rupee(position.entry_price) : '—';
  byId('detailPnl').textContent = mark ? rupee(mark.net) : '—';
  byId('detailPnl').className = mark ? clsPnl(mark.net) : '';
  state.candleSeries = { candles: item.candles || [], entry: position?.entry_price, stop: position?.stop_price };
  drawCandles();
}

function drawCandles() {
  const { candles = [], entry: entryPrice, stop: stopPrice } = state.candleSeries || {};
  const canvas = byId('candleChart');
  const empty = byId('chartEmpty');
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const width = rect.width, height = rect.height;
  ctx.clearRect(0, 0, width, height);
  if (!candles.length) { empty.style.display = 'flex'; return; }
  empty.style.display = 'none';
  const valid = candles.filter((bar) => Number.isFinite(Number(bar.high)) && Number.isFinite(Number(bar.low)) &&
    Number.isFinite(Number(bar.open)) && Number.isFinite(Number(bar.close)));
  const rows = state.candleRange === 'ALL' ? valid : valid.slice(-Number(state.candleRange));
  if (!rows.length) return;
  const left = 8, right = 45, top = 10, bottom = 24, volumeHeight = height * 0.18;
  const plotWidth = width - left - right, plotHeight = height - top - bottom - volumeHeight;
  const highs = rows.map((bar) => Number(bar.high));
  const lows = rows.map((bar) => Number(bar.low));
  let max = Math.max(...highs), min = Math.min(...lows);
  if (entryPrice) { max = Math.max(max, Number(entryPrice)); min = Math.min(min, Number(entryPrice)); }
  if (stopPrice) { max = Math.max(max, Number(stopPrice)); min = Math.min(min, Number(stopPrice)); }
  const padding = Math.max((max - min) * .08, max * .0008);
  max += padding; min -= padding;
  const y = (price) => top + (max - price) / (max - min) * plotHeight;
  ctx.font = '9px Segoe UI, sans-serif';
  ctx.textAlign = 'left';
  ctx.strokeStyle = '#263442'; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const yy = top + i * plotHeight / 4;
    ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(width - right, yy); ctx.stroke();
    const value = max - i * (max - min) / 4;
    ctx.fillStyle = '#77899a'; ctx.fillText(value.toFixed(2), width - right + 5, yy + 3);
  }
  if (entryPrice) {
    const entryY = y(Number(entryPrice));
    ctx.setLineDash([4, 4]); ctx.strokeStyle = '#55a8ff';
    ctx.beginPath(); ctx.moveTo(left, entryY); ctx.lineTo(width - right, entryY); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = '#82c4ff'; ctx.fillText(`Entry ${Number(entryPrice).toFixed(2)}`, left + 4, Math.max(10, entryY - 4));
  }
  if (stopPrice) {
    const stopY = y(Number(stopPrice));
    ctx.setLineDash([4, 4]); ctx.strokeStyle = '#ff6677';
    ctx.beginPath(); ctx.moveTo(left, stopY); ctx.lineTo(width - right, stopY); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = '#ff8793'; ctx.fillText(`Stop ${Number(stopPrice).toFixed(2)}`, left + 4, Math.max(10, stopY - 4));
  }
  const slot = plotWidth / rows.length;
  const candleWidth = Math.max(2, Math.min(9, slot * .55));
  const maxVolume = Math.max(1, ...rows.map((bar) => Number(bar.volume) || 0));
  rows.forEach((bar, index) => {
    const x = left + slot * index + slot / 2;
    const open = Number(bar.open), close = Number(bar.close), high = Number(bar.high), low = Number(bar.low);
    const color = close >= open ? '#21ca8b' : '#ff6677';
    ctx.strokeStyle = color; ctx.fillStyle = color;
    ctx.beginPath(); ctx.moveTo(x, y(high)); ctx.lineTo(x, y(low)); ctx.stroke();
    const bodyTop = Math.min(y(open), y(close));
    const bodyHeight = Math.max(1.3, Math.abs(y(open) - y(close)));
    ctx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyHeight);
    const volume = Number(bar.volume) || 0;
    const volumeY = top + plotHeight + (volumeHeight * (1 - volume / maxVolume));
    ctx.globalAlpha = .38; ctx.fillRect(x - candleWidth / 2, volumeY, candleWidth, top + plotHeight + volumeHeight - volumeY); ctx.globalAlpha = 1;
  });
  if (state.candleHover && state.candleHover.index >= 0 && state.candleHover.index < rows.length && byId('crosshairToggle').getAttribute('aria-pressed') === 'true') {
    const hover = state.candleHover;
    const x = left + slot * hover.index + slot / 2;
    const yy = Math.max(top, Math.min(top + plotHeight, hover.y));
    ctx.save(); ctx.setLineDash([3, 4]); ctx.strokeStyle = '#a8c9e088'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + plotHeight); ctx.moveTo(left, yy); ctx.lineTo(width - right, yy); ctx.stroke(); ctx.restore();
    const bar = rows[hover.index];
    const tooltip = byId('candleTooltip');
    tooltip.textContent = `${bar.time?.slice(0, 16).replace('T', ' ') || 'Candle'} · O ${fmt(bar.open)}  H ${fmt(bar.high)}  L ${fmt(bar.low)}  C ${fmt(bar.close)}  V ${Number(bar.volume || 0).toLocaleString('en-IN')}`;
    tooltip.style.left = `${Math.max(12, Math.min(width - 12, x))}px`;
    tooltip.classList.add('visible');
  } else {
    byId('candleTooltip').classList.remove('visible');
  }
  ctx.fillStyle = '#748597';
  const first = rows[0].time?.slice(11, 16) || '';
  const last = rows[rows.length - 1].time?.slice(11, 16) || '';
  byId('chartRangeCaption').textContent = `${rows.length} candles`;
  ctx.fillText(first, left, height - 6);
  ctx.textAlign = 'right'; ctx.fillText(last, width - right, height - 6);
}

function renderActivity(items, serverTime) {
  const target = byId('activityList');
  const today = String(serverTime || '').slice(0, 10);
  const todays = items.filter((item) => item.time?.slice(0, 10) === today && ['SIGNAL', 'ENTRY', 'EXIT', 'SKIP'].includes(item.kind)).slice(0, 8);
  if (!todays.length) { target.innerHTML = '<div class="empty-row">No signals recorded today.</div>'; return; }
  target.innerHTML = todays.map((item) => {
    const side = item.message.includes('BUY') || item.message.includes('LONG') || item.message.includes('UP') ? 'buy' : item.message.includes('SELL') || item.message.includes('SHORT') || item.message.includes('DOWN') ? 'sell' : 'wait';
    const time = tickTime(item.time);
    const shortMessage = item.message.replace(' confirmed; paper entry at signal candle close', ' confirmed').replace('Paper ', 'Paper ');
    return `<div class="activity-item"><span class="activity-time">${time}</span><span class="activity-symbol">${escapeHtml(item.symbol)}</span><span class="signal-chip ${side}">${item.kind === 'SIGNAL' ? (side === 'buy' ? 'BUY' : 'SELL') : item.kind}</span><span class="activity-note">${escapeHtml(shortMessage)}</span></div>`;
  }).join('');
}

function renderPositions(symbols, metrics, closedTrades) {
  const open = symbols.filter((item) => item.position);
  const body = byId('positionsBody');
  if (!open.length) {
    body.innerHTML = '<tr><td colspan="6" class="empty-row">No open paper positions</td></tr>';
  } else {
    body.innerHTML = open.map((item) => `<tr>
      <td>${escapeHtml(item.label)}</td><td class="${item.position.side === 'LONG' ? 'positive' : 'negative'}">${item.position.side}</td>
      <td class="num">${Number(item.position.quantity).toLocaleString('en-IN')}</td><td class="num">${fmt(item.position.entry_price)}</td>
      <td class="num">${item.ltp ? fmt(item.ltp) : '—'}</td><td class="num ${clsPnl(item.mark?.net)}">${item.mark ? fmt(item.mark.net) : '—'}</td>
    </tr>`).join('');
  }
  const recent = closedTrades.slice(0, 8);
  byId('closedTradeCount').textContent = String(recent.length);
  const closedBody = byId('closedTradesBody');
  if (!recent.length) {
    closedBody.innerHTML = '<tr><td colspan="6" class="empty-row">No closed paper trades</td></tr>';
    return;
  }
  closedBody.innerHTML = recent.map((trade) => `<tr>
    <td>${escapeHtml(trade.label || trade.symbol)}</td><td class="${trade.side === 'LONG' ? 'positive' : 'negative'}">${trade.side}</td>
    <td class="num">${Number(trade.quantity).toLocaleString('en-IN')}</td><td class="num">${fmt(trade.entry_price)}</td>
    <td class="num">${fmt(trade.exit_price)}</td><td class="num ${clsPnl(trade.net_pnl)}">${fmt(trade.net_pnl)}</td>
  </tr>`).join('');
}

function renderPerformance(perf) {
  const set = (id, value, colorValue = null) => {
    const node = byId(id); node.textContent = value;
    if (colorValue !== null) node.className = clsPnl(colorValue);
  };
  set('perfReturn', rupee(perf.net_profit || 0), perf.net_profit || 0);
  set('perfReturnPct', `${Number(perf.total_return_pct || 0).toFixed(3)}% of starting capital`);
  set('perfWinRate', `${Number(perf.win_rate || 0).toFixed(2)}%`);
  set('perfTradeSplit', `${perf.wins || 0} wins · ${perf.losses || 0} losses · ${perf.breakeven || 0} flat · ${perf.trade_count || 0} closed`);
  set('perfProfitFactor', perf.profit_factor === null || perf.profit_factor === undefined ? '—' : String(perf.profit_factor));
  set('perfDrawdown', rupee(perf.max_drawdown || 0), -(perf.max_drawdown || 0));
  set('perfDrawdownPct', `${Number(perf.max_drawdown_pct || 0).toFixed(3)}% · daily realized peak-to-trough`);
  set('perfGross', `${rupee(perf.gross_profit || 0)} / ${rupee(perf.gross_loss || 0)}`);
  set('perfFees', perf.estimated_fees == null ? 'Not modeled' : rupee(perf.estimated_fees), 0);
  set('perfAvgWinLoss', `${rupee(perf.average_win || 0)} / ${rupee(perf.average_loss || 0)}`);
  set('perfOpenPnl', rupee(perf.open_pnl || 0), perf.open_pnl || 0);
  set('perfEquityReturn', `Return including open P&L: ${Number(perf.equity_return_pct || 0).toFixed(3)}%`);
  byId('tradeHistoryCount').textContent = `${Number(perf.trade_count || 0).toLocaleString('en-IN')} TRADES`;

  const rows = perf.by_symbol || [];
  byId('symbolPerformanceBody').innerHTML = rows.length ? rows.map((row) => `<tr>
    <td>${row.symbol}</td><td class="num">${row.trades}</td><td class="num">${Number(row.win_rate).toFixed(1)}%</td>
    <td class="num ${clsPnl(row.net_pnl)}">${rupee(row.net_pnl)}</td>
  </tr>`).join('') : '<tr><td colspan="4" class="empty-row">No closed trades yet</td></tr>';
  state.equityCurve = perf.equity_curve || [];
  drawEquity(state.equityCurve);
}

function drawEquity(curve) {
  const canvas = byId('equityChart'), empty = byId('equityEmpty');
  const rect = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr)); canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  const ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const width = rect.width, height = rect.height;
  ctx.clearRect(0, 0, width, height);
  const startDate = byId('equityStart').value, endDate = byId('equityEnd').value;
  if (startDate && endDate && startDate > endDate) {
    state.equityPoints = []; empty.style.display = 'flex'; empty.textContent = 'Start date must be on or before end date.';
    byId('equityRange').textContent = 'Invalid date range'; return;
  }
  const visible = curve.filter((point) => (!startDate || point.date >= startDate) && (!endDate || point.date <= endDate));
  if (!visible.length) {
    state.equityPoints = []; empty.style.display = 'flex';
    empty.textContent = curve.length ? 'No realized trades fall inside this date range.' : 'Close paper trades to build the equity curve.';
    byId('equityRange').textContent = curve.length ? 'No trades in range' : 'No closed days'; return;
  }
  empty.style.display = 'none';
  empty.textContent = 'Close paper trades to build the equity curve.';
  const firstIndex = curve.indexOf(visible[0]);
  const openingPoint = firstIndex > 0
    ? { date: `Before ${visible[0].date}`, equity: Number(curve[firstIndex - 1].equity) }
    : { date: 'Starting balance', equity: Number(state.data?.metrics?.capital || 1_000_000) };
  const points = [openingPoint, ...visible.map((point) => ({ date: point.date, equity: Number(point.equity), dailyPnl: Number(point.daily_pnl) }))];
  const values = points.map((point) => point.equity);
  state.equityPoints = points;
  const minValue = Math.min(...values), maxValue = Math.max(...values);
  const pad = Math.max((maxValue - minValue) * .18, 100);
  const low = minValue - pad, high = maxValue + pad;
  const left = 46, right = 10, top = 12, bottom = 23;
  const x = (index) => left + (values.length < 2 ? (width - left - right) / 2 : index * (width - left - right) / (values.length - 1));
  const y = (value) => top + (high - value) * (height - top - bottom) / (high - low);
  ctx.font = '9px Segoe UI, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
  for (let i = 0; i <= 3; i++) {
    const value = high - i * (high - low) / 3, yy = y(value);
    ctx.strokeStyle = '#263442'; ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(width - right, yy); ctx.stroke();
    ctx.fillStyle = '#8293a3'; ctx.fillText(`₹${Math.round(value / 1000)}k`, 2, yy);
  }
  ctx.beginPath(); values.forEach((value, index) => index ? ctx.lineTo(x(index), y(value)) : ctx.moveTo(x(index), y(value)));
  ctx.lineTo(x(values.length - 1), height - bottom); ctx.lineTo(x(0), height - bottom); ctx.closePath();
  const gradient = ctx.createLinearGradient(0, top, 0, height - bottom); gradient.addColorStop(0, '#31bd8b44'); gradient.addColorStop(1, '#31bd8b00');
  ctx.fillStyle = gradient; ctx.fill();
  ctx.beginPath(); values.forEach((value, index) => index ? ctx.lineTo(x(index), y(value)) : ctx.moveTo(x(index), y(value)));
  ctx.strokeStyle = '#42d3a0'; ctx.lineWidth = 2; ctx.stroke();
  const first = visible[0].date, last = visible[visible.length - 1].date;
  ctx.fillStyle = '#8293a3'; ctx.textBaseline = 'alphabetic'; ctx.fillText(first, left, height - 5);
  ctx.textAlign = 'right'; ctx.fillText(last, width - right, height - 5);
  byId('equityRange').textContent = `${visible.length} session${visible.length === 1 ? '' : 's'} · ${first} to ${last}`;
}

function showTradeHistory(outcome) {
  byId('tradeSymbolFilter').value = '';
  byId('tradeSideFilter').value = '';
  byId('tradeStartFilter').value = '';
  byId('tradeEndFilter').value = '';
  byId('tradeOutcomeFilter').value = outcome;
  state.historyOffset = 0; state.expandedTradeId = null;
  loadTradeHistory();
  document.getElementById('tradeHistoryPanel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function candleRows() {
  const candles = (state.candleSeries?.candles || []).filter((bar) => Number.isFinite(Number(bar.high)) && Number.isFinite(Number(bar.low)) &&
    Number.isFinite(Number(bar.open)) && Number.isFinite(Number(bar.close)));
  return state.candleRange === 'ALL' ? candles : candles.slice(-Number(state.candleRange));
}

const equityCanvas = byId('equityChart');
const equityTooltip = byId('equityTooltip');
equityCanvas.addEventListener('pointermove', (event) => {
  const bounds = equityCanvas.getBoundingClientRect();
  const left = 46, right = 10, plotWidth = Math.max(1, bounds.width - left - right);
  if (!state.equityPoints.length || event.clientX < bounds.left + left || event.clientX > bounds.right - right) {
    equityTooltip.classList.remove('visible');
    return;
  }
  const x = event.clientX - bounds.left;
  const index = Math.max(0, Math.min(state.equityPoints.length - 1, Math.round((x - left) / plotWidth * (state.equityPoints.length - 1))));
  const point = state.equityPoints[index];
  equityTooltip.textContent = `${point.date} · ${rupee(point.equity, 0)}${point.dailyPnl === undefined ? '' : ` · Day ${rupee(point.dailyPnl, 0)}`}`;
  equityTooltip.style.left = `${Math.max(78, Math.min(bounds.width - 78, x))}px`;
  equityTooltip.classList.add('visible');
});
equityCanvas.addEventListener('pointerleave', () => equityTooltip.classList.remove('visible'));

const candleCanvas = byId('candleChart');
const candleTooltip = byId('candleTooltip');
candleCanvas.addEventListener('pointermove', (event) => {
  if (byId('crosshairToggle').getAttribute('aria-pressed') !== 'true') return;
  const bounds = candleCanvas.getBoundingClientRect();
  const left = 8, right = 45, top = 10, bottom = 24, volumeHeight = bounds.height * .18;
  const plotWidth = bounds.width - left - right;
  const plotHeight = bounds.height - top - bottom - volumeHeight;
  const px = event.clientX - bounds.left, py = event.clientY - bounds.top;
  const rows = candleRows(), slot = plotWidth / Math.max(1, rows.length);
  if (!rows.length || px < left || px > bounds.width - right || py < top || py > top + plotHeight) {
    state.candleHover = null; candleTooltip.classList.remove('visible'); drawCandles(); return;
  }
  state.candleHover = { index: Math.max(0, Math.min(rows.length - 1, Math.floor((px - left) / slot))), y: py };
  drawCandles();
});
candleCanvas.addEventListener('pointerleave', () => { state.candleHover = null; candleTooltip.classList.remove('visible'); drawCandles(); });
candleCanvas.addEventListener('wheel', (event) => {
  const ranges = ['30', '60', '120', 'ALL'];
  const index = Math.max(0, ranges.indexOf(state.candleRange));
  const next = Math.max(0, Math.min(ranges.length - 1, index + (event.deltaY > 0 ? 1 : -1)));
  if (next === index) return;
  event.preventDefault();
  state.candleRange = ranges[next]; state.candleHover = null; setActiveCandleRange(); drawCandles();
}, { passive: false });

function setActiveCandleRange() {
  document.querySelectorAll('[data-candle-range]').forEach((button) => {
    const active = button.dataset.candleRange === state.candleRange;
    button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));
  });
}

function populateTradeSymbols(symbols) {
  const select = byId('tradeSymbolFilter');
  if (select.options.length > 1) return;
  symbols.forEach((item) => { const option = document.createElement('option'); option.value = item.label; option.textContent = item.label; select.append(option); });
}

function tradeTime(value) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
}

async function loadTradeHistory() {
  const params = new URLSearchParams({ offset: String(state.historyOffset), limit: String(TRADE_PAGE_SIZE) });
  const symbol = byId('tradeSymbolFilter').value, side = byId('tradeSideFilter').value;
  const outcome = byId('tradeOutcomeFilter').value, start = byId('tradeStartFilter').value, end = byId('tradeEndFilter').value;
  if (symbol) params.set('symbol', symbol); if (side) params.set('side', side); if (outcome) params.set('outcome', outcome);
  if (start) params.set('start', start); if (end) params.set('end', end);
  const body = byId('tradeHistoryBody');
  try {
    const response = await apiFetch(`/api/trades?${params}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`History request failed (${response.status})`);
    const result = await response.json(); renderTradeHistory(result);
  } catch (_) { body.innerHTML = '<tr><td colspan="11" class="empty-row">Trade history is temporarily unavailable.</td></tr>'; }
}

function renderTradeHistory(result) {
  const body = byId('tradeHistoryBody'), trades = result.trades || [], total = Number(result.total || 0);
  if (!trades.length) body.innerHTML = '<tr><td colspan="11" class="empty-row">No trades match these filters.</td></tr>';
  else body.innerHTML = trades.map((trade) => {
    const expanded = state.expandedTradeId === trade.id;
    const detailRow = expanded ? `<tr class="trade-detail-row"><td colspan="11"><div class="trade-detail-grid">
      <div><small>MODEL SIGNAL DATE</small><b>${trade.signal_date || '—'}</b></div><div><small>FORECAST</small><b>${trade.direction || trade.side || '—'}</b></div>
      <div><small>STOP PRICE</small><b>${trade.stop_price == null ? 'No stop · 15:00 exit' : rupee(trade.stop_price)}</b></div>
      <div><small>POSITION VALUE</small><b>${rupee(trade.notional || Number(trade.entry_price) * Number(trade.quantity), 0)}</b></div>
      <div><small>EXIT TYPE</small><b>${trade.exit_reason || (trade.status === 'OPEN' ? 'OPEN' : '—')}</b></div><div><small>TRADE STATUS</small><b>${trade.status || 'CLOSED'}</b></div>
    </div></td></tr>` : '';
    return `<tr class="trade-summary-row" data-trade-id="${trade.id}">
    <td><button class="trade-expand" type="button" aria-expanded="${expanded}" aria-label="${expanded ? 'Hide' : 'Show'} ${escapeHtml(trade.label || trade.symbol)} trade details"><b>${escapeHtml(trade.label || trade.symbol)}</b><span>${expanded ? '−' : '+'}</span></button></td><td class="${trade.side === 'LONG' ? 'positive' : 'negative'}">${trade.side}</td>
    <td>${tradeTime(trade.opened_at)}</td><td>${tradeTime(trade.closed_at)}</td><td class="num">${Number(trade.quantity).toLocaleString('en-IN')}</td>
    <td class="num">${fmt(trade.entry_price)}</td><td class="num">${fmt(trade.exit_price)}</td><td class="num">${rupee(trade.gross_pnl)}</td>
    <td class="num">${trade.estimated_fees == null ? '—' : rupee(trade.estimated_fees)}</td><td class="num ${clsPnl(trade.net_pnl)}"><b>${rupee(trade.gross_pnl)}</b><small class="return-sub">${Number(trade.return_pct || 0).toFixed(3)}%</small></td>
    <td class="history-reason" title="${trade.exit_reason || ''}">${trade.exit_reason || '—'}</td>
  </tr>${detailRow}`;
  }).join('');
  body.querySelectorAll('.trade-expand').forEach((button) => button.addEventListener('click', () => {
    const id = Number(button.closest('[data-trade-id]').dataset.tradeId);
    state.expandedTradeId = state.expandedTradeId === id ? null : id;
    loadTradeHistory();
  }));
  const first = total ? result.offset + 1 : 0, last = Math.min(result.offset + trades.length, total);
  byId('tradePageStatus').textContent = `Showing ${first}–${last} of ${total} trades · times IST`;
  byId('tradePrev').disabled = result.offset <= 0;
  byId('tradeNext').disabled = result.offset + trades.length >= total;
}

async function loadState() {
  try { const response = await apiFetch('/api/state', { cache: 'no-store' }); render(await response.json()); }
  catch (error) { byId('connectionText').textContent = 'Dashboard offline'; }
}

function connectSocket() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${location.host}${APP_BASE}/ws`);
  ws.onmessage = (event) => { try { render(JSON.parse(event.data)); } catch (_) {} };
  ws.onclose = (event) => { if (event.code === 4401) { window.location.replace(appUrl('/login')); return; } setTimeout(connectSocket, 2500); };
  ws.onerror = () => ws.close();
}

byId('searchInput').addEventListener('input', () => state.data && renderScanner(state.data.symbols));
byId('signalFilter').addEventListener('change', () => state.data && renderScanner(state.data.symbols));
byId('forecastFilter').addEventListener('change', () => state.data && renderScanner(state.data.symbols));
byId('positionFilter').addEventListener('change', () => state.data && renderScanner(state.data.symbols));
byId('scannerSort').addEventListener('change', () => state.data && renderScanner(state.data.symbols));
document.querySelectorAll('[data-candle-range]').forEach((button) => button.addEventListener('click', () => {
  state.candleRange = button.dataset.candleRange; state.candleHover = null; setActiveCandleRange(); drawCandles();
}));
byId('crosshairToggle').addEventListener('click', () => {
  const button = byId('crosshairToggle'), enabled = button.getAttribute('aria-pressed') !== 'true';
  button.setAttribute('aria-pressed', String(enabled)); button.classList.toggle('active', enabled);
  if (!enabled) { state.candleHover = null; candleTooltip.classList.remove('visible'); }
  drawCandles();
});
const clearEquityPreset = () => document.querySelectorAll('[data-equity-sessions]').forEach((item) => item.classList.remove('active'));
byId('equityStart').addEventListener('change', () => { clearEquityPreset(); drawEquity(state.equityCurve); });
byId('equityEnd').addEventListener('change', () => { clearEquityPreset(); drawEquity(state.equityCurve); });
document.querySelectorAll('[data-equity-sessions]').forEach((button) => button.addEventListener('click', () => {
  document.querySelectorAll('[data-equity-sessions]').forEach((item) => item.classList.toggle('active', item === button));
  const curve = state.equityCurve;
  if (button.dataset.equitySessions === 'ALL' || !curve.length) {
    byId('equityStart').value = ''; byId('equityEnd').value = '';
  } else {
    const count = Number(button.dataset.equitySessions), start = curve[Math.max(0, curve.length - count)];
    byId('equityStart').value = start?.date || ''; byId('equityEnd').value = curve[curve.length - 1]?.date || '';
  }
  drawEquity(curve);
}));
byId('equityReset').addEventListener('click', () => {
  byId('equityStart').value = ''; byId('equityEnd').value = '';
  document.querySelectorAll('[data-equity-sessions]').forEach((item) => item.classList.toggle('active', item.dataset.equitySessions === 'ALL'));
  drawEquity(state.equityCurve);
});
document.querySelectorAll('[data-history-outcome]').forEach((button) => button.addEventListener('click', () => showTradeHistory(button.dataset.historyOutcome)));
document.querySelectorAll('[data-scroll-target]').forEach((button) => button.addEventListener('click', () => {
  document.getElementById(button.dataset.scrollTarget)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}));
byId('tradeFilters').addEventListener('submit', (event) => { event.preventDefault(); state.historyOffset = 0; state.expandedTradeId = null; loadTradeHistory(); });
byId('clearTradeFilters').addEventListener('click', () => { byId('tradeFilters').reset(); state.historyOffset = 0; state.expandedTradeId = null; loadTradeHistory(); });
byId('tradePrev').addEventListener('click', () => { state.historyOffset = Math.max(0, state.historyOffset - TRADE_PAGE_SIZE); state.expandedTradeId = null; loadTradeHistory(); });
byId('tradeNext').addEventListener('click', () => { state.historyOffset += TRADE_PAGE_SIZE; state.expandedTradeId = null; loadTradeHistory(); });
byId('logoutButton').addEventListener('click', async () => {
  try { await fetch(appUrl('/api/auth/logout'), { method: 'POST' }); } finally { window.location.replace(appUrl('/login')); }
});
const navButtons = [...document.querySelectorAll('.nav-item')];
let navClickHoldUntil = 0;
function setActiveNav(button) { navButtons.forEach((item) => item.classList.toggle('active', item === button)); }
navButtons.forEach((button) => button.addEventListener('click', () => {
  setActiveNav(button);
  navClickHoldUntil = Date.now() + 700;
  document.getElementById(button.dataset.target)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}));
window.addEventListener('scroll', () => {
  if (Date.now() < navClickHoldUntil) return;
  const marker = Math.min(150, window.innerHeight * .24);
  const activeButton = navButtons.find((button) => button.classList.contains('active'));
  const activeSection = activeButton && document.getElementById(activeButton.dataset.target);
  if (activeSection) {
    const bounds = activeSection.getBoundingClientRect();
    if (bounds.top <= marker && bounds.bottom >= marker) return;
  }
  const candidate = navButtons.map((button) => ({ button, bounds: document.getElementById(button.dataset.target)?.getBoundingClientRect() }))
    .filter((item) => item.bounds && item.bounds.top <= marker && item.bounds.bottom >= marker)
    .sort((a, b) => Math.abs(a.bounds.top - marker) - Math.abs(b.bounds.top - marker))[0];
  if (candidate) setActiveNav(candidate.button);
}, { passive: true });
byId('pauseButton').addEventListener('click', async () => {
  try { await apiFetch('/api/paper/toggle', { method: 'POST' }); await loadState(); }
  catch (_) { byId('connectionText').textContent = 'Could not update paper engine'; }
});
window.addEventListener('resize', () => { if (state.data) { renderChart(state.data.symbols.find((item) => item.symbol === state.selected)); renderPerformance(state.data.performance || {}); } });
setActiveCandleRange();
loadState();
connectSocket();
setInterval(loadState, 5000);
