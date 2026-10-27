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
           "start": "Нажмите на лист, чтобы начать"},
    "kk": {"hint": "Элементті басып ұстаңыз — атауы естіледі. Жіберіп, қайта басыңыз — мәндері. "
                   "Кілтті үшінші рет бассаңыз — кілт ауысады да, тізбекте не өзгергенін естисіз.",
           "ghint": "Тінтуірді батырманы басып тұрып жуан сызықпен жүргізіңіз — дыбыс биіктігі функцияның мәнін көрсетеді.",
           "start": "Бастау үшін парақты басыңыз"},
}


def demo_html(payload: dict, sheet_png: bytes, lang: str = "ru") -> str:
    ui = UI[lang]
    js = (STATIC / "touch.js").read_text(encoding="utf-8")
    img = base64.b64encode(sheet_png).decode("ascii")
    hint = ui["ghint"] if payload.get("k") == "g" else ui["hint"]
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body {{ margin:0; font-family: Plex, "IBM Plex Sans", system-ui, sans-serif; color:#14181d; }}
.sheet {{ position:relative; user-select:none; }}
.sheet img {{ width:100%; display:block; touch-action:none; cursor:pointer; border-radius:6px;
             box-shadow: 0 1px 0 #c9ccc4, 1px 2px 6px rgba(0,0,0,.08); }}
.sheet canvas {{ position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }}
.say {{ font-size:19px; line-height:1.4; min-height:2.9em; margin:12px 0 6px; padding:12px 14px; border-radius:12px;
        background:#f4f5f2; border:1px solid #d9dcd3; }}
.hint {{ font-size:14px; color:#4a525c; line-height:1.45; }}
</style></head><body>
<div class="sheet"><img id="sheet" alt="" src="data:image/png;base64,{img}" draggable="false"><canvas id="fx"></canvas></div>
<div class="say" id="say" aria-live="polite">{html.escape(ui['start'])}</div>
<div class="hint">{html.escape(hint)}</div>
<script>{js}</script>
<script>
const cfg = {json.dumps(payload, ensure_ascii=False)};
const TS = window.TouchSTEM;
TS.setLang(cfg.l);
TS.onSay = t => {{ document.getElementById('say').textContent = t; }};
const engine = new TS.Engine(cfg);
window.__engine = engine;
TS.bindClicks(document.getElementById('sheet'), cfg, engine);
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
  if (engine.cur && engine.cur[0] === 'h') {{
    const h = cfg.hs[+engine.cur.slice(1)];
    ctx.strokeStyle = '#2440c8'; ctx.lineWidth = 2 * dpr; ctx.beginPath(); ctx.arc(h[0] * k, h[1] * k, h[2] * k, 0, 7); ctx.stroke();
  }}
  requestAnimationFrame(draw);
}}
draw();
</script></body></html>"""
