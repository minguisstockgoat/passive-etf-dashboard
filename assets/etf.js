/* ETF 상세: 개요(기초지수·정기변경·cap) + ※주의 매도규모 + 구성종목(PDF) */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function qs(k) { return new URLSearchParams(location.search).get(k); }

  var HOLD = [], HSORT = { key: 'weight', dir: -1 }, HFILTER = '';

  (async function () {
    var ticker = qs('ticker');
    if (!ticker) { fail('종목이 지정되지 않았습니다.'); return; }
    var etf, hold = null;
    try {
      var d = await PE.loadJSON('data/etfs.json');
      etf = (d.etfs || []).find(function (e) { return e.ticker === ticker; });
      if (!etf) { fail('해당 ETF를 찾을 수 없습니다.'); return; }
      document.title = etf.name + ' · 패시브 ETF 대시보드';
      try { hold = await PE.loadJSON('data/holdings/' + ticker + '.json'); } catch (e) { hold = null; }
    } catch (e) { fail('데이터 로드 실패: ' + e.message); return; }
    render(etf, hold);
  })();

  function fail(m) { $('#detail').innerHTML = '<div class="empty">' + esc(m) + '</div>'; }

  function monthsChips(ms) {
    if (!ms || !ms.length) return '<span class="tag sched">수시 (고정 종목교체 없음)</span>';
    return ms.map(function (m) { return '<span class="tag sched">' + m + '월</span>'; }).join(' ');
  }

  function render(e, hold) {
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

    // 개요 카드
    html += '<div class="cards">';
    html += card('기초지수', '<div class="v">' + esc(e.index_name || '-') + '</div>');
    html += card('정기변경 일정',
      '<div class="v">' + esc(e.schedule_label) + '</div>'
      + '<div style="margin-top:8px">' + monthsChips(e.months) + '</div>'
      + '<div class="note">' + esc(e.schedule_detail || '') + '</div>');
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
      + '<div class="meta">' + (hold ? ('기준일 ' + esc(hold.asof) + ' · ' + hold.count + '종 · 비중합 ' + (hold.total_weight || 0) + '%') : '수집 준비중') + '</div></div>';
    if (hold && hold.holdings && hold.holdings.length) {
      HOLD = hold.holdings.slice();
      html += '<div style="margin:0 4px 10px"><input class="h-search" id="hsearch" placeholder="종목명·코드 검색"></div>';
      html += '<div class="card"><div class="tbl-scroll"><table id="htbl"><thead><tr>'
        + '<th style="width:44px">#</th>'
        + '<th data-hs="name">종목명</th>'
        + '<th data-hs="weight" class="num">구성비중</th>'
        + '<th data-hs="shares" class="num hide-sm">보유수량</th>'
        + '<th data-hs="amount" class="num hide-sm">평가금액</th>'
        + '</tr></thead><tbody id="hrows"></tbody></table></div></div>';
    } else {
      html += '<div class="card"><div class="empty">구성종목(PDF) 데이터를 준비 중입니다.</div></div>';
    }

    html += '<div class="foot" style="margin-top:26px"><div class="disc">'
      + '시가총액·기초지수: KRX OPEN API · 구성종목: ' + esc(e.company) + ' 공식 공시 · '
      + '매도규모는 <b>시가총액 × 초과 %p</b> 단순 추정치입니다. 정보 제공 목적이며 투자 권유가 아닙니다.'
      + '</div></div>';

    $('#detail').innerHTML = html;
    if (HOLD.length) bindHoldings();
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
        + '<td class="num hide-sm">' + (h.amount ? PE.won(h.amount) : '-') + '</td>'
        + '</tr>';
    }).join('');
  }
})();
