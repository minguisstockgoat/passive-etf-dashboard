/* 공통 유틸: 포맷, 데이터 로드, 장중 실시간가 조회(프록시 폴백) */
(function (g) {
  'use strict';

  // ── 금액 포맷 (원 → 조/억) ─────────────────────────
  function won(v) {
    v = Number(v) || 0;
    var eok = Math.round(v / 1e8);                 // 억 단위
    if (eok >= 10000) {
      var jo = Math.floor(eok / 10000), rest = eok % 10000;
      return jo + '조' + (rest ? ' ' + rest.toLocaleString() + '억' : '');
    }
    return eok.toLocaleString() + '억';
  }
  function won2(v) { return won(v); }              // alias
  function pct(v, d) { return (Number(v) || 0).toFixed(d == null ? 2 : d) + '%'; }
  function comma(v) { return (Number(v) || 0).toLocaleString(); }

  // ── JSON 로드 (캐시 무효화) ────────────────────────
  async function loadJSON(path, bust) {
    var u = path + (bust ? (path.indexOf('?') < 0 ? '?' : '&') + 't=' + Date.now() : '');
    var r = await fetch(u, { cache: bust ? 'no-store' : 'default' });
    if (!r.ok) throw new Error(path + ' ' + r.status);
    return r.json();
  }

  // ── CORS 프록시 폴백 fetch (텍스트 반환) ───────────
  // 1순위: 사용자 전용 Cloudflare Worker(네이버 시세 호스트 화이트리스트, ~200ms, 안정).
  //        폴백으로 공개 프록시.
  var PROXIES = [
    function (u) { return { url: 'https://hynix-proxy.eogks879.workers.dev/?url=' + encodeURIComponent(u), json: false }; },
    function (u) { return { url: 'https://api.allorigins.win/raw?url=' + encodeURIComponent(u), json: false }; },
    function (u) { return { url: 'https://corsproxy.org/?url=' + encodeURIComponent(u), json: false }; },
    function (u) { return { url: 'https://api.allorigins.win/get?url=' + encodeURIComponent(u), json: 'contents' }; }
  ];
  async function proxyText(target, ms) {
    for (var i = 0; i < PROXIES.length; i++) {
      var p = PROXIES[i](target);
      try {
        var ctl = new AbortController();
        var to = setTimeout(function () { ctl.abort(); }, ms || 6000);
        var r = await fetch(p.url, { signal: ctl.signal });
        clearTimeout(to);
        if (!r.ok) continue;
        var body = await r.text();
        if (p.json === 'contents') { try { body = JSON.parse(body).contents; } catch (e) { continue; } }
        if (body && body.length > 2) return body;
      } catch (e) { /* 다음 프록시 */ }
    }
    return null;
  }

  // ── 장중 실시간 가격 (네이버 폴링) → {ticker: price} ──
  async function livePrices(tickers) {
    if (!tickers || !tickers.length) return {};
    var out = {};
    // 한 번에 40개씩
    for (var s = 0; s < tickers.length; s += 40) {
      var batch = tickers.slice(s, s + 40);
      var url = 'https://polling.finance.naver.com/api/realtime/domestic/stock/' + batch.join(',');
      var txt = await proxyText(url, 7000);
      if (!txt) continue;
      var j; try { j = JSON.parse(txt); } catch (e) { continue; }
      (j.datas || []).forEach(function (d) {
        var p = d.closePrice != null ? d.closePrice : (d.nv != null ? d.nv : d.tradePrice);
        p = Number(String(p == null ? '' : p).replace(/,/g, ''));
        if (p > 0) out[d.itemCode || d.cd] = p;
      });
    }
    return out;
  }

  g.PE = { won: won, won2: won2, pct: pct, comma: comma, loadJSON: loadJSON, proxyText: proxyText, livePrices: livePrices };
})(window);
