"""Local dashboard — stdlib ``http.server`` only, zero dependencies.

Reads (all take the combined filter: exclude=&include=&from=&to=&modes=&teammate=):
    GET  /                  the dashboard page
    GET  /api/dashboard     overview + daily + by_hour + filtered games + tags
                            + modes + teammates, in ONE request (games() memoised)
    GET  /api/game/<id>     roster, raw lines, derived metrics
    GET  /api/upgrades      experimental: upgrades/prot vs win rate & length
    GET  /api/unparsed      new-cosmetic tripwire
    GET  /api/settings      player / log path / detected names / clients
    GET  /api/version       version + update availability
POST /api/tags {name}   ·  /api/game/<gid>/tag/<tid>  ·  /api/settings {..}

Every number comes from Store.* (the tested code); the filter bar just supplies
arguments, so the tiles/graphs always describe exactly the filtered game list.
This viewer is functional, not final — a visual revamp lands once features settle.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

from .db import Store
from .version import __version__, check_update

_TOGGLE = re.compile(r"^/api/game/(\d+)/tag/(\d+)$")
_TAG_SET = re.compile(r"^/api/game/(\d+)/tag/(\d+)/set$")
_GAME = re.compile(r"^/api/game/(\d+)$")
_GAME_RESOLVE = re.compile(r"^/api/game/(\d+)/resolve$")
_TAG_DELETE = re.compile(r"^/api/tags/(\d+)/delete$")
_TAG_RENAME = re.compile(r"^/api/tags/(\d+)/rename$")
_TAG_COLOR = re.compile(r"^/api/tags/(\d+)/color$")
_DEVICE_REVOKE = re.compile(r"^/api/cloud/devices/([A-Za-z0-9_-]+)/revoke$")
_BRIDGING_SESSION = re.compile(r"^/api/bridging/session/(\d+)$")
# IGN charset validated in the route rather than interpolated into the path
_PLAYER_GAMES = re.compile(r"^/api/players/([A-Za-z0-9_]{1,16})/games$")

# The React frontend build (frontend/dist). When it exists it is served at /;
# without it the embedded fallback page below keeps working, so deleting the
# dist folder reverts to the old viewer.
#
# Frozen (PyInstaller onefile): the package lives in the temp _MEIPASS unpack
# dir, so the source-tree path above resolves to nothing and the exe would
# silently serve the legacy viewer. The build bundles dist as "frontend/dist"
# inside _MEIPASS — look there first.
def _dist_dir() -> str:
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return os.path.join(bundle, "frontend", "dist")
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")


DIST_DIR = _dist_dir()

# Explicit types: on Windows, mimetypes reads the registry and can call .js
# "text/plain", which browsers reject for ES module scripts.
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".map": "application/json",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain",
}


def dist_file(url_path: str) -> Optional[str]:
    """Map a URL path to a file in frontend/dist, or None when no build exists.

    Traversal-safe: the resolved path must stay inside dist. Unknown non-API
    paths fall back to index.html (SPA shell).
    """
    root = os.path.realpath(DIST_DIR)
    if not os.path.isfile(os.path.join(root, "index.html")):
        return None
    rel = url_path.lstrip("/") or "index.html"
    cand = os.path.realpath(os.path.join(root, rel))
    if cand != root and not cand.startswith(root + os.sep):
        return None
    if os.path.isfile(cand):
        return cand
    return os.path.join(root, "index.html")

_PAGE = r"""<!doctype html><meta charset=utf-8>
<title>Rivult Tracker</title>
<style>
 :root{--bg:#0d0f14;--card:#161b24;--card2:#1b212c;--line:#242c3a;--ink:#e8ecf4;
   --mut:#8b93a7;--grn:#7ee787;--red:#ff7b72;--yel:#e3b341;--blu:#58a6ff}
 *{box-sizing:border-box}
 body{background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,Segoe UI,sans-serif;margin:0;padding:18px;max-width:1120px}
 h1{font-size:19px;margin:0;display:inline} .sub{color:var(--mut);margin:2px 0 12px}
 .gear{float:right;cursor:pointer;color:var(--mut);font-size:18px}
 .tiles{display:grid;grid-template-columns:repeat(8,1fr);gap:8px;margin-bottom:12px}
 .tile{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:8px 10px}
 .tile .k{color:var(--mut);font-size:10px;text-transform:uppercase;letter-spacing:.03em}
 .tile .v{font-size:19px;font-weight:650;margin-top:1px}
 .panel{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:10px 12px;margin-bottom:10px}
 .panel .k{color:var(--mut);font-size:10px;text-transform:uppercase;letter-spacing:.03em;margin-bottom:4px}
 svg{display:block;width:100%}
 .row{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:7px 0}
 .lbl{color:var(--mut);font-size:11px;text-transform:uppercase;margin-right:2px}
 .chip{border:1px solid var(--line);border-radius:999px;padding:2px 10px;cursor:pointer;user-select:none;font-size:12px;color:var(--mut);background:var(--card2)}
 .chip.only{color:#0d0f14;background:var(--grn);border-color:var(--grn)}
 .chip.excl{color:#0d0f14;background:var(--red);border-color:var(--red);text-decoration:line-through}
 .chip.on{color:#0d0f14;background:var(--blu);border-color:var(--blu)}
 .chip.ro{cursor:default;padding:1px 7px;font-size:11px}
 select,input,button{background:var(--card2);border:1px solid var(--line);color:var(--ink);border-radius:6px;padding:3px 7px;font:inherit}
 button{cursor:pointer} .preset.on{background:var(--blu);color:#0d0f14;border-color:var(--blu)}
 table{border-collapse:collapse;width:100%}
 th,td{text-align:right;padding:4px 7px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
 th{color:var(--mut);font-weight:500;font-size:11px;text-transform:uppercase;cursor:pointer}
 th.l,td.l{text-align:left} tr.g{cursor:pointer} tr.g:hover{background:var(--card)}
 .W{color:var(--grn)} .L{color:var(--red)} .U{color:var(--yel)}
 .mates{color:var(--mut);font-size:12px} .mode{color:var(--blu);font-size:12px} .map{color:var(--mut);font-size:12px}
 .detail{background:var(--card);border:1px solid var(--line)}
 .detail td{border:0;padding:12px} .metrics{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:6px}
 .metrics b{color:var(--blu)} .rl{margin:4px 0;font-size:12px;color:var(--mut)}
 .rl .you{color:var(--grn)} .rl .mate{color:var(--blu)}
 .log{max-height:240px;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px;font:12px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap}
 .log .final{color:var(--red)} .log .bed{color:var(--yel)} .log .win{color:var(--grn)}
 .log .who,.log .noise{color:#5b6472} .log .unparsed{color:var(--blu)}
 #menu{position:absolute;background:var(--card2);border:1px solid var(--line);border-radius:8px;padding:4px;display:none;z-index:9;box-shadow:0 6px 20px #0008}
 #menu .mi{padding:4px 12px;border-radius:5px;cursor:pointer;font-size:13px;white-space:nowrap}
 #menu .mi:hover{background:var(--card)} #menu .hd{color:var(--mut);font-size:11px;padding:2px 12px}
 dialog{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:12px;padding:18px;max-width:520px}
 dialog h3{margin:0 0 10px} dialog label{display:block;color:var(--mut);font-size:12px;margin:10px 0 3px}
 dialog input,dialog select{width:100%} .banner{background:#1f3a1f;border:1px solid var(--grn);border-radius:8px;padding:8px 12px;margin-bottom:10px}
 details{margin-top:14px} summary{cursor:pointer;color:var(--mut)} .up{font:12px/1.6 ui-monospace,monospace;color:var(--mut)}
 .hint{color:var(--mut);font-size:12px}
</style>
<span class=gear onclick="settings.showModal()">&#9881;</span>
<h1>Rivult Tracker</h1>
<div class=sub id=sub>every game from your log — right-click a row to tag it</div>
<div id=updbanner></div>

<div class=tiles id=tiles></div>
<div class=panel><div class=k id=dailyk>daily FKDR</div><svg id=daily viewBox="0 0 1000 120" preserveAspectRatio=none></svg></div>
<div class=panel><div class=k>when you play best (FKDR by hour of day)</div><svg id=byhour viewBox="0 0 1000 110"></svg></div>

<div class=row><span class=lbl>tags</span><span id=ftags></span></div>
<div class=row><span class=lbl>mode</span><span id=fmodes></span></div>
<div class=row>
  <span class=lbl>with</span>
  <select id=fmate><option value="">anyone</option></select>
  <span class=lbl>dates</span>
  <button class=preset data-d=all>all</button><button class=preset data-d=0>today</button>
  <button class=preset data-d=7>7d</button><button class=preset data-d=30>30d</button>
  <input type=date id=from><span class=hint>–</span><input type=date id=to>
  <span class=lbl>sort</span>
  <select id=sort><option value=date>date</option><option value=fkdr>FKDR</option>
    <option value=length>length</option><option value=teammate>teammate</option>
    <option value=mode>mode</option><option value=map>map</option>
    <option value=result>result</option><option value=beds>beds</option>
    <option value=finals>finals</option></select>
  <button id=dir title="flip direction">▼</button>
  <button onclick=clearFilters()>clear</button>
  <input id=newtag placeholder="new tag" size=8><button onclick=addTag()>+tag</button>
  <button id=refresh title="re-read the log for new games">&#8635; refresh</button>
  <span id=syncmsg class=hint></span>
</div>

<div id=count class=hint></div>
<div id=app>loading…</div>
<div id=menu></div>

<details id=upwrap><summary>experimental: diamond upgrades vs winning</summary><div id=upg class=hint></div></details>
<details id=unpwrap><summary>UNPARSED lines (tripwire)</summary><div class=up id=unp></div></details>

<dialog id=settings>
 <h3>Settings</h3>
 <label>Your Minecraft name (blank = auto-detect, which handles renames)</label>
 <input id=setPlayer placeholder="auto">
 <div class=hint id=setNames></div>
 <label>Log file path</label>
 <select id=setClients></select>
 <input id=setLog placeholder="path to latest.log">
 <label>Update URL (GitHub releases API)</label>
 <input id=setUpd placeholder="default">
 <div class=row style=margin-top:14px>
   <button onclick=saveSettings()>save</button>
   <button onclick="settings.close()">cancel</button>
   <span class=hint id=setMsg></span>
 </div>
</dialog>

<script>
let D={}, F={tags:{}, modes:new Set(), mate:'', from:'', to:'', sort:'date', dir:-1}, OPEN=null;
const $=id=>document.getElementById(id);
const mmss=s=>s==null?'—':Math.floor(s/60)+':'+String(s%60).padStart(2,'0');
const playfmt=s=>{const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return h?h+'h '+m+'m':m+'m'};
const esc=s=>(''+s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function qs(){const p=new URLSearchParams();
  const inc=Object.keys(F.tags).filter(n=>F.tags[n]==='only'),ex=Object.keys(F.tags).filter(n=>F.tags[n]==='excl');
  if(inc.length)p.set('include',inc.join(','));if(ex.length)p.set('exclude',ex.join(','));
  if(F.modes.size)p.set('modes',[...F.modes].join(','));if(F.mate)p.set('teammate',F.mate);
  if(F.from)p.set('from',F.from);if(F.to)p.set('to',F.to);return p.toString()}

async function reload(){D=await fetch('/api/dashboard?'+qs()).then(r=>r.json());render()}

function render(){
  const s=D.overview;
  if(D.you)$('sub').textContent=`tracking ${D.you} — right-click a row to tag it`;
  $('tiles').innerHTML=[['games',s.games],['W / L',s.wins+' / '+s.losses],
    ['win %',s.games?Math.round(100*s.wins/s.games)+'%':'—'],['FKDR',s.fkdr],
    ['clutch %',s.clutch_rate+'%'],['avg finals',s.avg_finals],['avg beds',s.avg_beds],
    ['playtime',playfmt(s.playtime_s)]].map(t=>`<div class=tile><div class=k>${t[0]}</div><div class=v>${t[1]}</div></div>`).join('');
  $('dailyk').textContent=`daily FKDR · ${s.sessions} sessions · ${s.avg_games_per_session} games/session · avg game ${mmss(s.avg_game_s)}`;
  drawDaily(D.daily); drawHours(D.by_hour);
  // filter chips
  $('ftags').innerHTML=D.tags.map(t=>{const st=F.tags[t.name],c=st==='only'?'only':st==='excl'?'excl':'';
    return `<span class="chip ${c}" style="${c?'':'border-color:'+t.color}" onclick="cycleTag('${t.name}')">${t.name}</span>`}).join('');
  $('fmodes').innerHTML=D.modes.map(m=>`<span class="chip ${F.modes.has(m)?'on':''}" onclick="toggleMode('${m}')">${m}</span>`).join('');
  const mate=$('fmate'); if(mate.dataset.n!=D.teammates.length){mate.dataset.n=D.teammates.length;
    mate.innerHTML='<option value="">anyone</option>'+D.teammates.map(t=>`<option value="${t.ign}">${t.ign} (${t.games})</option>`).join('');mate.value=F.mate}
  // sortable list
  const gs=D.games.slice().sort(cmp);
  $('count').textContent=`${gs.length} games`+ (qs()?' (filtered)':'');
  let h=`<table><tr>${['date','start','mode','map','res','K','FK','D','FD','beds','len','with','tags'].map(c=>`<th class="${['date','start','mode','map','res','with','tags'].includes(c)?'l':''}">${c}</th>`).join('')}</tr>`;
  for(const g of gs){
    const res=g.result==='WIN'?['W','WIN']:g.result==='FINAL_DEATH'?['L','LOSS']:['U','?'];
    const tg=g.tags.map(n=>{const t=D.tags.find(t=>t.name===n)||{};return `<span class="chip ro" style="background:${t.color};border-color:${t.color};color:#0d0f14">${n}</span>`}).join(' ');
    h+=`<tr class=g data-gid=${g.id} onclick="openGame(${g.id})">
      <td class=l>${g.date||'?'}</td><td class=l>${g.start_ts}</td><td class="l mode">${g.mode||'?'}</td>
      <td class="l map">${g.map||''}</td><td class="l ${res[0]}">${res[1]}</td>
      <td>${g.your_kills}</td><td>${g.your_final_kills}</td><td>${g.your_deaths}</td><td>${g.your_final_deaths}</td>
      <td>${g.beds_broken}</td><td>${mmss(g.duration_s)}</td>
      <td class="l mates">${g.teammates.join(', ')||''}</td><td class=l>${tg}</td></tr>`;
    if(OPEN===g.id)h+=`<tr><td colspan=13 style=padding:0><div class=detail id=det${g.id}>…</div></td></tr>`;
  }
  $('app').innerHTML=gs.length?h+'</table>':'No games match the filters.';
  if(OPEN)fillDetail(OPEN);
  loadUpgrades();
}
function cmp(a,b){let r;const fk=g=>g.your_final_deaths?g.your_final_kills/g.your_final_deaths:g.your_final_kills;
  switch(F.sort){
    case 'fkdr':r=fk(a)-fk(b);break; case 'length':r=(a.duration_s||0)-(b.duration_s||0);break;
    case 'teammate':r=(a.teammates[0]||'~').localeCompare(b.teammates[0]||'~');break;
    case 'mode':r=(a.mode||'').localeCompare(b.mode||'');break; case 'map':r=(a.map||'').localeCompare(b.map||'');break;
    case 'result':r=(a.result||'').localeCompare(b.result||'');break; case 'beds':r=a.beds_broken-b.beds_broken;break;
    case 'finals':r=a.your_final_kills-b.your_final_kills;break;
    default:r=((a.date||'')+a.start_ts).localeCompare((b.date||'')+b.start_ts);}
  return r*F.dir;
}
$('sort').onchange=e=>{F.sort=e.target.value;render()};
$('dir').onclick=()=>{F.dir*=-1;$('dir').textContent=F.dir<0?'▼':'▲';render()};
function cycleTag(n){F.tags[n]=F.tags[n]==='only'?'excl':F.tags[n]==='excl'?undefined:'only';if(!F.tags[n])delete F.tags[n];reload()}
function toggleMode(m){F.modes.has(m)?F.modes.delete(m):F.modes.add(m);reload()}
$('fmate').onchange=e=>{F.mate=e.target.value;reload()};
$('from').onchange=e=>{F.from=e.target.value;setPreset(null);reload()};
$('to').onchange=e=>{F.to=e.target.value;setPreset(null);reload()};
// LOCAL date, not toISOString (UTC): at 11pm local, UTC is already tomorrow
// and a "today" filter would match nothing.
const localISO=d=>d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
document.querySelectorAll('.preset').forEach(b=>b.onclick=()=>{const d=b.dataset.d;
  if(d==='all'){F.from='';F.to=''}else{
    F.to=localISO(new Date());F.from=localISO(new Date(Date.now()-d*864e5))}
  $('from').value=F.from;$('to').value=F.to;setPreset(b);reload()});
$('refresh').onclick=async()=>{const btn=$('refresh');btn.disabled=true;
  $('syncmsg').textContent='reading log…';
  try{const r=await fetch('/api/sync',{method:'POST'}).then(r=>r.json());
    $('syncmsg').textContent=r.error?r.error:
      `${r.log}: ${r.synced} games synced`+(r.in_progress?' · one in progress — appears when it ends':'');
  }catch(e){$('syncmsg').textContent='sync failed: '+e}
  btn.disabled=false;reload()};
function setPreset(b){document.querySelectorAll('.preset').forEach(x=>x.classList.toggle('on',x===b))}
function clearFilters(){F.tags={};F.modes.clear();F.mate='';F.from='';F.to='';$('from').value='';$('to').value='';setPreset(null);reload()}

function openGame(id){OPEN=OPEN===id?null:id;render()}
async function fillDetail(id){const el=$('det'+id);if(!el)return;
  const d=await fetch('/api/game/'+id).then(r=>r.json());
  const b2d=d.bed_to_death_s!=null?`<b>${mmss(d.bed_to_death_s)}</b> bed→death`:'';
  const you=d.roster.filter(r=>r.is_you).map(r=>`<span class=you>${r.ign}</span>`).join('');
  const mates=d.roster.filter(r=>r.is_teammate).map(r=>`<span class=mate>${r.ign}</span>`).join(', ');
  const opp=d.roster.filter(r=>!r.is_you&&!r.is_teammate).map(r=>r.ign);
  const log=d.lines.map(l=>{const k=l.kind,cls=k==='kill'?(l.raw.endsWith('FINAL KILL!')?'final':''):k;
    const raw=l.raw.replace(/^\[[0-9:]+\] \[Client thread\/INFO\]: \[CHAT\] /,'').replace(/§./g,'');
    return `<span class=${cls}>${esc(raw)}</span>`}).join('\n');
  el.innerHTML=`<div class=metrics><span>${d.mode||'?'}${d.map?' · '+d.map:''}</span><span>${mmss(d.duration_s)} long</span>
    ${b2d?'<span>'+b2d+'</span>':''}<span>${d.your_final_kills} FK / ${d.your_final_deaths} FD</span>
    ${d.est_diamonds?'<span>~'+d.est_diamonds+'💎 · prot '+d.prot_level+'</span>':''}</div>
    <div class=rl>you ${you} · team ${mates||'—'} · <b>${opp.length}</b> opp: ${opp.join(', ')}</div>
    <div class=log>${log}</div>`;
}
const menu=$('menu');
document.addEventListener('contextmenu',e=>{const tr=e.target.closest('tr.g');if(!tr)return;e.preventDefault();
  const gid=+tr.dataset.gid,g=D.games.find(g=>g.id===gid);
  menu.innerHTML='<div class=hd>tag this game</div>'+D.tags.map(t=>{const on=g.tags.includes(t.name);
    return `<div class=mi onclick="tagGame(${gid},${t.id},'${t.name}')">${on?'✓':'&nbsp;&nbsp;'} ${t.name}</div>`}).join('');
  menu.style.left=e.pageX+'px';menu.style.top=e.pageY+'px';menu.style.display='block'});
document.addEventListener('click',e=>{if(!menu.contains(e.target))menu.style.display='none'});
async function tagGame(gid,tid,name){menu.style.display='none';
  await fetch(`/api/game/${gid}/tag/${tid}`,{method:'POST'});reload()}
async function addTag(){const n=$('newtag').value.trim();if(!n)return;
  await fetch('/api/tags',{method:'POST',body:JSON.stringify({name:n})});$('newtag').value='';reload()}

function drawDaily(days){if(!days.length){$('daily').innerHTML='';return}
  const W=1000,n=days.length,bw=W/n,max=Math.max(4,...days.map(d=>d.fkdr));let s='';
  days.forEach((d,i)=>{const h=110*d.fkdr/max,col=d.fkdr>=3?'#7ee787':d.fkdr>=1.5?'#e3b341':'#ff7b72';
    s+=`<rect x=${(i*bw).toFixed(1)} y=${(112-h).toFixed(1)} width=${Math.max(1,bw-1).toFixed(1)} height=${h.toFixed(1)} fill="${col}"><title>${d.date}: FKDR ${d.fkdr} (${d.games}g ${d.wins}W)</title></rect>`});
  s+=`<text x=2 y=12 fill=#8b93a7 font-size=11>${max.toFixed(1)}</text>`;$('daily').innerHTML=s}
function drawHours(hrs){if(!hrs.length){$('byhour').innerHTML='';return}
  const max=Math.max(2,...hrs.map(h=>h.fkdr)),bw=1000/24;let s='';
  for(const h of hrs){const bh=88*h.fkdr/max,x=h.hour*bw,col=h.fkdr>=3?'#7ee787':h.fkdr>=1.5?'#e3b341':'#ff7b72';
    s+=`<rect x=${(x+2).toFixed(1)} y=${(92-bh).toFixed(1)} width=${(bw-4).toFixed(1)} height=${bh.toFixed(1)} fill="${col}"><title>${h.hour}:00 — FKDR ${h.fkdr}, ${h.winrate}% win, ${h.games}g</title></rect>`;
    s+=`<text x=${(x+bw/2).toFixed(1)} y=106 fill=#5b6472 font-size=9 text-anchor=middle>${h.hour}</text>`}
  $('byhour').innerHTML=s}

async function loadUpgrades(){const u=await fetch('/api/upgrades?'+qs()).then(r=>r.json());
  const row=r=>`prot ${r.bucket}: ${r.winrate}% win, ${r.games}g, avg ${mmss(r.avg_len_s)}`;
  const drow=r=>`${r.bucket==0?'0':r.bucket==33?'33+':'≤'+r.bucket}💎: ${r.winrate}% win, ${r.games}g, avg ${mmss(r.avg_len_s)}`;
  $('upg').innerHTML='<b>by protection tier</b><br>'+u.by_prot.map(row).join('<br>')+
    '<br><br><b>by estimated diamonds spent</b><br>'+u.by_diamonds.map(drow).join('<br>')+
    '<br><span class=hint>diamond costs are estimates (Hypixel rebalances prices)</span>'}
async function loadUnparsed(){const u=await fetch('/api/unparsed').then(r=>r.json());
  $('unpwrap').querySelector('summary').textContent=`UNPARSED lines (${u.length} distinct — tripwire)`;
  $('unp').innerHTML=u.slice(0,50).map(r=>`${String(r.n).padStart(4)}  ${esc(r.raw.replace(/^\[[0-9:]+\][^:]*: \[CHAT\] /,'').replace(/§./g,'').slice(0,110))}`).join('<br>')}

// settings
async function openSettings(){const s=await fetch('/api/settings').then(r=>r.json());
  $('setPlayer').value=s.player;$('setLog').value=s.log_path;$('setUpd').value=s.update_url;
  $('setNames').textContent=s.detected_names.length?'detected over time: '+s.detected_names.join(', '):'';
  $('setClients').innerHTML='<option value="">— detected clients —</option>'+
    s.clients.map(c=>`<option value="${c.path}">${c.label}: ${c.path}</option>`).join('')}
$('setClients').onchange=e=>{if(e.target.value)$('setLog').value=e.target.value};
async function saveSettings(){$('setMsg').textContent='saving…';
  await fetch('/api/settings',{method:'POST',body:JSON.stringify({
    player:$('setPlayer').value.trim(),log_path:$('setLog').value.trim(),update_url:$('setUpd').value.trim()})});
  $('setMsg').textContent='saved — restart to apply log/name changes';reload()}
$('settings').addEventListener('close',()=>$('setMsg').textContent='');
document.querySelector('.gear').addEventListener('click',openSettings);
async function checkVersion(){const v=await fetch('/api/version').then(r=>r.json());
  if(v.update_available)$('updbanner').innerHTML=`<div class=banner>Update available: v${v.latest} (you have v${v.current}). Download from your releases page.</div>`}

reload();loadUnparsed();checkVersion();
</script>"""


def _install_update(db_path: str, app_cb: Optional[dict]) -> dict:
    """POST /api/update/install: verify + download a newer exe, then swap and
    restart AFTER this response has flushed.

    prepare_update does the guarded download (refuses mid-game, refuses when
    not frozen). On success the actual swap is deferred to a background thread
    so the browser gets a clean "installing" reply before the process exits —
    the swap shuts the app down through app_cb['quit'] so the tray icon is
    removed cleanly, not ghosted."""
    import threading
    import time

    from .clients import default_log
    from .track import is_in_game
    from .version import apply_update, prepare_update

    store = Store(db_path)
    try:
        url = store.get_meta("update_url") or None
        log = store.get_meta("log_path") or default_log()
        you = store.get_meta("player") or store.get_meta("you") or None
    finally:
        store.close()

    result = prepare_update(url, log, you, in_game_fn=is_in_game)
    if not result.get("ok"):
        return result

    exit_fn = app_cb.get("quit") if app_cb else None

    def _swap_and_exit() -> None:
        time.sleep(1.0)          # let the HTTP response reach the browser
        try:
            apply_update(exit_fn=exit_fn)
        except Exception:
            pass

    threading.Thread(target=_swap_and_exit, daemon=True).start()
    return {"ok": True, "installing": True, "latest": result.get("latest")}


def _sync_now(store: Store) -> dict:
    """Re-parse the configured log and upsert new games — the viewer's refresh
    button. Uses the exact code path of the live tracker (same session logic,
    content-based keys), so pressing it never conflicts with a running tracker;
    the trailing in-progress game is held back until it resolves, and the
    response says whether one is in progress right now."""
    from .clients import default_log
    from .events import Outcome
    from .parse import parse_log
    from .track import _remember_name, _resolve_session, catchup_backfill

    log = store.get_meta("log_path") or default_log()
    if not log or not os.path.exists(log):
        return {"error": "no Minecraft log found - set one in settings"}
    # Rotated logs first: games played while the app was closed live there,
    # not in latest.log. No-op when nothing new rotated. Opens its own Store
    # connections — fine alongside this request's (WAL + busy_timeout).
    caught_up = catchup_backfill(store.path, log, status_cb=lambda _m: None)
    store._gcache = None
    forced = store.get_meta("player") or None
    result = parse_log(log, you=forced)
    _remember_name(store, result.you)
    size = os.path.getsize(log)
    session_id = _resolve_session(store, log, size)
    n = store.sync(result, session_id)
    store.set_meta(f"size:{log}", str(size))
    in_progress = bool(result.games) and \
        result.games[-1].outcome is Outcome.UNRESOLVED
    return {"synced": n, "games_in_log": len(result.games),
            "in_progress": in_progress, "log": os.path.basename(log),
            "rotated_logs_imported": caught_up}


def _cloud_status(store: Store, refresh: bool) -> dict:
    """Account/license/sync state for the Account page. Offline-first: the
    cached license is the default; ``refresh`` asks the server and falls back
    to the cache on any failure (check_license already degrades)."""
    from .sync import api_for, check_license, license_status

    logged_in = bool(store.get_meta("cloud_token"))
    lic = (check_license(store, api_for(store))
           if refresh and logged_in else license_status(store))
    return {
        "logged_in": logged_in,
        "email": store.get_meta("cloud_email") or "",
        "license": lic,
        "api_base": store.get_meta("cloud_api_base") or "https://api.rivult.net",
        "last_sync": store.get_meta("cloud_last_sync") or None,
        "last_sync_result": store.get_meta("cloud_last_sync_result") or None,
    }


def _cloud_post(store: Store, path: str, body: dict) -> dict:
    """Auth / sync / device actions proxied to the Rivult cloud. Errors come
    back as {error, code} so the UI can branch (offline vs rejected) without
    parsing messages. The browser only ever talks to this local server."""
    from .cloudapi import CloudError
    from .sync import SyncEngine, api_for

    try:
        api = api_for(store)
        if path in ("/api/cloud/login", "/api/cloud/register"):
            email = (body.get("email") or "").strip()
            password = body.get("password") or ""
            if not email or not password:
                return {"error": "email and password required", "code": "INPUT"}
            data = (api.register(email, password)
                    if path.endswith("register") else api.login(email, password))
            store.set_meta("cloud_token", data["token"])
            store.set_meta("cloud_email", email)
            return {"ok": True, "email": email}
        if path == "/api/cloud/delete-account":
            if not store.get_meta("cloud_token"):
                return {"error": "not logged in", "code": "UNAUTHENTICATED"}
            password = body.get("password") or ""
            if not password:
                return {"error": "password required", "code": "INPUT"}
            api.delete_account(password)
            # The account is gone; drop every local trace of it so the app
            # returns to a clean signed-out state. Local GAMES are deliberately
            # untouched — they live in this DB, and losing your history because
            # you deleted a cloud account would be a nasty surprise.
            for k in ("cloud_token", "cloud_email", "cloud_license",
                      "cloud_pull_cursor", "cloud_tag_snapshot",
                      "cloud_seen_server_tags", "cloud_last_sync",
                      "cloud_last_sync_result"):
                store.set_meta(k, "")
            # Sync bookkeeping MUST go too: sync_state records what was already
            # pushed, so leaving it would make a future NEW account sync
            # nothing at all ("already pushed") and look permanently empty.
            # The schema runs first because these tables are created lazily by
            # SyncEngine — someone who signed in but never synced has none.
            from .sync import _SYNC_SCHEMA
            store.conn.executescript(_SYNC_SCHEMA)
            store.conn.execute("DELETE FROM sync_state")
            store.conn.execute("DELETE FROM sync_pending_tags")
            store.conn.commit()
            return {"ok": True, "deleted": True}
        if path == "/api/cloud/logout":
            try:
                api.logout()
            except CloudError:
                pass          # revoking a dead token is fine
            store.set_meta("cloud_token", "")
            return {"ok": True}
        if path == "/api/cloud/sync":
            if not store.get_meta("cloud_token"):
                return {"error": "not logged in", "code": "UNAUTHENTICATED"}
            result = SyncEngine(store, api).run()
            import datetime
            store.set_meta("cloud_last_sync",
                           datetime.datetime.now(datetime.timezone.utc).isoformat())
            store.set_meta("cloud_last_sync_result", json.dumps(result))
            return {"ok": True, **result}
        # Billing (design P2). The Worker mints a Stripe-hosted URL; the app
        # opens it in the system browser. No card data passes through here.
        if path == "/api/cloud/billing/checkout":
            if not store.get_meta("cloud_token"):
                return {"error": "sign in first", "code": "UNAUTHENTICATED"}
            plan = (body.get("plan") or "").strip()
            if plan not in ("monthly", "annual"):
                return {"error": "plan must be monthly or annual", "code": "INPUT"}
            return {"ok": True, **(api.checkout(plan) or {})}
        if path == "/api/cloud/billing/portal":
            if not store.get_meta("cloud_token"):
                return {"error": "sign in first", "code": "UNAUTHENTICATED"}
            return {"ok": True, **(api.portal() or {})}
        m = _DEVICE_REVOKE.match(path)
        if m:
            return {"ok": True, **(api.revoke_device(m.group(1)) or {})}
    except CloudError as e:
        return {"error": str(e), "code": e.code}
    return {"error": "unknown cloud action", "code": "INPUT"}


def _filters(q: dict) -> dict:
    return dict(
        exclude=_split(q.get("exclude")), include=_split(q.get("include")),
        date_from=_one(q.get("from")), date_to=_one(q.get("to")),
        modes=_split(q.get("modes")), teammate=_one(q.get("teammate")))


# -- paywall (design P1) ----------------------------------------------------
#
# MASTER SWITCH. Must stay in lockstep with `PAYWALL_ENABLED` in
# frontend/src/state/DataContext.tsx — flip both, or neither.
#
# Leave this OFF until the Worker is actually deployed. Every license check
# fails while there is no server to ask, which resolves to "not premium", so
# turning it on early would clamp the owner's own dashboard to 90 days and
# lock Breakdowns/Trends with no way to buy a subscription.
PAYWALL_ENABLED = False

FREE_HISTORY_DAYS = 90


def _is_premium(store: Store) -> bool:
    """Cached cloud license == active, honouring the 5-day offline grace.

    Never raises: an unreadable license is treated as "not premium" rather
    than failing the request, and with the paywall off nobody notices.
    """
    try:
        from .sync import license_status
        return (license_status(store) or {}).get("status") == "active"
    except Exception:
        return False


def _free_tier_filters(store: Store, f: dict) -> tuple[dict, bool]:
    """Narrow the window to the free tier's last ``FREE_HISTORY_DAYS``.

    Returns ``(filters, clamped)`` — a NEW dict, never a mutated caller's.
    The frontend has its own gate for UX; this is what makes it real, since
    the client gate is only a rendering choice a determined user can skip.
    """
    if not PAYWALL_ENABLED or _is_premium(store):
        return f, False
    cutoff = (datetime.date.today()
              - datetime.timedelta(days=FREE_HISTORY_DAYS)).isoformat()
    current = f.get("date_from")
    # dates are local ISO strings, compared lexicographically (see
    # ARCHITECTURE §Stat semantics) — a tighter user filter wins
    if current and current >= cutoff:
        return f, False
    return {**f, "date_from": cutoff}, True


def _overlay_test(app_cb: Optional[dict]) -> dict:
    """Show a sample notification so the user can see the overlay's look and
    position without playing a game."""
    notify = (app_cb or {}).get("overlay_test")
    if not callable(notify):
        return {"ok": False,
                "error": "the overlay isn't running — turn it on and restart"}
    try:
        from .keybind import PressResult
        notify(PressResult("added", _PREVIEW_TAG, "current",
                           f"tagged {_PREVIEW_TAG}"))
        return {"ok": True}
    except Exception as e:                      # never 500 over a preview
        return {"ok": False, "error": str(e)}


def _autocmd_test(app_cb: Optional[dict], delay_s: Optional[float]) -> dict:
    """Fire the fixed command pair on demand, after a countdown.

    Auto-commands can otherwise only be observed by starting a real game, which
    makes them nearly impossible to iterate on. This skips the once-per-game
    debounce and nothing else: same fixed pair, and the focus gate still decides
    whether anything is typed, so a test run with the wrong window in front
    types nothing.
    """
    fire = (app_cb or {}).get("autocmd_test")
    if not callable(fire):
        return {"ok": False,
                "error": "the tracker isn't running — auto-commands need it"}
    try:
        from .autocmd import TEST_DELAY_S
        wait = TEST_DELAY_S if delay_s is None else max(0.0, min(60.0, delay_s))
        fire(wait)
        return {"ok": True, "delay_s": wait}
    except Exception as e:                      # never 500 over a test button
        return {"ok": False, "error": str(e)}


# The sample the preview shows. A real registry tag, so the accent dot is the
# colour the user will actually see for it.
_PREVIEW_TAG = "sweats"


def make_handler(db_path: str, app_cb: Optional[dict] = None):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, text):
            body = text.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: str):
            ext = os.path.splitext(path)[1].lower()
            ctype = _CONTENT_TYPES.get(ext, "application/octet-stream")
            with open(path, "rb") as fh:
                body = fh.read()
            try:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                # Vite fingerprints everything under /assets/; the shell must
                # always be revalidated so new builds show up on refresh.
                in_assets = f"{os.sep}assets{os.sep}" in path
                self.send_header(
                    "Cache-Control",
                    "max-age=31536000, immutable" if in_assets else "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass    # browser cancelled the request (tab closed mid-load)

        def do_GET(self):
            u = urlparse(self.path)
            if not u.path.startswith("/api/"):
                built = dist_file(u.path)
                if built:
                    return self._file(built)
            if u.path == "/" or u.path.startswith("/index"):
                return self._html(_PAGE)
            store = Store(db_path)
            try:
                q = parse_qs(u.query)
                f = _filters(q)
                if u.path == "/api/dashboard":
                    scoped, clamped = _free_tier_filters(store, f)
                    payload = store.dashboard(**scoped)
                    if clamped:
                        payload["clamped"] = True
                    return self._json(payload)
                if u.path == "/api/upgrades":
                    return self._json(store.upgrade_stats(**f))
                if u.path == "/api/unparsed":
                    return self._json(store.unparsed())
                if u.path == "/api/search/games":
                    # the Games search box: which games contain a player whose
                    # name matches. Text matching on maps/tags/teammates stays
                    # client-side on the already-loaded list; only the roster
                    # needs the server, because it isn't in the payload.
                    return self._json({"game_ids": store.games_matching_player(
                        _one(q.get("q")) or "")})
                if u.path == "/api/players":
                    # autocomplete for the Games page player filter — any
                    # player from any roster, not just your teammates
                    return self._json(
                        {"players": store.player_search(_one(q.get("q")) or "")})
                m = _PLAYER_GAMES.match(u.path)
                if m:
                    return self._json(
                        {"game_ids": store.games_with_player(m.group(1))})
                if u.path == "/api/settings":
                    return self._json(store.settings())
                if u.path == "/api/cloud/status":
                    refresh = _one(q.get("refresh")) == "1"
                    return self._json(_cloud_status(store, refresh))
                if u.path == "/api/cloud/devices":
                    from .cloudapi import CloudError
                    from .sync import api_for
                    try:
                        return self._json(api_for(store).devices())
                    except CloudError as e:
                        return self._json({"error": str(e), "code": e.code})
                if u.path == "/api/version":
                    url = store.get_meta("update_url") or None
                    return self._json(check_update(url))
                if u.path == "/api/bridging/status":
                    from .inputrec import get_recorder
                    return self._json(get_recorder(db_path).status())
                if u.path == "/api/bridging/sessions":
                    from .inputrec import list_sessions
                    return self._json({"sessions": list_sessions(db_path)})
                m = _BRIDGING_SESSION.match(u.path)
                if m:
                    from .inputrec import session_detail
                    d = session_detail(db_path, int(m.group(1)))
                    return self._json(d) if d else self.send_error(404)
                m = _GAME.match(u.path)
                if m:
                    d = store.game_detail(int(m.group(1)))
                    return self._json(d) if d else self.send_error(404)
            finally:
                store.close()
            self.send_error(404)

        def do_POST(self):
            u = urlparse(self.path)
            # Bound to 127.0.0.1 only (see serve): un-hides the native window
            # when a second launch is redirected here by the single-instance
            # guard. No DB access, no payload — just raises the window.
            if u.path == "/api/app/show":
                if app_cb and callable(app_cb.get("show")):
                    try:
                        app_cb["show"]()
                    except Exception:
                        pass
                    return self._json({"ok": True})
                return self._json({"ok": False, "error": "no window"}, 404)
            if u.path == "/api/update/install":
                return self._json(_install_update(db_path, app_cb))
            # Preview the keybind overlay. The overlay lives on the TRACKER
            # thread, so the server reaches it through app_cb — the same
            # indirection /api/app/show uses for the window. Absent when the
            # server runs without a tracker (the dev config), which the UI
            # reports rather than appearing to do nothing.
            if u.path == "/api/overlay/test":
                return self._json(_overlay_test(app_cb))
            # Same indirection: the AutoCommander lives on the tracker thread.
            if u.path == "/api/autocmd/test":
                q = parse_qs(u.query)
                try:
                    d = float(q["delay"][0]) if q.get("delay") else None
                except (TypeError, ValueError):
                    d = None
                return self._json(_autocmd_test(app_cb, d))
            store = Store(db_path)
            try:
                if u.path == "/api/sync":
                    return self._json(_sync_now(store))
                if u.path == "/api/refresh-all":
                    # Synchronous by design: the server is threaded, WAL keeps
                    # reads flowing, and ~400 archives take about 90 s. The UI
                    # disables the button and says "takes a minute or two".
                    from .clients import default_log
                    from .track import full_refresh
                    log = store.get_meta("log_path") or default_log()
                    if not log:
                        return self._json(
                            {"error": "no Minecraft log found - set one in settings"})
                    result = full_refresh(store.path, log,
                                          status_cb=lambda _m: None)
                    store._gcache = None
                    return self._json(result)
                if u.path == "/api/bridging/start":
                    from .inputrec import get_recorder
                    try:
                        return self._json(get_recorder(db_path).start())
                    except RuntimeError as e:
                        return self._json({"error": str(e)}, 400)
                if u.path == "/api/bridging/stop":
                    from .inputrec import get_recorder
                    return self._json(get_recorder(db_path).stop())
                m = _TAG_SET.match(u.path)
                if m:
                    applied = bool(self._body().get("applied"))
                    return self._json({"applied": store.set_tag(
                        int(m.group(1)), int(m.group(2)), applied)})
                m = _TOGGLE.match(u.path)
                if m:
                    return self._json({"applied": store.toggle_tag(int(m.group(1)), int(m.group(2)))})
                m = _GAME_RESOLVE.match(u.path)
                if m:
                    # Your call on a game the parser couldn't resolve. Stored
                    # against the game's content key, so a full log refresh
                    # keeps it. body: {result: WIN|FINAL_DEATH|null,
                    # hidden: bool} — both absent/false clears the override.
                    b = self._body()
                    try:
                        return self._json(store.set_game_override(
                            int(m.group(1)),
                            result=b.get("result") or None,
                            hidden=bool(b.get("hidden"))))
                    except ValueError as e:
                        return self._json({"error": str(e)}, 400)
                m = _TAG_DELETE.match(u.path)
                if m:
                    store.delete_tag(int(m.group(1)))
                    return self._json({"ok": True})
                m = _TAG_RENAME.match(u.path)
                if m:
                    name = (self._body().get("name") or "")
                    try:
                        stored = store.rename_tag(int(m.group(1)), name)
                        return self._json({"ok": True, "name": stored})
                    except ValueError as e:
                        return self._json({"error": str(e)}, 400)
                m = _TAG_COLOR.match(u.path)
                if m:
                    color = (self._body().get("color") or "")
                    try:
                        store.set_tag_color(int(m.group(1)), color)
                        return self._json({"ok": True})
                    except ValueError as e:
                        return self._json({"error": str(e)}, 400)
                if u.path == "/api/tags":
                    name = (self._body().get("name") or "").strip()
                    try:
                        return self._json({"id": store.create_tag(name), "name": name})
                    except ValueError as e:
                        return self._json({"error": str(e)}, 400)
                if u.path == "/api/settings":
                    b = self._body()
                    for key in ("player", "log_path", "update_url"):
                        if key in b:
                            store.set_meta(key, str(b[key]))
                    if "autocmd_enabled" in b:
                        store.set_meta("autocmd_enabled",
                                       "1" if b["autocmd_enabled"] else "0")
                    if "autocmd_notice_dismissed" in b:
                        store.set_meta(
                            "autocmd_notice_dismissed",
                            "1" if b["autocmd_notice_dismissed"] else "0")
                    if "autocmd_delay_s" in b:
                        try:
                            delay = min(60.0, max(0.5, float(b["autocmd_delay_s"])))
                            store.set_meta("autocmd_delay_s", str(delay))
                        except (TypeError, ValueError):
                            pass
                    if "autocmd_chat_key" in b:
                        # allowlisted ONLY — an arbitrary value here would tap
                        # an arbitrary key into the game
                        from .autocmd import CHAT_KEYS
                        key = str(b["autocmd_chat_key"])
                        if key in CHAT_KEYS:
                            store.set_meta("autocmd_chat_key", key)
                    if "tag_filter" in b:
                        store.set_meta("tag_filter", json.dumps(b["tag_filter"]))
                    if "keybind_map" in b:
                        # a bad binding is the user's typo, not a server error:
                        # reject the whole map with the offending row named
                        from .keybind import BindingError, validate_map
                        try:
                            keymap = validate_map(b["keybind_map"])
                        except BindingError as e:
                            return self._json({"error": str(e)}, 400)
                        store.set_meta("keybind_map", json.dumps(keymap))
                        # The tracker picks the change up on its next tick and
                        # re-registers, overwriting this within a couple of
                        # seconds. Stale status would otherwise describe the
                        # bindings that were just replaced.
                        store.set_meta("keybind_status", json.dumps(
                            {"ok": [], "failed": [], "error": "applying…"}
                            if keymap else {"ok": [], "failed": [], "error": None}))
                    if "keybind_overlay" in b:
                        store.set_meta("keybind_overlay",
                                       "1" if b["keybind_overlay"] else "0")
                    if "overlay_placement" in b:
                        # validated against the known presets rather than
                        # trusted — the tracker would fall back anyway, but
                        # storing junk makes the UI echo junk back
                        from .overlay import PRESETS, normalize_preset
                        preset = normalize_preset(b["overlay_placement"])
                        raw = b["overlay_placement"]
                        asked = (raw.get("preset") if isinstance(raw, dict)
                                 else raw)
                        if asked not in PRESETS:
                            return self._json(
                                {"error": f"unknown overlay position {asked!r}"},
                                400)
                        store.set_meta("overlay_placement",
                                       json.dumps({"preset": preset}))
                    if "tray_enabled" in b:
                        store.set_meta("tray_enabled",
                                       "1" if b["tray_enabled"] else "0")
                    if "trend_window" in b:
                        try:
                            # clamp to the offered choices rather than trusting
                            # the client; an absurd window would just be slow
                            w = int(b["trend_window"])
                            if w in (50, 100, 200, 500):
                                store.set_meta("trend_window", str(w))
                        except (TypeError, ValueError):
                            pass
                    if "trend_focus_tag" in b:
                        # a tag NAME, validated the same way tag names are
                        from .keybind import _TAG_CHARSET
                        name = str(b["trend_focus_tag"]).strip()[:24]
                        if not name or _TAG_CHARSET.fullmatch(name):
                            store.set_meta("trend_focus_tag", name)
                    if "counted_accounts" in b:
                        val = b["counted_accounts"]
                        if not isinstance(val, list):
                            return self._json(
                                {"error": "counted_accounts must be a list"}, 400)
                        store.set_counted_accounts(val)
                    return self._json({"ok": True})
                if u.path.startswith("/api/cloud/"):
                    return self._json(_cloud_post(store, u.path, self._body()))
            finally:
                store.close()
            self.send_error(404)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return {}

        def log_message(self, *a):
            pass

    return Handler


def _split(vals) -> list:
    return [s for s in vals[0].split(",") if s] if vals else []


def _one(vals) -> Optional[str]:
    return vals[0] if vals and vals[0] else None


PORT_SCAN_TRIES = 20


class _Server(ThreadingHTTPServer):
    """ThreadingHTTPServer that refuses to share a port.

    ``http.server`` sets ``allow_reuse_address = 1``. On Windows that flag does
    NOT mean "rebind a TIME_WAIT port" as it does on POSIX — it lets a second
    socket bind a port another process is actively serving. With it on, the
    port scan below always "succeeds" on the busy port and two copies of the
    app fight over requests. Off, a busy port raises and the scan advances.
    """

    allow_reuse_address = False


def bind_server(db_path: str, host: str, port: int,
                app_cb: Optional[dict] = None) -> ThreadingHTTPServer:
    """Bind the first free port at or after ``port``.

    A hardcoded 8770 crashes the app on any machine where something else holds
    that port (another copy of the tracker, an unrelated dev server), which is
    exactly the failure a first-time user cannot diagnose.
    """
    handler = make_handler(db_path, app_cb=app_cb)
    last: Optional[OSError] = None
    for candidate in range(port, port + PORT_SCAN_TRIES):
        try:
            return _Server((host, candidate), handler)
        except OSError as e:
            last = e
    raise OSError(
        f"no free port in {port}-{port + PORT_SCAN_TRIES - 1}: {last}")


def serve(db_path: str, host: str = "127.0.0.1", port: int = 8770,
          ready_cb: Optional[Callable[[int], None]] = None,
          app_cb: Optional[dict] = None) -> None:
    # threaded so a slow /api/version network call can't block the dashboard;
    # each request opens its own short-lived SQLite connection (WAL-safe)
    httpd = bind_server(db_path, host, port, app_cb=app_cb)
    port = httpd.server_address[1]
    if ready_cb:
        ready_cb(port)
    print(f"viewer on http://{host}:{port}  (db: {db_path}, v{__version__})  Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopped")


def main(argv: Optional[list] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="bedwars_parser.server")
    p.add_argument("--db", default="bedwars.db")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8770)
    args = p.parse_args(argv)
    serve(args.db, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
