/* ETF 상세: 개요(기초지수·정기변경·cap) + ※주의 매도규모 + 구성종목(PDF) */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function qs(k) { return new URLSearchParams(location.search).get(k); }

  var HOLD = [], HSORT = { key: 'weight', dir: -1 }, HFILTER = '';
  var FUND = 0, FUND_LBL = '';   // 평가금액 환산 기준(순자산총액 우선, 없으면 시가총액)
  var ASOF = '';                 // etfs.json 기준일(KRX)

  // PDF 의 평가금액은 1CU 기준이라 펀드 전체 규모와 무관한 숫자다.
  // 구성비중 × 펀드 규모로 환산해야 '이 ETF 가 그 종목을 얼마나 들고 있나'가 바로 읽힌다.
  function fundSize(e) {
    if (e.nav > 0 && e.shares > 0) return { size: e.nav * e.shares, label: '순자산총액' };
    if (e.market_cap > 0) return { size: e.market_cap, label: '시가총액' };
    return { size: 0, label: '' };
  }

  (async function () {
    var ticker = qs('ticker');
    if (!ticker) { fail('종목이 지정되지 않았습니다.'); return; }
    var etf, hold = null;
    try {
      var d = await PE.loadJSON('data/etfs.json');
      ASOF = d.as_of || '';
      etf = (d.etfs || []).find(function (e) { return e.ticker === ticker; });
      if (!etf) { fail('해당 ETF를 찾을 수 없습니다.'); return; }
      document.title = etf.name + ' · 패시브 ETF 대시보드';
      try { hold = await PE.loadJSON('data/holdings/' + ticker + '.json'); } catch (e) { hold = null; }
    } catch (e) { fail('데이터 로드 실패: ' + e.message); return; }
    render(etf, hold);
  })();

  function fail(m) { $('#detail').innerHTML = '<div class="empty">' + esc(m) + '</div>'; }

  // 외부 링크 버튼. 운용사 PDF 는 '지금 이 순간' 기준이라 스냅샷보다 항상 최신이다.
  function linkBtn(url, text, cls) {
    if (!url) return '';
    return '<a class="xlink ' + (cls || '') + '" href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">'
      + esc(text) + '<span class="ext">↗</span></a>';
  }

  function linkBar(e) {
    var L = e.links;
    if (!L) return '';
    var out = [];
    out.push(linkBtn(L.product, L.manager_label + ' 상품페이지', 'prod'));
    if (L.pdf && L.pdf !== L.product) out.push(linkBtn(L.pdf, '구성종목(PDF) 원문', 'pdf'));
    out.push(linkBtn(L.index_url, L.index_label, 'idx'));
    var note = L.pdf_exact
      ? '운용사 원문은 실시간(운용사 게시 기준)입니다. 아래 표는 매일 저녁 받아둔 스냅샷이라 기준일이 다를 수 있습니다.'
      : '운용사 상품 페이지를 자동으로 특정하지 못해 상품 목록으로 연결됩니다.';
    return '<div class="xlinks">' + out.join('') + '<span class="xnote">' + note + '</span></div>';
  }

  // 다음 정기변경 예정일 — 목록 화면의 '정기변경 임박' 필터와 같은 계산(빌드 시 산출)
  function nextRebalLine(e) {
    var r = e.rebalance;
    if (!r || !r.dates || !r.dates.length) return '';
    var today = new Date(); today.setHours(0, 0, 0, 0);
    for (var i = 0; i < r.dates.length; i++) {
      var d = new Date(r.dates[i] + 'T00:00:00');
      if (d >= today) {
        var dd = Math.round((d - today) / 86400000);
        return '<div style="margin-top:8px"><span class="due ' + (dd <= 14 ? 'hot' : (dd <= 31 ? 'soon' : '')) + '">'
          + '<b>D-' + dd + '</b><span class="dt">' + esc(r.dates[i]) + '</span></span>'
          + '<span class="note" style="display:inline;margin-left:6px">' + esc(r.rule)
          + (r.estimated ? ' · 자동추정' : '') + ' 기준 예상 효력일(KRX 휴장일 반영 · 임시공휴일 제외)</span></div>';
      }
    }
    return '';
  }

  function monthsChips(ms) {
    if (!ms || !ms.length) return '<span class="tag sched">수시 (고정 종목교체 없음)</span>';
    return ms.map(function (m) { return '<span class="tag sched">' + m + '월</span>'; }).join(' ');
  }

  function render(e, hold) {
    var fs = fundSize(e); FUND = fs.size; FUND_LBL = fs.label;
    var cap = e.cap || null;
    var br = e.breach_summary || (hold && hold.breach_summary) || null;
    var capPill = cap ? (cap.verified
      ? '<span class="pill ok">확인</span>'
      : '<span class="pill chk">확인 요</span>') : '';

    var html = '';
    // 헤더
    html += '<div class="d-head">'
      + '<div><h1><span class="mgr-dot" style="width:14px;height:14px;background:' + e.color + '"></span>' + esc(e.name) + '</h1>'
      + '<div class="badges">'
      + '<span class="tag cat-' + e.category + '">' + e.category + '</span>'
      + '<span class="tag mgr">' + esc(e.manager) + ' · ' + esc(e.company) + '</span>'
      + '<span class="tag sched">' + esc(e.ticker) + '</span>'
      + (br ? '<span class="badge-warn">⚠ 비중 cap 초과 ' + br.count + '종</span>' : '')
      + '</div></div>'
      + '<div class="d-mktcap"><div class="v">' + PE.won(e.market_cap) + '</div><div class="l">시가총액 · KRX ' + esc(e.krx_name || '') + '</div></div>'
      + '</div>';

    // 운용사 상품페이지 · 구성종목(PDF) 원문 · 기초지수 산출기관
    html += linkBar(e);

    // 개요 카드
    html += '<div class="cards">';
    html += card('기초지수', '<div class="v">' + esc(e.index_name || '-') + '</div>'
      + ((e.links && e.links.index_url)
        ? '<div class="note">' + linkBtn(e.links.index_url, e.links.index_label, 'sm')
          + (e.links.index_deep ? '' : ' <span style="color:var(--muted)">(개별 지수 페이지를 특정하지 못해 산출기관 페이지로 연결)</span>')
          + '</div>'
        : ''));
    html += card('정기변경 일정',
      '<div class="v">' + esc(e.schedule_label) + '</div>'
      + '<div style="margin-top:8px">' + monthsChips(e.months) + '</div>'
      + nextRebalLine(e)
      + '<div class="note">' + esc(e.schedule_detail || '') + '</div>'
      + (e.months && e.months.length ? '<div class="note"><a class="xlink sm" href="#rebal">과거 정기변경 이력 보기 ↓</a></div>' : ''));
    html += card('비중 cap 규칙 ' + capPill,
      cap ? ('<div class="v">' + esc(cap.label || '-') + '</div>'
        + '<div class="note">' + esc(cap.note || '') + '</div>'
        + '<div class="note" style="color:var(--muted)">근거: ' + esc(cap.source || '') + '</div>')
      : '<div class="v">-</div>');
    html += card('구성 기준일',
      '<div class="v">' + esc((hold && hold.asof) || e.holdings_asof || '-') + '</div>'
      + '<div class="note">구성종목 ' + ((hold && hold.count) || 0) + '종 · 출처 ' + esc((hold && hold.source) || e.manager) + '</div>');
    html += '</div>';

    // ※주의 매도규모
    if (br && br.items && br.items.length) {
      html += '<div class="alert">'
        + '<h3>※ 주의 — 비중 cap 초과 (비중 축소 필요)</h3>'
        + '<div class="lead">아래 종목은 현재 구성비중이 상한(' + br.cap_pct + '%)을 초과합니다. '
        + '규칙상 비중 축소가 필요하며, <b>최소 매도규모 = 시가총액 × 초과 %p</b> 로 추정했습니다.'
        + (br.verified ? '' : ' <b>(상한 ' + br.cap_pct + '%는 재확인 권장 — 지수 방법론/투자설명서 확인 필요)</b>')
        + '</div>'
        + '<div class="tbl-scroll"><table><thead><tr>'
        + '<th>종목</th><th class="num">현재 비중</th><th class="num">상한</th><th class="num">초과 %p</th><th class="num">최소 매도규모</th>'
        + '</tr></thead><tbody>'
        + br.items.map(function (it) {
          return '<tr><td>' + esc(it.name) + '<span class="code">' + esc(it.code) + '</span></td>'
            + '<td class="num">' + it.weight.toFixed(2) + '%</td>'
            + '<td class="num">' + it.cap_pct + '%</td>'
            + '<td class="num" style="color:var(--warn);font-weight:800">+' + it.excess_pp.toFixed(2) + 'p</td>'
            + '<td class="num" style="color:var(--warn);font-weight:800">' + PE.won(it.sell_amount) + '</td></tr>';
        }).join('')
        + '</tbody></table></div>'
        + '<div class="total"><span class="lbl">합계 최소 매도규모</span><span class="amt">' + PE.won(br.total_sell) + '</span></div>'
        + '</div>';
    }

    // 구성종목(PDF)
    html += '<div class="sec-title"><h2>구성종목 (PDF)</h2>'
      + '<div class="meta">' + (hold ? ('기준일 ' + esc(hold.asof) + ' · ' + hold.count + '종 · 비중합 ' + (hold.total_weight || 0) + '%'
          + (FUND > 0 ? ' · 평가금액 = 구성비중 × ' + FUND_LBL + ' ' + PE.won(FUND) : '')) : '수집 준비중') + '</div>'
      + (e.links ? linkBtn(e.links.pdf, '운용사 원문 PDF 실시간 보기', 'sm pdf') : '')
      + '</div>';
    html += staleNote(e, hold);
    if (hold && hold.holdings && hold.holdings.length) {
      HOLD = hold.holdings.map(function (h) {
        var o = {}; for (var k in h) o[k] = h[k];
        o.est_amount = FUND > 0 ? (h.weight || 0) / 100 * FUND : 0;   // 구성비중 × 펀드 규모
        return o;
      });
      html += '<div style="margin:0 4px 10px"><input class="h-search" id="hsearch" placeholder="종목명·코드 검색"></div>';
      html += '<div class="card"><div class="tbl-scroll"><table id="htbl"><thead><tr>'
        + '<th style="width:44px">#</th>'
        + '<th data-hs="name">종목명</th>'
        + '<th data-hs="weight" class="num">구성비중</th>'
        + '<th data-hs="shares" class="num hide-sm">CU당 보유수량</th>'
        + '<th data-hs="est_amount" class="num hide-sm">평가금액</th>'
        + '</tr></thead><tbody id="hrows"></tbody></table></div></div>';
    } else {
      html += '<div class="card"><div class="empty">구성종목(PDF) 데이터를 준비 중입니다.</div></div>';
    }

    // 과거 정기변경 이력 — 최신 PDF 표 아래. data/rebal/{ticker}.json 을 따로 불러와 채운다.
    html += '<div id="rebal"></div>';

    html += '<div class="foot" style="margin-top:26px"><div class="disc">'
      + '시가총액·기초지수: KRX OPEN API · 구성종목: ' + esc(e.company) + ' 공식 공시 · '
      + '매도규모는 <b>시가총액 × 초과 %p</b> 단순 추정치입니다. 정보 제공 목적이며 투자 권유가 아닙니다.'
      + '</div></div>';

    $('#detail').innerHTML = html;
    if (HOLD.length) bindHoldings();
    loadRebal(e);
  }

  // 구성종목 기준일이 KRX 기준일보다 많이 밀려 있으면(운용사 수집 실패가 이어진 경우) 경고한다.
  // 2026-07~10 TIGER 가 이 상태로 석 달 묵어 운용사 홈페이지 비중과 어긋났었다.
  function staleNote(e, hold) {
    if (!hold || !hold.asof || !ASOF) return '';
    var lag = Math.round((new Date(ASOF + 'T00:00:00') - new Date(hold.asof + 'T00:00:00')) / 86400000);
    if (lag <= 4) return '';
    return '<div class="stale">⚠ 이 ETF 의 구성종목은 <b>' + esc(hold.asof) + '</b> 기준으로, 대시보드 기준일('
      + esc(ASOF) + ')보다 ' + lag + '일 늦습니다. 운용사 사이트 수집이 지연된 상태라 운용사 홈페이지 비중과 다를 수 있으니 '
      + '위 원문 PDF 링크로 확인하세요.</div>';
  }

  function card(k, v) { return '<div class="info"><div class="k">' + k + '</div>' + v + '</div>'; }

  function bindHoldings() {
    var maxw = Math.max.apply(null, HOLD.map(function (h) { return h.weight || 0; })) || 1;
    var s = $('#hsearch');
    if (s) s.oninput = function () { HFILTER = this.value.trim().toLowerCase(); drawH(maxw); };
    document.querySelectorAll('#htbl thead th[data-hs]').forEach(function (th) {
      th.onclick = function () {
        var k = th.dataset.hs;
        if (HSORT.key === k) HSORT.dir *= -1;
        else { HSORT.key = k; HSORT.dir = (k === 'name') ? 1 : -1; }
        drawH(maxw);
      };
    });
    drawH(maxw);
  }

  function drawH(maxw) {
    var rows = HOLD.filter(function (h) {
      if (!HFILTER) return true;
      return (h.name || '').toLowerCase().indexOf(HFILTER) >= 0 || (String(h.code) || '').indexOf(HFILTER) >= 0;
    });
    var k = HSORT.key, d = HSORT.dir;
    rows.sort(function (a, b) {
      var va = a[k], vb = b[k];
      if (k === 'name') { va = va || ''; vb = vb || ''; return va < vb ? -d : va > vb ? d : 0; }
      return ((vb || 0) - (va || 0)) * (d < 0 ? 1 : -1);
    });
    document.querySelectorAll('#htbl thead th[data-hs]').forEach(function (th) {
      var base = th.textContent.replace(/[▲▼]\s*$/, '').trim();
      th.innerHTML = base + (th.dataset.hs === HSORT.key ? ' <span class="ar">' + (HSORT.dir < 0 ? '▼' : '▲') + '</span>' : '');
    });
    $('#hrows').innerHTML = rows.map(function (h, i) {
      var w = h.weight || 0;
      return '<tr class="' + (h.over_cap ? 'over' : '') + '">'
        + '<td class="rk">' + (i + 1) + '</td>'
        + '<td><b>' + esc(h.name) + '</b><span class="code">' + esc(h.code) + '</span>'
        + (h.over_cap ? '<span class="over-flag">cap 초과</span>' : '') + '</td>'
        + '<td class="num"><div>' + w.toFixed(2) + '%</div><div class="wt-bar"><i style="width:' + Math.min(100, w / maxw * 100).toFixed(1) + '%"></i></div></td>'
        + '<td class="num hide-sm">' + PE.comma(h.shares) + '</td>'
        + '<td class="num hide-sm">' + (h.est_amount ? PE.won(h.est_amount) : '-') + '</td>'
        + '</tr>';
    }).join('');
  }

  /* ── 과거 정기변경 이력 ───────────────────────────────────────────
     data/rebal/{ticker}.json (scripts/rebal_history.py) — 정기변경일 전후 운용사 PDF 비교.
     순매매 %p 는 CU 보유수량 변화 × post 가격 / 펀드 평가액(가격 효과 제거). */
  var RB = null, RB_SEL = 0, RB_FILTER = 'all', RB_ALL = false;
  var TYPE_LBL = { 'in': '편입', 'out': '편출', 'up': '비중 확대', 'down': '비중 축소', 'ca': '주식수 조정', 'recode': '코드 변경' };

  async function loadRebal(e) {
    var box = $('#rebal');
    if (!box) return;
    var j = null;
    try { j = await PE.loadJSON('data/rebal/' + e.ticker + '.json'); } catch (x) { j = null; }
    var evs = (j && j.events) || [];
    var head = '<div class="sec-title"><h2>과거 정기변경 이력</h2>'
      + '<div class="meta">' + (evs.length
        ? (esc((j.since || '').slice(0, 7)) + ' 이후 ' + evs.length + '회 · 정기변경일 전후 운용사 PDF 비교')
        : '') + '</div></div>';
    if (!evs.length) {
      var why = (!e.months) ? '정기변경 일정이 확인되지 않아 이력을 만들지 않았습니다.'
        : (!e.months.length ? '정해진 정기변경 없이 수시로 종목을 바꾸는 ETF 입니다.'
          : (j && j.note ? j.note : '아직 비교할 수 있는 과거 PDF 가 없습니다(최근 상장 등).'));
      box.innerHTML = head + '<div class="card"><div class="empty" style="padding:28px 20px">' + esc(why) + '</div></div>';
      return;
    }
    RB = { etf: e, data: j, evs: evs };
    RB_SEL = 0; RB_FILTER = 'all'; RB_ALL = false;
    box.innerHTML = head
      + (j.note ? '<div class="rb-note">' + esc(j.note) + '</div>' : '')
      + '<div class="rb-strip" id="rbstrip"></div>'
      + '<div class="card rb-panel" id="rbpanel"></div>';
    drawStrip();
    drawEvent();
  }

  function ym(d) { return d ? d.slice(0, 4) + '.' + d.slice(5, 7) : ''; }
  function md(d) { return d ? d.slice(5).replace('-', '/') : ''; }

  // 억 단위 미만은 백만원으로(소형 종목 편출 등)
  function amt(v, signed) {
    if (v == null) return '-';
    var a = Math.abs(v), s = signed ? (v > 0 ? '+' : (v < 0 ? '−' : '')) : '';
    if (a >= 1e8) return s + PE.won(a);
    if (a >= 1e6) return s + Math.round(a / 1e6).toLocaleString() + '백만';
    return a > 0 ? s + '1백만 미만' : '0';
  }
  function pp(v) {
    var a = Math.abs(v);
    return (v > 0 ? '+' : (v < 0 ? '−' : '')) + (a >= 0.1 ? a.toFixed(2) : a.toFixed(3)) + '%p';
  }

  function drawStrip() {
    var max = Math.max.apply(null, RB.evs.map(function (v) { return (v.sum && v.sum.to) || 0; })) || 1;
    $('#rbstrip').innerHTML = RB.evs.map(function (v, i) {
      var s = v.sum || {}, ok = v.status === 'ok';
      var h = ok ? Math.max(4, Math.round((s.to || 0) / max * 34)) : 2;
      return '<button class="rb-ev' + (i === RB_SEL ? ' on' : '') + (ok ? '' : ' quiet') + '" data-i="' + i + '">'
        + '<span class="rb-bar"><i style="height:' + h + 'px"></i></span>'
        + '<span class="rb-d">' + ym(v.date) + '</span>'
        + '<span class="rb-s">' + (ok
          ? ((s['in'] || s.out) ? '<em class="i">+' + (s['in'] || 0) + '</em> <em class="o">−' + (s.out || 0) + '</em>' : '조정만')
          : '변동 없음') + '</span>'
        + '</button>';
    }).join('');
    document.querySelectorAll('#rbstrip .rb-ev').forEach(function (b) {
      b.onclick = function () { RB_SEL = +b.dataset.i; RB_FILTER = 'all'; RB_ALL = false; drawStrip(); drawEvent(); };
    });
  }

  function drawEvent() {
    var v = RB.evs[RB_SEL], s = v.sum || {}, e = RB.etf;
    var h = '<div class="rb-head">'
      + '<div><div class="rb-title">' + esc(v.date) + ' 정기변경'
      + (v.est ? ' <span class="pill chk">일정 자동추정</span>' : '')
      + (v.provisional ? ' <span class="pill chk">잠정</span>' : '') + '</div>'
      + '<div class="rb-sub">예상 효력일(' + esc(v.rule) + ') · PDF 비교 <b>' + esc(v.pre) + '</b> → <b>' + esc(v.post) + '</b>'
      + (v.days && v.days.length ? ' · 구성 반영일 ' + v.days.map(md).join(', ') : '')
      + (v.aum ? ' · 당시 순자산 ' + PE.won(v.aum) : '') + '</div></div></div>';

    if (v.status !== 'ok') {
      h += '<div class="empty" style="padding:26px 20px">이 정기변경 전후(' + esc(v.pre) + ' → ' + esc(v.post)
        + ') PDF 에는 의미 있는 구성 변화가 없었습니다'
        + (v.est ? ' — 정기변경 일정이 자동추정이라 실제 변경일이 이 구간 밖일 수 있습니다.' : '.') + '</div>';
      $('#rbpanel').innerHTML = h;
      return;
    }

    h += '<div class="rb-stats">'
      + stat('편입', s['in'] || 0, 'i') + stat('편출', s.out || 0, 'o')
      + stat('비중 확대', s.up || 0, '') + stat('비중 축소', s.down || 0, '')
      + stat('편도 회전율', (s.to || 0).toFixed(2) + '%', '')
      + (s.buy_amt != null ? stat('추정 매수 / 매도', amt(s.buy_amt) + ' / ' + amt(s.sell_amt), 'wide') : '')
      + '</div>';

    // cap 상한 조정 요약
    var cuts = v.items.filter(function (it) { return it.cap === 'cut'; });
    var fills = v.items.filter(function (it) { return it.cap === 'fill'; });
    if (cuts.length) {
      h += '<div class="rb-cap"><b>비중 상한(cap) 조정</b> — '
        + cuts.map(function (it) {
          return esc(it.n) + ' ' + it.w0.toFixed(2) + '% → ' + it.w1.toFixed(2) + '% (상한 ' + it.lim + '%, 순매매 ' + pp(it.tr)
            + (it.amt != null ? ', ' + amt(it.amt, true) : '') + ')';
        }).join(' · ')
        + (fills.length ? '<br>상한까지 채워 올린 종목: ' + fills.map(function (it) { return esc(it.n) + ' ' + it.w1.toFixed(2) + '%'; }).join(', ') : '')
        + '<span class="rb-capnote">현재 cap 규칙(' + esc((e.cap && e.cap.label) || '') + ') 기준 표시입니다. 과거엔 규칙이 달랐을 수 있습니다.</span></div>';
    }

    var cnt = {
      all: v.items.length,
      io: v.items.filter(function (it) { return it.t === 'in' || it.t === 'out'; }).length,
      adj: v.items.filter(function (it) { return it.t === 'up' || it.t === 'down'; }).length
    };
    h += '<div class="rb-tools"><div class="seg">'
      + segBtn('all', '전체 ' + cnt.all) + segBtn('io', '편입·편출 ' + cnt.io) + segBtn('adj', '비중 조정 ' + cnt.adj)
      + '</div><span class="rb-legend">순매매 = 보유수량 변화 × 당시 가격 ÷ 펀드 평가액 (주가 변동 효과 제외)</span></div>';

    var rows = v.items.filter(function (it) {
      if (RB_FILTER === 'io') return it.t === 'in' || it.t === 'out';
      if (RB_FILTER === 'adj') return it.t === 'up' || it.t === 'down';
      return true;
    });
    var LIMIT = 25, shown = RB_ALL ? rows : rows.slice(0, LIMIT);
    var maxTr = Math.max.apply(null, rows.map(function (it) { return Math.abs(it.tr); }).concat([0.0001]));

    h += '<div class="tbl-scroll"><table class="rb-tbl"><thead><tr>'
      + '<th>구분</th><th>종목</th><th class="num">이전 비중</th><th class="num">이후 비중</th>'
      + '<th class="num">순매매</th><th class="num hide-sm">CU 수량</th><th class="num">추정 금액</th>'
      + '</tr></thead><tbody>'
      + shown.map(function (it) {
        var w = Math.min(100, Math.abs(it.tr) / maxTr * 100);
        var dir = it.tr > 0 ? 'b' : (it.tr < 0 ? 's' : '');
        return '<tr class="t-' + it.t + '">'
          + '<td><span class="rb-t t-' + it.t + '">' + TYPE_LBL[it.t] + '</span>'
          + (it.cap === 'cut' ? '<span class="rb-t cap">상한 초과분 매도</span>' : '')
          + (it.cap === 'fill' ? '<span class="rb-t capf">상한까지 매수</span>' : '') + '</td>'
          + '<td><b>' + esc(it.n) + '</b><span class="code">' + esc(it.c) + '</span></td>'
          + '<td class="num">' + (it.t === 'in' ? '<span class="mu">-</span>' : it.w0.toFixed(2) + '%') + '</td>'
          + '<td class="num">' + (it.t === 'out' ? '<span class="mu">-</span>' : it.w1.toFixed(2) + '%') + '</td>'
          + '<td class="num rb-tr ' + dir + '"><div>' + (it.t === 'ca' || it.t === 'recode' ? '<span class="mu">-</span>' : pp(it.tr)) + '</div>'
          + (dir ? '<div class="rb-trbar ' + dir + '"><i style="width:' + w.toFixed(1) + '%"></i></div>' : '') + '</td>'
          + '<td class="num hide-sm">' + qty(it) + '</td>'
          + '<td class="num rb-amt ' + dir + '">' + (it.amt != null ? amt(it.amt, true) : '<span class="mu">-</span>') + '</td>'
          + '</tr>';
      }).join('')
      + '</tbody></table></div>';
    if (rows.length > LIMIT) {
      h += '<div class="rb-more"><button class="btn ghost" id="rbmore">' + (RB_ALL ? '접기' : '전체 ' + rows.length + '개 보기') + '</button></div>';
    }
    if (s.ca || s.recode) {
      h += '<div class="rb-foot">' + (s.ca ? '주식수 조정 ' + s.ca + '종: 분할·병합·무상증자 등으로 수량은 바뀌었지만 비중은 그대로인 종목(매매 아님). ' : '')
        + (s.recode ? '코드 변경 ' + s.recode + '건: 같은 종목의 종목코드만 바뀐 경우. ' : '') + '</div>';
    }
    if (s.same) h += '<div class="rb-foot">그 밖에 ' + s.same + '종은 보유수량 변화가 없거나 미미(±0.01%p 미만)해 생략했습니다.</div>';

    $('#rbpanel').innerHTML = h;
    document.querySelectorAll('#rbpanel .seg button').forEach(function (b) {
      b.onclick = function () { RB_FILTER = b.dataset.f; RB_ALL = false; drawEvent(); };
    });
    var mb = $('#rbmore');
    if (mb) mb.onclick = function () { RB_ALL = !RB_ALL; drawEvent(); };
  }

  function stat(k, v, cls) {
    return '<div class="rb-stat ' + (cls || '') + '"><div class="k">' + k + '</div><div class="v">' + v + '</div></div>';
  }
  function segBtn(f, t) { return '<button data-f="' + f + '" class="' + (RB_FILTER === f ? 'on' : '') + '">' + t + '</button>'; }
  function qty(it) {
    if (it.t === 'in') return '<span class="mu">0 →</span> ' + PE.comma(it.s1);
    if (it.t === 'out') return PE.comma(it.s0) + ' <span class="mu">→ 0</span>';
    var r = it.s0 ? (it.s1 / it.s0 - 1) * 100 : 0;
    return PE.comma(it.s0) + ' → ' + PE.comma(it.s1)
      + (it.s0 ? ' <span class="mu">(' + (r > 0 ? '+' : '') + r.toFixed(1) + '%)</span>' : '');
  }
})();
