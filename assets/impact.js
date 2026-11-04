(async function(){'use strict';
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul'}).format(new Date());
const num=(n,d=2)=>Number.isFinite(n)?n.toLocaleString('ko-KR',{maximumFractionDigits:d,minimumFractionDigits:d}):'—';
const money=n=>Number.isFinite(n)?num(n/1e8,2)+'억':'—';
const pct=n=>Number.isFinite(n)?num(n,2)+'%':'—';
const dateDiff=(a,b)=>(Date.parse(b+'T00:00:00Z')-Date.parse(a+'T00:00:00Z'))/86400000;
let catalog,market,holidays,status,selected,hold,rows=[],model,manual=false,peers=[],version=0,lastReport=null;
const unsupported=h=>h.holdings.filter(x=>!market.stocks[x.code]&&Math.abs(x.weight||0)>.001&&!/현금|예금|미수금|미지급|원화|설정현금/.test(x.name||''));
const holdings=new Map(),query=new URLSearchParams(location.search);
const next=e=>(e.rebalance?.dates||[]).find(d=>d>=today)||null;
const lag=d=>{if(!d)return Infinity;let n=0;for(let x=new Date(d+'T00:00:00Z'),end=new Date(today+'T00:00:00Z');x<end;){x.setUTCDate(x.getUTCDate()+1);if(x.getUTCDay()%6!==0&&!holidays.has(x.toISOString().slice(0,10)))n++;}return n;};
async function loadHold(e){if(!holdings.has(e.ticker))holdings.set(e.ticker,await PE.loadJSON('data/holdings/'+e.ticker+'.json',true));return holdings.get(e.ticker);}
function same(e){return e.ticker!==selected.ticker&&e.index_name===selected.index_name&&next(e)===next(selected)&&next(e)&&!/레버리지|인버스|선물|합성|커버드콜/.test(e.name)&&e.nav*e.shares>0;}
function invalidate(){lastReport=null;$('#report').innerHTML='';}
function fillOptions(prefer){
 const horizon=+$('#horizon').value;
 const list=catalog.etfs.filter(e=>horizon===9999||(next(e)&&dateDiff(today,next(e))<=horizon)).sort((a,b)=>(next(a)||'9999').localeCompare(next(b)||'9999')||b.market_cap-a.market_cap);
 $('#fund').innerHTML=list.map(e=>'<option value="'+esc(e.ticker)+'">'+esc(e.name)+' · '+esc(next(e)||'일정 미확인')+(e.rebalance?.estimated?' (추정)':'')+'</option>').join('');
 if(prefer&&list.some(e=>e.ticker===prefer))$('#fund').value=prefer;
 if(!list.length){$('#fund-summary').textContent='이 기간에 예정된 ETF가 없습니다. 전체 ETF로 변경해 주세요.';$('#generate').disabled=true;return;}
 choose();
}
async function choose(){
 const token=++version;$('#generate').disabled=true;$('#message').textContent='구성종목을 불러오는 중…';invalidate();
 selected=catalog.etfs.find(e=>e.ticker===$('#fund').value);manual=false;$('#scenario-source').value='';$('#peers').checked=false;
 try{
  const h=await loadHold(selected);if(token!==version)return;hold=h;
  rows=h.holdings.filter(h=>market.stocks[h.code]&&h.weight>=0).map(h=>({code:h.code,name:h.name,current:+h.weight,target:+h.weight}));
  const equity=rows.reduce((s,r)=>s+r.current,0);
  model=ImpactModel.defaultTarget(selected,rows,market);
  if(unsupported(h).length)model={...model,ready:false,blocked:true,note:'현물 종목 시세와 연결되지 않은 자산('+unsupported(h).map(x=>x.name).join(', ')+')이 있어 수급 계산을 보류합니다.'};
  if(equity<80||equity>101)model={...model,ready:false,blocked:true,note:'국내 현물 주식 비중이 '+num(equity)+'%여서 일반 현물 모델을 적용할 수 없습니다. 파생상품·미확보 종목의 노출 확인이 필요합니다.'};
  rows.forEach((r,i)=>r.target=model.targets[i]);
  peers=catalog.etfs.filter(same);$('#peer-count').textContent='('+peers.length+'개: '+peers.map(e=>e.name).join(', ')+')';$('#peers').disabled=!peers.length;$('#peer-count').textContent=peers.length?'('+peers.length+'개: '+peers.map(e=>e.name).join(', ')+')':'(합산 가능한 ETF 없음)';
  const d=next(selected),warn=[];
  if(lag(hold.asof)>1)warn.push('구성종목 기준 '+hold.asof+' · '+lag(hold.asof)+'거래일 경과');
  if(lag(market.as_of)>2)warn.push('거래대금 자료 지연: '+market.as_of);
  if(!status.ok)warn.push('최근 보고서 데이터 수집 실패 · 직전 자료 사용');
  $('#fund-summary').innerHTML='<h2>'+esc(selected.name)+'</h2><p>'+esc(selected.index_name||'')+' · 순자산 '+money(selected.nav*selected.shares)+'</p><p>예상 효력일 <b>'+esc(d||'미확인')+'</b>'+(d?' · D-'+dateDiff(today,d):'')+(selected.rebalance?.estimated?' · 일정 자동 추정':' · 규칙 기반 예상일')+' · 실제 매매일은 공지 확인</p><p class="small">거래대금 기준 '+esc(market.as_of)+' · 구성 '+esc(hold.asof)+' · 순자산 '+esc(catalog.as_of)+'</p><div class="notice">'+esc(model.note)+'</div>'+(warn.length?'<div class="notice">'+warn.map(esc).join('<br>')+'</div>':'');
  $('#generate').disabled=!!model.blocked;$('#message').textContent=model.ready?'기본 시나리오로 바로 생성할 수 있습니다.':'목표 비중이 미확정입니다. 가정을 입력하거나 현황 보고서를 생성하세요.';
  editor();
 }catch(e){$('#message').textContent='자료를 불러오지 못했습니다. '+e.message;}
}
function editor(){
 $('#target-rows').innerHTML=rows.map((r,i)=>'<tr><td>'+esc(r.name)+' <span class="small">'+r.code+'</span></td><td>'+num(r.current)+'%</td><td><input type="number" min="0" max="100" step="0.0001" aria-label="'+esc(r.name)+' 목표 비중" data-row="'+i+'" value="'+numRaw(r.target)+'"></td></tr>').join('');sumWeights();
}
function numRaw(n){return Math.round(n*1e6)/1e6;}
function sumWeights(){const sum=rows.reduce((s,r)=>s+(Number.isFinite(r.target)?r.target:0),0),current=rows.reduce((s,r)=>s+r.current,0);$('#weight-total').textContent='목표 '+num(sum,4)+'% / 주식 합계 '+num(current,4)+'% (현금 등 유지)';}
$('#target-rows').addEventListener('input',event=>{if(!event.target.dataset.row)return;const i=+event.target.dataset.row;rows[i].target=event.target.value===''?NaN:Number(event.target.value);manual=true;invalidate();sumWeights();$('#message').textContent='입력한 목표 비중으로 생성합니다.';});
$('#scenario-source').addEventListener('input',invalidate);
$('#reset-target').onclick=()=>{rows=rows.filter(r=>r.current>0);model=ImpactModel.defaultTarget(selected,rows,market);rows.forEach((r,i)=>r.target=model.targets[i]);manual=false;$('#scenario-source').value='';editor();invalidate();};
$('#balance').onclick=()=>{const s=rows.reduce((a,r)=>a+r.target,0),budget=rows.reduce((a,r)=>a+r.current,0);if(!(s>0)){ $('#message').textContent='0보다 큰 목표 비중을 먼저 입력해 주세요.';return;}rows.forEach(r=>r.target=r.target/s*budget);manual=true;editor();invalidate();};
$('#add').onclick=()=>{const value=$('#add-stock').value,code=value.match(/[0-9A-Z]{6}/)?.[0]||Object.keys(market.stocks).find(c=>market.stocks[c].name===value);if(!code||!market.stocks[code]){$('#message').textContent='목록에서 국내 주식 종목을 선택해 주세요.';return;}if(rows.some(r=>r.code===code)){$('#message').textContent='이미 포함된 종목입니다.';return;}rows.push({code,name:market.stocks[code].name,current:0,target:0});manual=true;editor();invalidate();$('#add-stock').value='';};
for(const id of ['#remaining','#execution','#peers'])$(id).onchange=invalidate;
$('#reload-data').onclick=()=>{location.href='impact.html?ticker='+encodeURIComponent(selected?.ticker||'');};
$('#horizon').onchange=()=>fillOptions(selected?.ticker);$('#fund').onchange=choose;
function download(name,content,type){const u=URL.createObjectURL(new Blob([content],{type})),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
function sources(etfs){return '<ul class="source-list">'+etfs.map(e=>'<li><a href="'+esc(e.links?.product||'https://data.krx.co.kr')+'" target="_blank" rel="noopener">'+esc(e.name)+' · 운용사 구성종목·상품 공시</a> / <a href="'+esc(e.links?.index_url||'https://data.krx.co.kr')+'" target="_blank" rel="noopener">지수 산출기관</a></li>').join('')+(model.source?'<li><a href="'+esc(model.source)+'" target="_blank" rel="noopener">가중 규칙 참고 원문</a></li>':'')+'<li><a href="https://data-dbg.krx.co.kr" target="_blank" rel="noopener">KRX OPEN API</a>: 일별 실제 거래대금·종가·상장주식수</li><li><a href="https://wcomp.fnguide.com" target="_blank" rel="noopener">FnGuide Company Guide</a>: 보통주 유동주식수. 지수 제공사의 유동계수와 다를 수 있음.</li></ul>';}
function direction(x){return x.amount>0?'상방':x.amount<0?'하방':'중립';}
function level(x,stale){if(stale)return '자료 지연 · 판단 보류';if(Math.abs(x.amount)<1)return '추정 순수요 없음';return x.level===null?'거래대금 부족 · 판단 보류':['작음','보통','큼','매우 큼'][x.level];}
function sentence(x,stale){if(!x)return '유의미한 대상 없음';return esc(x.name)+'의 예상 '+(x.amount>0?'순매수':'순매도')+'는 <b>'+money(Math.abs(x.amount))+'</b>. 5일 평균 하루 거래대금의 <b>'+pct(x.advPct)+'</b>, 유동시총의 '+pct(x.floatPct)+'에 해당합니다. 선택한 집행 기간의 하루 참여율 '+pct(x.participation)+' 기준 <b>'+direction(x)+' 압력 '+level(x,stale)+'</b>으로 분류합니다.'+(x.absorption!==null?' 하루 평균 거래대금의 10%씩 소화한다고 가정하면 약 '+num(x.absorption,1)+'거래일 분량입니다.':'')+(x.floatPct>=1?' 유동시총의 1% 이상에 해당하는 물량으로, 유통물량 집중 부담도 함께 확인해야 합니다.':'')+(x.floatPct===null?' 유동주식 자료가 없어 유통물량 집중도는 판단을 보류합니다.':'');}
$('#generate').onclick=async()=>{
 $('#generate').disabled=true;$('#message').textContent='영향을 계산하는 중…';const chosen=selected,token=version;
 try{
  const now=new Date().toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}),equity=rows.reduce((s,r)=>s+r.current,0),sum=rows.reduce((s,r)=>s+r.target,0);
  if(rows.some(r=>!Number.isFinite(r.target)||r.target<0||r.target>100))throw Error('목표 비중은 0~100 사이 숫자로 입력해 주세요.');
  if(Math.abs(sum-equity)>.05)throw Error('목표 비중 합계가 주식 비중과 다릅니다. 합계를 맞춘 뒤 다시 생성해 주세요.');
  const selectedEtfs=[chosen,...($('#peers').checked?peers:[])],baseline={},warnings=[];
  for(const e of selectedEtfs){const h=await loadHold(e);if(unsupported(h).length)throw Error(e.name+'의 미확보 자산이 있어 합산할 수 없습니다.');const weights={};for(const x of h.holdings)if(market.stocks[x.code]&&x.weight>=0)weights[x.code]=(weights[x.code]||0)+x.weight;
   const total=Object.values(weights).reduce((s,v)=>s+v,0);if(total<80||total>101)throw Error(e.name+'의 현물 노출을 확인할 수 없습니다. 합산을 해제해 주세요.');
   baseline[e.ticker]={weights,equity:total,selectedEquity:equity,date:h.asof};
   if(lag(h.asof)>1)warnings.push(e.name+' 구성 '+h.asof+' ('+lag(h.asof)+'거래일 경과)');
  }
  if(token!==version)return;
  const stale=lag(market.as_of)>2||lag(catalog.as_of)>2||Object.values(baseline).some(p=>lag(p.date)>2||p.date>today)||market.as_of>today||catalog.as_of>today;
  if(stale)warnings.push('자료 지연으로 압력 등급과 투자 판단은 보류합니다. 금액은 표시된 과거 기준의 시나리오입니다.');
  if(!status.ok)warnings.push('가장 최근 원천 수집이 실패했습니다. 직전 수집 자료 기준입니다.');
  const ready=model.ready||manual,source=$('#scenario-source').value.trim(),days=+$('#execution').value,remaining=+$('#remaining').value;
  if(manual&&!source)throw Error('예상안의 근거를 짧게 입력해 주세요. 예: 현재 종목 유지·내 비중 가정');
  let analysis=ready?ImpactModel.calculate(rows,selectedEtfs,baseline,market,remaining,days):null;
  // Include peer-only constituents as exits only in a complete manually supplied / modeled basket.
  if(analysis&&selectedEtfs.length>1){const extras=[...new Set(Object.values(baseline).flatMap(p=>Object.keys(p.weights)))].filter(c=>!rows.some(r=>r.code===c));
   if(extras.length){const extraRows=extras.map(c=>({code:c,name:market.stocks[c].name,current:0,target:0}));analysis=ImpactModel.calculate([...rows,...extraRows],selectedEtfs,baseline,market,remaining,days);warnings.push('같은 지수라도 현물 구성 차이가 있는 '+extras.length+'종은 공통 목표에서 제외되는 것으로 가정했습니다.');}}
  const resultRows=analysis?.rows||[],material=resultRows.filter(x=>Math.abs(x.amount)>=1e6),buy=material.filter(x=>x.amount>0)[0],sell=material.filter(x=>x.amount<0)[0];
  const missingADV=material.filter(x=>x.adv===null).length,missingFloat=material.filter(x=>x.floatCap===null).length;
  if(missingADV)warnings.push('영향 대상 '+missingADV+'종은 온전한 5거래일 거래대금이 없어 압력 등급을 계산하지 않았습니다.');
  if(missingFloat)warnings.push('영향 대상 '+missingFloat+'종의 유동자료는 없거나 수집 후 30일이 지나 유동시총 비교를 제외했습니다.');
  const title=chosen.name+' · 리밸런싱 영향 분석',hypothesis=manual?'사용자 입력 시나리오: '+source:(model.label||'목표 비중 미확정');
  let html='<article class="report-card"><div class="report-actions toolbar"><button id="print-report">인쇄 / PDF 저장</button><button id="save-report">보고서 HTML 저장</button>'+(ready?'<button id="save-csv">종목별 계산표 CSV</button>':'')+'</div><h2>'+esc(title)+'</h2><p class="report-meta">생성 '+esc(now)+' KST · 예상 효력일 '+esc(next(chosen)||'미확인')+(chosen.rebalance?.estimated?' (자동 추정)':' (규칙 기반 예상)')+'<br>순자산 기준 '+esc(catalog.as_of)+' · 구성 '+Object.values(baseline).map(p=>esc(p.date)).filter((v,i,a)=>a.indexOf(v)===i).join(', ')+' · 거래대금 '+market.sessions.map(esc).join(' / ')+'</p><div class="notice">'+esc(hypothesis)+'<br>'+esc(manual?'입력한 구성·목표 비중을 사용합니다. 공지의 진위 및 효력일은 자동 확인하지 않습니다.':model.note)+'</div>';
  if(warnings.length)html+='<div class="notice">'+warnings.map(esc).join('<br>')+'</div>';
  if(analysis){
   html+='<div class="metrics"><div class="metric"><span>예상 매수 합계</span><b class="buy">'+money(analysis.buy)+'</b></div><div class="metric"><span>예상 매도 합계</span><b class="sell">'+money(analysis.sell)+'</b></div><div class="metric"><span>집행 가정</span><b>'+days+'일 / 잔여 '+Math.round(remaining*100)+'%</b></div></div><h3>결론</h3><ul class="conclusion"><li>'+sentence(buy,stale)+'</li><li>'+sentence(sell,stale)+'</li><li>'+selectedEtfs.length+'개 ETF의 가정 수요만 포함합니다. 전체 시장의 패시브 수급 총액이나 예상 주가 등락률로 해석할 수 없습니다.</li></ul>';
   html+='<h3>거래대금 대비 수급 압력</h3><p class="small">선택 기간으로 나눈 하루 예상 매매 / 최근 5일 평균 하루 거래대금. 막대는 상대 크기이며 100%에서 잘라 표시합니다.</p><div class="pressure-bars">'+material.filter(x=>x.participation!==null).slice(0,10).map(x=>'<div class="bar-row"><span>'+esc(x.name)+'</span><div class="bar-track"><div class="bar-fill '+(x.amount<0?'sell':'')+'" style="width:'+Math.min(100,x.participation)+'%"></div></div><span>'+direction(x)+' '+pct(x.participation)+'</span></div>').join('')+'</div>';
   html+='<h3>종목별 예상 영향</h3><p class="small">표를 좌우로 움직이면 유동자료 기준일과 압력 등급까지 볼 수 있습니다.</p><div class="tbl-scroll"><table class="impact-table"><thead><tr><th>종목</th><th>변경 구분</th><th>현재 → 목표</th><th>순매매</th><th>추정 주식 수</th><th>5일 평균 거래대금</th><th>거래대금 대비</th><th>하루 참여율</th><th>유동시총</th><th>유동시총 대비</th><th>유동자료 수집일</th><th>압력</th></tr></thead><tbody>'+resultRows.map(x=>'<tr><td class="stockname">'+esc(x.name)+'<br><span class="small">'+x.code+'</span></td><td>'+(x.current===0&&x.target>0?'편입 가정':x.current>0&&x.target===0?'편출 가정':Math.abs(x.target-x.current)<.0001?'유지':'비중 조정')+'</td><td>'+num(x.current)+' → '+num(x.target)+'%</td><td class="'+(x.amount<0?'sell':'buy')+'">'+money(x.amount)+'</td><td>'+num(x.shares,0)+'</td><td>'+money(x.adv)+'</td><td>'+pct(x.advPct)+'</td><td>'+pct(x.participation)+'</td><td>'+money(x.floatCap)+'</td><td>'+pct(x.floatPct)+'</td><td>'+(x.stock.float_source?'<a href="'+esc(x.stock.float_source)+'" target="_blank" rel="noopener">'+esc(x.stock.float_fetched_at||'미확보')+'</a>':'미확보')+'</td><td>'+direction(x)+' · '+level(x,stale)+'</td></tr>').join('')+'</tbody></table></div><p class="small">현재·목표 비중은 선택한 ETF 기준. 합산 시 금액은 각 ETF의 현재 비중·순자산·현금 비중을 따로 계산합니다. 양수는 순매수, 음수는 순매도입니다. 유동시총 비교는 방향을 제외한 절대 규모입니다.</p>';
  }else html+='<h3>판단 보류 · 예상 변경안 필요</h3><p>현재 구성만으로 다음 정기변경의 편입·편출이나 목표 비중을 확정할 수 없습니다. “예상 편입·편출 / 목표 비중 조정”에서 가정을 입력하면 종목별 수급 압력을 계산합니다. 변경안 미확보를 수급 영향 0으로 처리하지 않습니다.</p>';
  html+='<h3>등록된 구성·가중 규칙</h3><p>'+esc(chosen.cap?.label||'규칙 미확인')+'</p><p class="small">'+esc(chosen.cap?.note||'')+'<br>규칙 근거: '+esc(chosen.cap?.source||'미확보')+'</p><h3>가정과 계산 방법</h3><div class="method"><ul><li>예상 매매 = 순자산총액(NAV × 상장좌수) × (목표 비중 − 현재 비중) × 미집행 비율. 순자산·가격·설정좌수와 현재 현금 비중은 유지합니다.</li><li>최근 5거래일 <b>실제 거래대금의 산술평균</b>을 사용합니다. 종가 × 거래량으로 대신하지 않습니다. 거래정지의 0 거래대금은 포함하고, 신규상장 등 5일 미확보는 산출에서 제외합니다.</li><li>유동시총 = FnGuide 보통주 유동주식수 × KRX 종가. 수집일은 주주자료의 효력일이 아니며, 지수 제공사의 유동계수·보호예수와 차이가 있을 수 있습니다.</li><li>압력 등급은 하루 참여율 기준 5% 미만 작음, 5~20% 보통, 20~50% 큼, 50% 이상 매우 큼. 비교용 휴리스틱이며 과거 수익률로 보정한 예측모형이 아닙니다. 유동시총 대비 비율은 물량 집중도를 별도로 보여줍니다.</li><li>소화일수는 절대 매매금액 ÷ (5일 평균 거래대금 × 10%)로 환산한 비교치입니다. 1일 가정에도 분모는 하루 전체 거래대금입니다. 종가 동시호가 체결량과 같지 않습니다. 현물 바스켓 이전·선집행·가격 변동·다른 ETF의 반대 수급에 따라 실제 장내 압력은 달라집니다.</li><li>확정 공지 전의 예상 종목·비중과 규칙 기반 일정은 변경될 수 있습니다. 합산 범위 밖 ETF·연기금·해외 펀드는 포함하지 않습니다.</li></ul></div><h3>분석 범위·출처</h3><p>'+selectedEtfs.map(e=>esc(e.name)+' ('+money(e.nav*e.shares)+')').join(' · ')+'</p>'+sources(selectedEtfs)+'</article>';
  $('#report').innerHTML=html;lastReport={title,analysis,date:today,etfs:selectedEtfs,baseline,days,remaining,hypothesis};
  $('#print-report').onclick=()=>window.print();
  $('#save-report').onclick=async()=>{const clone=$('#report').cloneNode(true);clone.querySelector('.report-actions')?.remove();const css=await (await fetch('assets/impact.css')).text();download('ETF_'+chosen.ticker+'_'+today+'.html','<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title><style>body{font-family:system-ui,sans-serif;max-width:1300px;margin:20px auto;padding:15px}table{border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #ddd}.tbl-scroll{overflow-x:auto}'+css+'</style>'+clone.innerHTML+'</html>','text/html;charset=utf-8');};
  if(ready)$('#save-csv').onclick=()=>{const cell=x=>'"'+(typeof x==='number'?String(x):String(x??'').replace(/^(?=[0-9][0-9A-Z]{5}$)/,"'").replace(/^[=+@\-\t\r]/,"'")).replace(/"/g,'""')+'"';const data=[['분석 ETF','효력 예정일','자료 기준일','가정','종목코드','종목명','현재 비중%','목표 비중%','예상 순매매 원','5일 평균 거래대금 원','거래대금 대비%','하루 참여율%','유동시총 원','유동시총 대비%','유동자료 수집일','집행일수','미집행 비율','기여 ETF','ETF별 순매매 원']];for(const x of analysis.rows)for(const c of x.contributions)data.push([chosen.name,next(chosen),market.as_of,hypothesis,x.code,x.name,x.current,x.target,x.amount,x.adv,x.advPct,x.participation,x.floatCap,x.floatPct,x.stock.float_fetched_at,days,remaining,c.name,c.amount]);download('ETF_'+chosen.ticker+'_'+today+'.csv','\ufeff'+data.map(r=>r.map(cell).join(',')).join('\r\n'),'text/csv;charset=utf-8');};
  $('#message').textContent=ready?'보고서 생성 완료':'현황 보고서 생성 · 목표 비중 미확정';$('#report').scrollIntoView({behavior:'smooth'});
 }catch(e){$('#message').textContent=e.message;}finally{if(token===version)$('#generate').disabled=!!model.blocked;}
};
try{
 const data=await Promise.all([PE.loadJSON('data/etfs.json',true),PE.loadJSON('data/impact/market.json',true),PE.loadJSON('data/holidays.json'),PE.loadJSON('data/impact/status.json',true)]);
 [catalog,market]=data;holidays=new Set(data[2].dates||[]);status=data[3];
 $('#stock-list').innerHTML=Object.values(market.stocks).map(s=>'<option value="'+esc(s.code+' '+s.name)+'"></option>').join('');
 const initial=query.get('ticker');const e=catalog.etfs.find(e=>e.ticker===initial);
 if(e&&(!next(e)||dateDiff(today,next(e))>31))$('#horizon').value='9999';
 fillOptions(initial);
}catch(e){$('#message').textContent='보고서용 자료를 불러오지 못했습니다. 잠시 후 다시 열어 주세요. '+e.message;}
})();
