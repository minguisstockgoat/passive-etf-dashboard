/* Pure, deterministic scenario math. All weights are percentage points, money KRW. */
(function(g){'use strict';
const number=x=>typeof x==='number'&&Number.isFinite(x);
function allocate(base,caps,total){
 if(!base.length||caps.reduce((a,b)=>a+b,0)<total-1e-7)throw Error('상한 안에서 주식 비중을 배분할 수 없습니다. 목표 비중을 직접 확인하세요.');
 const out=base.map(()=>0);let active=base.map((_,i)=>i),left=total;
 for(let n=0;n<=base.length&&active.length;n++){
  const sum=active.reduce((s,i)=>s+base[i],0);if(sum<=0)throw Error('가중치 근거가 부족합니다.');
  const hit=active.filter(i=>left*base[i]/sum>caps[i]+1e-8);
  if(!hit.length){active.forEach(i=>out[i]=left*base[i]/sum);return out;}
  hit.forEach(i=>{out[i]=caps[i];left-=caps[i];});active=active.filter(i=>!hit.includes(i));
 }
 return out;
}
function defaultTarget(e,rows,market){
 const total=rows.reduce((s,r)=>s+r.current,0),cap=e.cap||{},current=rows.map(r=>r.current);
 if(/레버리지|인버스|선물|합성|커버드콜/.test(e.name))return {ready:false,targets:current,note:'파생상품·레버리지 노출은 현물 비중 차이만으로 계산할 수 없어 자동 추정에서 제외합니다.',blocked:true};
 if(e.ticker==='466920'){
  const top=['010140','042660','329180'];
  if(top.every(c=>rows.some(r=>r.code===c))&&rows.length===13){
   const rest=rows.filter(r=>!top.includes(r.code));
   const floats=rest.map(r=>market.stocks[r.code]?.float_cap);
   // Vendor float is a proxy for the methodology; preserve explicit assumption in every report.
   const usable=rest.every((r,i)=>number(floats[i])&&floats[i]>0&&market.stocks[r.code].float_fetched_at&&Math.abs(Date.parse(market.as_of)-Date.parse(market.stocks[r.code].float_fetched_at))<=30*86400000);
   const weights=allocate(usable?floats:rest.map(r=>r.current),rest.map(()=>total*.20),total*.25);
   let k=0;return {ready:true,targets:rows.map(r=>top.includes(r.code)?total*.25:weights[k++]),
    note:'현 구성 13종·조선 TOP3 유지 가정. TOP3 각각 지수 비중 25%, 나머지 25%는 '+(usable?'FnGuide 유동시총 대용치 가중':'현재 구성비중 비례 배분(유동자료 미확보)')+'·종목당 20% 상한. ETF 현금 비중 유지. 편입·편출 선정과 향후 가격 변화는 미반영.',
    source:'https://www.soletf.com/api/etf/pds/down/policyDescription/211028?type=description',label:'구성 유지 · 정기 가중 재설정 시나리오'};
  }
 }
 if(cap.verified&&!cap.index_exception&&cap.single_cap>0&&/^(단일종목|종목별|종목당|개별종목)\s*\d+(\.\d+)?%\s*(상한|실링)/.test(cap.label||'')){
  try{return {ready:true,targets:allocate(current,current.map(()=>cap.single_cap*total),total),note:'현재 구성종목·현금 비중 유지. 현 비중을 출발점으로 '+cap.single_cap*100+'% 상한을 적용하고 잔여 종목에 비례 재배분합니다. 실제 지수의 종목 선정·가중 산출을 완전히 재현한 결과가 아닙니다.',source:e.links?.product,label:'구성 유지 · 상한 조정 시나리오'};}catch(err){return {ready:false,targets:current,note:err.message};}
 }
 return {ready:false,targets:current,note:'확정 변경안 또는 검증된 목표 비중이 없습니다. 현재 보유 비중을 편집용으로 표시합니다. 예상 편입·편출과 목표 비중을 입력하면 영향 보고서를 생성할 수 있습니다.'};
}
function calculate(rows,etfs,baseline,market,remaining,days){
 const out=[];let buy=0,sell=0;
 for(const r of rows){
  let amount=0;const contributions=[];
  for(const e of etfs){const aum=e.nav*e.shares;if(!(aum>0))throw Error(e.name+' 순자산총액 미확보');const p=baseline[e.ticker];
   const target=r.target/p.selectedEquity*p.equity,previous=p.weights[r.code]||0;
   const flow=aum*(target-previous)/100*remaining;amount+=flow;contributions.push({ticker:e.ticker,name:e.name,amount:flow,current:previous,target});
  }
  const s=market.stocks[r.code]||{},adv=number(s.adtv5)&&s.adtv5>0?s.adtv5:null;
  const floatFresh=s.float_fetched_at&&Math.abs(Date.parse(market.as_of)-Date.parse(s.float_fetched_at))<=30*86400000;
  const ff=floatFresh&&number(s.float_cap)&&s.float_cap>0?s.float_cap:null;
  const advPct=adv?Math.abs(amount)/adv*100:null,participation=advPct===null?null:advPct/days,floatPct=ff?Math.abs(amount)/ff*100:null;
  const level=participation===null?null:participation<5?0:participation<20?1:participation<50?2:3;
  if(amount>0)buy+=amount;else sell-=amount;
  out.push({...r,amount,shares:s.close>0?amount/s.close:null,adv,advPct,participation,floatCap:ff,floatPct,level,stock:s,contributions,absorption:adv?Math.abs(amount)/(adv*.1):null});
 }
 out.sort((a,b)=>(b.participation??-1)-(a.participation??-1)||Math.abs(b.amount)-Math.abs(a.amount));
 return {rows:out,buy,sell,net:buy-sell};
}
g.ImpactModel={allocate,defaultTarget,calculate};
})(typeof window!=='undefined'?window:globalThis);
