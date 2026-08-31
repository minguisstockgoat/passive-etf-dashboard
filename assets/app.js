/* 초기화면: 시총순 테이블 + 필터 + 실시간 갱신 */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  var DATA = [];            // etfs
  var LIVE = {};            // ticker -> 실시간 시총
  var META = {};
  var F = { type: 'all', cats: new Set(), min: null, max: null, months: new Set(), mgrs: new Set(), q: '', due: 0 };
  var SORT = { key: 'market_cap', dir: -1 };

  var MONTHS = [1,2,3,4,5,6,7,8,9,10,11,12];

  function mcap(e) { return LIVE[e.ticker] != null ? LIVE[e.ticker] : e.market_cap; }

  // ── 정기변경 D-day ──────────────────────────
  // rebalance.dates = 앞으로의 정기변경 예정일(빌드 시 계산). 오늘 이후 첫 날짜를 쓴다.
  // 수시(months=[])·미확인(months=null)은 rebalance 가 없어 항상 맨 뒤로 밀린다.
  var TODAY = (function () { var d = new Date(); d.setHours(0, 0, 0, 0); return d; })();
  function nextRebal(e) {
    var r = e.rebalance;
    if (!r || !r.dates || !r.dates.length) return null;
    for (var i = 0; i < r.dates.length; i++) {
      var d = new Date(r.dates[i] + 'T00:00:00');
      if (d >= TODAY) return { date: d, iso: r.dates[i], rule: r.rule, est: !!r.estimated };
    }
    return null;
  }
  function ddays(e) {
    var n = nextRebal(e);
    return n ? Math.round((n.date - TODAY) / 86400000) : null;
  }

  // ── 필터 UI 구성 ────────────────────────────
  function buildFilters() {
    // 분류 칩
    var cats = ['시장대표','섹터','테마','전략','그룹주'].filter(function (c) {
      return DATA.some(function (e) { return e.category === c; });
    });
    $('#f-cat').innerHTML = cats.map(function (c) {
      return '<button class="chip" data-cat="' + c + '">' + c + '</button>';
    }).join('');
    // 월 칩
    $('#f-month').innerHTML = MONTHS.map(function (m) {
      return '<button class="chip mon" data-mon="' + m + '">' + m + '</button>';
    }).join('') + '<button class="chip mon" data-mon="0">수시</button>'
      + '<button class="chip mon" data-mon="-1">미확인</button>';
    // 운용사 칩
    var mgrs = [];
    DATA.forEach(function (e) { if (mgrs.indexOf(e.manager) < 0) mgrs.push(e.manager); });
    $('#f-mgr').innerHTML = mgrs.map(function (m) {
      var col = (DATA.find(function (e) { return e.manager === m; }) || {}).color || '#2d8b8b';
      return '<button class="chip" data-mgr="' + m + '"><span class="mgr-dot" style="display:inline-block;margin-right:5px;background:' + col + '"></span>' + m + '</button>';
    }).join('');

    // 이벤트
    $$('#f-type button').forEach(function (b) {
      b.onclick = function () {
        $$('#f-type button').forEach(function (x) { x.classList.remove('on'); });
        b.classList.add('on'); F.type = b.dataset.v; render();
      };
    });
    // 임박 필터를 켜면 정렬도 임박순으로 바꿔야 '상위에 보인다'는 목적이 산다
    $$('#f-due button').forEach(function (b) {
      b.onclick = function () {
        $$('#f-due button').forEach(function (x) { x.classList.remove('on'); });
        b.classList.add('on'); F.due = +b.dataset.v;
        if (F.due) { SORT = { key: 'rebal', dir: 1 }; }
        else if (SORT.key === 'rebal') { SORT = { key: 'market_cap', dir: -1 }; }
        render();
      };
    });
    $$('#f-cat button').forEach(function (b) { b.onclick = function () { toggle(b, F.cats, b.dataset.cat); }; });
    $$('#f-month button').forEach(function (b) { b.onclick = function () { toggle(b, F.months, +b.dataset.mon); }; });
    $$('#f-mgr button').forEach(function (b) { b.onclick = function () { toggle(b, F.mgrs, b.dataset.mgr); }; });
    $('#f-min').oninput = function () { F.min = this.value ? +this.value : null; render(); };
    $('#f-max').oninput = function () { F.max = this.value ? +this.value : null; render(); };
    $('#f-reset').onclick = resetFilters;

    $$('#tbl thead th').forEach(function (th) {
      if (!th.dataset.sort) return;
      th.onclick = function () {
        var k = th.dataset.sort;
        if (SORT.key === k) SORT.dir *= -1;
        else { SORT.key = k; SORT.dir = (k === 'market_cap') ? -1 : 1; }
        render();
      };
    });
  }
  function toggle(btn, set, val) {
    if (set.has(val)) { set.delete(val); btn.classList.remove('on'); }
    else { set.add(val); btn.classList.add('on'); }
    render();
  }
  function resetFilters() {
    F = { type: 'all', cats: new Set(), min: null, max: null, months: new Set(), mgrs: new Set(), q: '', due: 0 };
    $('#f-min').value = ''; $('#f-max').value = ''; if ($('#search')) $('#search').value = '';
    $$('.chip.on').forEach(function (b) { b.classList.remove('on'); });
    $$('#f-type button').forEach(function (b, i) { b.classList.toggle('on', i === 0); });
    $$('#f-due button').forEach(function (b, i) { b.classList.toggle('on', i === 0); });
    SORT = { key: 'market_cap', dir: -1 };
    render();
  }

  // ── 필터 적용 ───────────────────────────────
  function pass(e) {
    if (F.type === 'theme' && !e.is_theme) return false;
    if (F.type === 'market' && e.is_theme) return false;
    if (F.cats.size && !F.cats.has(e.category)) return false;
    var cap億 = mcap(e) / 1e8;
    if (F.min != null && cap億 < F.min) return false;
    if (F.max != null && cap億 > F.max) return false;
    if (F.months.size) {
      var ms = e.months;   // null(미확인) | [](수시) | [월..]
      var hit = false;
      F.months.forEach(function (m) {
        if (m === -1 && ms === null) hit = true;
        else if (m === 0 && Array.isArray(ms) && ms.length === 0) hit = true;
        else if (m > 0 && Array.isArray(ms) && ms.indexOf(m) >= 0) hit = true;
      });
      if (!hit) return false;
    }
    if (F.due) {
      var dd = ddays(e);                 // 수시·미확인은 null → 임박 필터에서 제외
      if (dd == null || dd > F.due) return false;
    }
    if (F.mgrs.size && !F.mgrs.has(e.manager)) return false;
    if (F.q) {
      var hay = (e.name + ' ' + (e.index_name || '') + ' ' + e.manager).toLowerCase();
      if (hay.indexOf(F.q) < 0) return false;
    }
    return true;
  }

  function sortRows(rows) {
    var k = SORT.key, d = SORT.dir;
    return rows.slice().sort(function (a, b) {
      var va, vb;
      if (k === 'market_cap') { va = mcap(a); vb = mcap(b); }
      else if (k === 'rebal') {
        // 일정 없는 종목(수시·미확인)은 정렬 방향과 무관하게 항상 뒤로
        var da = ddays(a), db = ddays(b);
        if (da == null && db == null) return mcap(b) - mcap(a);
        if (da == null) return 1;
        if (db == null) return -1;
        va = da; vb = db;
      }
      else { va = a[k] || ''; vb = b[k] || ''; }
      if (va < vb) return -1 * d; if (va > vb) return 1 * d; return mcap(b) - mcap(a);
    });
  }

  // ── 렌더 ────────────────────────────────────
  function render() {
    var rows = sortRows(DATA.filter(pass));
    var isLive = Object.keys(LIVE).length > 0;
    $('#count').innerHTML = '표시 <b>' + rows.length + '</b>종 / 전체 ' + DATA.length + '종'
      + (F.min != null || F.max != null || F.type !== 'all' || F.cats.size || F.months.size || F.mgrs.size || F.due ? ' · 필터 적용됨' : '')
      + (F.due ? ' · 정기변경 ' + F.due + '일 이내' : '');

    $$('#tbl thead th').forEach(function (th) {
      var base = th.textContent.replace(/[▲▼]\s*$/, '').trim();
      th.innerHTML = base + (th.dataset.sort === SORT.key ? ' <span class="ar">' + (SORT.dir < 0 ? '▼' : '▲') + '</span>' : '');
    });

    if (!rows.length) { $('#rows').innerHTML = '<tr><td colspan="5" class="empty">조건에 맞는 ETF가 없습니다.</td></tr>'; return; }
    $('#rows').innerHTML = rows.map(function (e) {
      var warn = e.breach_summary ? '<span class="badge-warn" title="비중 cap 초과 종목 있음">⚠ ' + e.breach_summary.count + '</span>' : '';
      var cv = mcap(e);
      return '<tr onclick="location.href=\'etf.html?ticker=' + e.ticker + '\'">'
        + '<td><div class="etf-name"><span class="mgr-dot" style="background:' + e.color + '"></span>'
        + '<span class="nm">' + e.name + '</span>'
        + '<span class="tag cat-' + e.category + '">' + e.category + '</span>' + warn + '</div></td>'
        + '<td class="hide-sm"><span class="tag sched' + (e.schedule_verified ? '' : ' est') + '"'
        + (e.schedule_verified ? '' : ' title="자동추정 · 개별 확인 필요"') + '>' + e.schedule_label + '</span></td>'
        + '<td>' + dueCell(e) + '</td>'
        + '<td class="num"><span class="mktcap' + (isLive ? ' mc-live' : '') + '">' + PE.won(cv) + '</span></td>'
        + '<td class="hide-sm"><span class="tag mgr">' + e.manager + '</span></td>'
        + '</tr>';
    }).join('');
  }

  // 다음 정기변경 셀 — D-day 배지 + 날짜. 임박할수록 진하게.
  function dueCell(e) {
    var n = nextRebal(e);
    if (!n) {
      var ms = e.months;
      if (ms === null) return '<span class="due none" title="정기변경 규칙 미확인">확인 요</span>';
      return '<span class="due none" title="고정 정기 종목교체 없이 수시 반영">수시</span>';
    }
    var d = Math.round((n.date - TODAY) / 86400000);
    var cls = d <= 14 ? 'hot' : (d <= 31 ? 'soon' : '');
    var md = n.iso.slice(5).replace('-', '/');
    return '<span class="due ' + cls + '" title="' + n.rule + (n.est ? ' · 자동추정' : '')
      + ' — 지수 변경 효력일 예상치(KRX 휴장일 반영 · 임시공휴일 제외)">'
      + '<b>D-' + d + '</b><span class="dt">' + md + (n.est ? '<span class="est-mark">~</span>' : '') + '</span></span>';
  }

  // ── 실시간 갱신 ─────────────────────────────
  async function refresh() {
    var btn = $('#refresh'); btn.disabled = true;
    $('#refresh-ic').outerHTML = '<span class="spin" id="refresh-ic"></span>';
    try {
      // 1) 최신 스냅샷 재조회 (빠름 · 항상 동작)
      var fresh = await PE.loadJSON('data/etfs.json', true);
      DATA = fresh.etfs; META = fresh; LIVE = {};
      setAsof(0, true);      // 스냅샷 + '실시간 확인 중'
      render();
    } catch (e) { /* 유지 */ }
    // 버튼은 바로 복구, 장중 실시간가는 백그라운드로
    $('#refresh-ic').outerHTML = '<span id="refresh-ic">↻</span>';
    btn.disabled = false;
    liveEnhance();
  }

  async function liveEnhance() {
    try {
      var prices = await PE.livePrices(DATA.map(function (e) { return e.ticker; }));
      var n = 0;
      DATA.forEach(function (e) {
        if (prices[e.ticker] && e.shares) { LIVE[e.ticker] = prices[e.ticker] * e.shares; n++; }
      });
      setAsof(n);            // n>0 → 실시간, 0 → 스냅샷 유지
      render();
    } catch (e) { setAsof(0); }
  }

  function setAsof(liveN, checking) {
    var el = $('#asof');
    var base = 'KRX 종가 기준일 <b>' + (META.as_of || '-') + '</b>';
    if (liveN) {
      var t = new Date();
      var hh = ('0' + t.getHours()).slice(-2), mm = ('0' + t.getMinutes()).slice(-2);
      el.innerHTML = base + '<br><span class="live">● 실시간 시총 반영 ' + hh + ':' + mm + ' (' + liveN + '종)</span>';
    } else if (checking) {
      el.innerHTML = base + '<br><span style="color:var(--muted)">스냅샷 · 실시간 확인 중…</span>';
    } else {
      el.innerHTML = base + '<br>스냅샷 · 갱신 ' + (META.generated_at || '');
    }
  }

  // ── 시작 ────────────────────────────────────
  (async function init() {
    try {
      var d = await PE.loadJSON('data/etfs.json');
      DATA = d.etfs; META = d;
      var mc = d.min_cap_eok ? (d.min_cap_eok >= 10000 ? (d.min_cap_eok / 10000) + '조' : d.min_cap_eok.toLocaleString() + '억') : '';
      $('#sub').innerHTML = '금일 기준 시가총액 <b>' + mc + '원 이상</b> 국내주식형 패시브 ETF <b>' + d.count + '종</b>의 '
        + '정기변경 일정 · 시가총액 · 구성종목(PDF) · 비중 cap 규제를 정리합니다. '
        + '<span style="color:var(--muted)">(9천억+ 32종은 정기변경·cap 원문 검증, 그 외는 자동 분류)</span>';
      $('#regnote').innerHTML = '<b>비중 규제</b> · ' + (d.reg_note || '');
      setAsof(0);
      buildFilters();
      $('#search').oninput = function () { F.q = this.value.trim().toLowerCase(); render(); };
      $('#f-min').value = '';
      render();
    } catch (e) {
      $('#rows').innerHTML = '<tr><td colspan="5" class="empty">데이터를 불러오지 못했습니다. (' + e.message + ')</td></tr>';
    }
    $('#refresh').onclick = refresh;
  })();
})();
