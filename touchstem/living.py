"""Embeddable click-mode demo of the living sheet (same engine as the phone page)."""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"

UI = {
    "ru": {"hint": "Нажмите и держите элемент — прозвучит название. Отпустите и нажмите снова — значения. "
                   "На ключе нажмите третий раз — ключ переключится, и вы услышите, что изменилось в цепи.",
           "ghint": "Ведите мышью по толстой линии с зажатой кнопкой — высота звука показывает значение функции.",
           "start": "Нажмите на лист, чтобы начать",
           "rhint": "Нажмите и держите любую часть — прозвучит название. Отпустите и нажмите снова — описание, "
                    "в третий раз — что находится рядом.",
           "game": "Игра «Найди»", "go": "Загадать", "rand": "Случайно", "stop": "Стоп",
           "found": "Найдено за {s} с"},
    "kk": {"hint": "Элементті басып ұстаңыз — атауы естіледі. Жіберіп, қайта басыңыз — мәндері. "
                   "Кілтті үшінші рет бассаңыз — кілт ауысады да, тізбекте не өзгергенін естисіз.",
           "ghint": "Тінтуірді батырманы басып тұрып жуан сызықпен жүргізіңіз — дыбыс биіктігі функцияның мәнін көрсетеді.",
           "start": "Бастау үшін парақты басыңыз",
           "rhint": "Кез келген бөлікті басып ұстаңыз — атауы естіледі. Жіберіп, қайта басыңыз — сипаттамасы, "
                    "үшінші рет — жанында не барын естисіз.",
           "game": "«Тап» ойыны", "go": "Тапсырма беру", "rand": "Кездейсоқ", "stop": "Тоқтату",
           "found": "{s} секундта табылды"},
}


def sheet_px(payload: dict) -> int:
    """Small plates (a 1:1 panel overlay) are shown small, not blown up to the column width."""
    return int(min(620, payload.get("pw", 200) * 3.4))


