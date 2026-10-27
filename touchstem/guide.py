"""Self-contained audio-guide player (HTML + JS) for a student's phone.

Speech uses the browser's built-in voices (Web Speech API); the visible text is in an
aria-live region, so screen readers (TalkBack / VoiceOver) read it too.
"""
from __future__ import annotations

import html
import json

UI = {
    "ru": {"prev": "Назад", "next": "Дальше", "repeat": "Повторить", "all": "Слушать всё", "stop": "Стоп",
           "step": "Шаг {i} из {n}", "novoice": "Голос для этого языка не найден — читаю русским голосом.",
           "hint": "Пробел — повторить, стрелки — назад и дальше."},
    "kk": {"prev": "Артқа", "next": "Әрі қарай", "repeat": "Қайталау", "all": "Барлығын тыңдау", "stop": "Тоқтату",
           "step": "{n} қадамның {i}-і", "novoice": "Қазақ тіліндегі дауыс табылмады — орыс дауысымен оқимын.",
           "hint": "Бос орын — қайталау, көрсеткілер — артқа және әрі қарай."},
}


def guide_html(steps: list[str], lang: str = "ru", title: str = "") -> str:
    ui = UI[lang]
    data = json.dumps({"steps": steps, "ui": ui, "lang": "kk-KZ" if lang == "kk" else "ru-RU"}, ensure_ascii=False)
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {{ --ink:#14181d; --paper:#f4f5f2; --blue:#2440c8; --line:#c9ccc4; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:"IBM Plex Sans","Segoe UI",system-ui,sans-serif; color:var(--ink); background:transparent; }}
  .wrap {{ max-width:640px; margin:0 auto; padding:8px 4px 16px; }}
  .count {{ font-size:15px; color:#5b6470; margin:0 0 10px; }}
  .say {{ font-size:clamp(22px,5.4vw,30px); line-height:1.38; min-height:7.5em; background:var(--paper);
          border:1px solid var(--line); border-radius:18px; padding:22px 22px; margin:0 0 14px; }}
  .row {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
  button {{ font:inherit; font-size:20px; font-weight:600; min-height:64px; border-radius:16px; border:2px solid var(--ink);
            background:#fff; color:var(--ink); cursor:pointer; }}
  button.primary {{ background:var(--ink); color:#fff; }}
  button:focus-visible {{ outline:4px solid var(--blue); outline-offset:3px; }}
  .wide {{ grid-column:1 / -1; }}
  .note {{ font-size:14px; color:#5b6470; margin-top:12px; min-height:1em; }}
</style></head><body><div class="wrap">
<p class="count" id="count"></p>
<div class="say" id="say" aria-live="polite" role="status"></div>
<div class="row">
  <button id="prev">◀ {html.escape(ui['prev'])}</button>
  <button id="next" class="primary">{html.escape(ui['next'])} ▶</button>
  <button id="repeat">🔊 {html.escape(ui['repeat'])}</button>
  <button id="all">{html.escape(ui['all'])}</button>
</div>
<p class="note" id="note">{html.escape(ui['hint'])}</p>
</div>
<script>
const D = {data};
let i = 0, playingAll = false;
const say = document.getElementById('say'), count = document.getElementById('count'), note = document.getElementById('note');
function voice() {{
  const vs = speechSynthesis.getVoices();
  let v = vs.find(v => v.lang && v.lang.toLowerCase().startsWith(D.lang.slice(0,2)));
  if (!v && D.lang.startsWith('kk')) {{ v = vs.find(v => v.lang && v.lang.toLowerCase().startsWith('ru')); if (v) note.textContent = D.ui.novoice; }}
  return v;
}}
function show() {{
  say.textContent = D.steps[i];
  count.textContent = D.ui.step.replace('{{i}}', i + 1).replace('{{n}}', D.steps.length);
}}
function speak(onend) {{
  if (!('speechSynthesis' in window)) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(D.steps[i]);
  const v = voice(); if (v) {{ u.voice = v; u.lang = v.lang; }} else {{ u.lang = D.lang; }}
  u.rate = 0.92;
  if (onend) u.onend = onend;
  speechSynthesis.speak(u);
}}
function go(d) {{ playingAll = false; i = Math.max(0, Math.min(D.steps.length - 1, i + d)); show(); speak(); }}
document.getElementById('prev').onclick = () => go(-1);
document.getElementById('next').onclick = () => go(1);
document.getElementById('repeat').onclick = () => {{ playingAll = false; speak(); }};
const allBtn = document.getElementById('all');
allBtn.onclick = () => {{
  if (playingAll) {{ playingAll = false; speechSynthesis.cancel(); allBtn.textContent = D.ui.all; return; }}
  playingAll = true; allBtn.textContent = D.ui.stop;
  const step = () => {{ show(); speak(() => {{ if (playingAll && i < D.steps.length - 1) {{ i++; step(); }} else {{ playingAll = false; allBtn.textContent = D.ui.all; }} }}); }};
  step();
}};
document.addEventListener('keydown', e => {{
  if (e.key === 'ArrowRight') go(1); else if (e.key === 'ArrowLeft') go(-1);
  else if (e.key === ' ') {{ e.preventDefault(); speak(); }}
}});
if ('speechSynthesis' in window) speechSynthesis.onvoiceschanged = () => {{}};
show();
</script></body></html>"""