def script_json(obj) -> str:
    """JSON safe to inline in <script> (labels may come from the AI or a pasted JSON)."""
    return (json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def demo_html(payload: dict, sheet_png: bytes, lang: str = "ru") -> str:
    ui = UI[lang]
    js = (STATIC / "touch.js").read_text(encoding="utf-8")
    img = base64.b64encode(sheet_png).decode("ascii")
    kind = payload.get("k")
    hint = ui["ghint"] if kind == "g" else ui["rhint"] if kind == "r" else ui["hint"]
    game = "" if kind == "g" else f"""<div class="game"><b>{html.escape(ui['game'])}</b>
<select id="target" aria-label="{html.escape(ui['game'])}"></select>
<button id="go">{html.escape(ui['go'])}</button><button id="rand">{html.escape(ui['rand'])}</button>
<span class="meter" aria-hidden="true"><i id="heat"></i></span></div>"""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body {{ margin:0; font-family: Plex, "IBM Plex Sans", system-ui, sans-serif; color:#14181d; }}
.sheet {{ position:relative; user-select:none; max-width:{sheet_px(payload)}px; margin:0 auto; }}
.sheet img {{ width:100%; display:block; touch-action:none; cursor:pointer; border-radius:6px;
             box-shadow: 0 1px 0 #c9ccc4, 1px 2px 6px rgba(0,0,0,.08); }}
.sheet canvas {{ position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }}
.say {{ font-size:19px; line-height:1.4; min-height:2.9em; margin:12px 0 6px; padding:12px 14px; border-radius:12px;
        background:#f4f5f2; border:1px solid #d9dcd3; }}
.hint {{ font-size:14px; color:#4a525c; line-height:1.45; }}
.game {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:0 0 10px; font-size:14px; }}
.game select, .game button {{ font:inherit; font-size:14px; padding:7px 12px; border-radius:10px; border:1px solid #c9ccc4;
        background:#fff; color:#14181d; cursor:pointer; }}
.game button#go {{ background:#14181d; color:#fff; border-color:#14181d; }}
.meter {{ flex:1; min-width:80px; height:8px; background:#e6e8e1; border-radius:99px; overflow:hidden; }}
.meter i {{ display:block; height:100%; width:0; background:linear-gradient(90deg,#2440c8,#e5484d); transition:width .2s; }}
</style></head><body>
<div class="sheet"><img id="sheet" alt="" src="data:image/png;base64,{img}" draggable="false"><canvas id="fx"></canvas></div>
<div class="say" id="say" aria-live="polite">{html.escape(ui['start'])}</div>
{game}
<div class="hint">{html.escape(hint)}</div>
<script>{js}</script>
<script>
const cfg = {script_json(payload)};
const TS = window.TouchSTEM;
TS.setLang(cfg.l);
TS.ttsBase = '/app/static/tts/';
TS.onSay = t => {{ document.getElementById('say').textContent = t; }};
const engine = new TS.Engine(cfg);
window.__engine = engine;
TS.bindClicks(document.getElementById('sheet'), cfg, engine);
const sel = document.getElementById('target');
let foundRing = null, t0 = 0;
if (sel) {{
  engine.targets().forEach((t, i) => {{ const o = document.createElement('option'); o.value = i; o.textContent = t[0]; sel.appendChild(o); }});
  const start = i => {{ sel.value = i; engine.find(i); t0 = performance.now(); foundRing = null; document.getElementById('heat').style.width = '0'; }};
  document.getElementById('go').onclick = () => start(+sel.value);
  document.getElementById('rand').onclick = () => start(Math.floor(Math.random() * engine.targets().length));
  engine.onHint = d => {{ document.getElementById('heat').style.width = Math.max(4, 100 - d / Math.max(cfg.pw, cfg.ph) * 160) + '%'; }};
  engine.onFound = t => {{ foundRing = [t[1], t[2], performance.now()]; document.getElementById('heat').style.width = '100%';
    setTimeout(() => {{ document.getElementById('say').textContent += '  ' + {json.dumps(ui['found'])}.replace('{{s}}', ((performance.now() - t0) / 1000).toFixed(1).replace('.', ',')); }}, 50); }};
}}
// visual layer for sighted viewers: glowing lamps and the element under the finger
const fx = document.getElementById('fx'), ctx = fx.getContext('2d');
function draw() {{
  const r = fx.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  if (fx.width !== Math.round(r.width * dpr)) {{ fx.width = Math.round(r.width * dpr); fx.height = Math.round(r.height * dpr); }}
  const k = fx.width / cfg.pw;
  ctx.clearRect(0, 0, fx.width, fx.height);
  if (cfg.k === 'c') cfg.hs.forEach(h => {{
    if (h[8] && h[8].length && h[8][engine.state]) {{
      const g = ctx.createRadialGradient(h[0] * k, h[1] * k, 2 * k, h[0] * k, h[1] * k, 16 * k);
      g.addColorStop(0, 'rgba(255,196,64,.85)'); g.addColorStop(1, 'rgba(255,196,64,0)');
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(h[0] * k, h[1] * k, 16 * k, 0, 7); ctx.fill();
    }}
  }});
  if (cfg.k === 'r' && engine.cur && engine.cur[0] === 'h' && !engine.target) {{
    const p = cfg.hs[+engine.cur.slice(1)][0];
    ctx.beginPath(); ctx.moveTo(p[0] * k, p[1] * k);
    for (let i = 2; i < p.length; i += 2) ctx.lineTo(p[i] * k, p[i + 1] * k);
    ctx.closePath(); ctx.fillStyle = 'rgba(36,64,200,.13)'; ctx.fill();
    ctx.strokeStyle = '#2440c8'; ctx.lineWidth = 2.5 * dpr; ctx.stroke();
  }}
  if (foundRing) {{
    const a = (performance.now() - foundRing[2]) / 900;
    if (a < 1) {{ ctx.strokeStyle = 'rgba(30,127,79,' + (1 - a) + ')'; ctx.lineWidth = 4 * dpr;
      ctx.beginPath(); ctx.arc(foundRing[0] * k, foundRing[1] * k, (6 + 30 * a) * k, 0, 7); ctx.stroke(); }}
  }}
  if (cfg.k !== 'r' && engine.cur && engine.cur[0] === 'h' && !engine.target) {{
    const h = cfg.hs[+engine.cur.slice(1)];
    ctx.strokeStyle = '#2440c8'; ctx.lineWidth = 2 * dpr; ctx.beginPath(); ctx.arc(h[0] * k, h[1] * k, h[2] * k, 0, 7); ctx.stroke();
  }}
  requestAnimationFrame(draw);
}}
draw();
</script></body></html>"""
