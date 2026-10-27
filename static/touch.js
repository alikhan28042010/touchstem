/* TouchSTEM living sheet engine.
 * Camera mode: ArUco mat markers -> homography -> coloured fingertip sticker -> plate millimetres.
 * Click mode: pointer on a picture of the sheet (demo for sighted people, no camera).
 * Both feed the same Engine: dwell = name, lift-and-tap = live values, tap again = action / what-if.
 */
(function (global) {
  'use strict';
  const TS = {};

  // ---------------------------------------------------------------- payload
  function b64urlToBytes(s) {
    s = s.replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    const bin = atob(s);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  TS.decode = async function (s) {
    const ds = new DecompressionStream('deflate');
    const stream = new Blob([b64urlToBytes(s)]).stream().pipeThrough(ds);
    const buf = await new Response(stream).arrayBuffer();
    return JSON.parse(new TextDecoder().decode(buf));
  };

  // ---------------------------------------------------------------- speech + tone
  global.__spoken = global.__spoken || [];
  let lang = 'ru-RU';
  TS.setLang = (l) => { lang = l === 'kk' ? 'kk-KZ' : 'ru-RU'; };
  function voice() {
    if (!('speechSynthesis' in global)) return null;
    const vs = speechSynthesis.getVoices();
    return vs.find(v => (v.lang || '').toLowerCase().startsWith(lang.slice(0, 2))) ||
           (lang.startsWith('kk') ? vs.find(v => (v.lang || '').toLowerCase().startsWith('ru')) : null);
  }
  TS.say = function (text) {
    if (!text) return;
    global.__spoken.push(text);
    if (TS.onSay) TS.onSay(text);
    if (!('speechSynthesis' in global) || global.__TS_TEST) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const v = voice();
    if (v) { u.voice = v; u.lang = v.lang; } else u.lang = lang;
    u.rate = 0.95;
    speechSynthesis.speak(u);
  };
  let audio = null, osc = null, gain = null;
  TS.tone = function (freq) {
    if (global.__TS_TEST) { global.__tone = freq; return; }
    try {
      if (!audio) {
        audio = new (global.AudioContext || global.webkitAudioContext)();
        osc = audio.createOscillator(); gain = audio.createGain();
        osc.type = 'sine'; gain.gain.value = 0; osc.connect(gain).connect(audio.destination); osc.start();
      }
      if (freq) { osc.frequency.setTargetAtTime(freq, audio.currentTime, 0.03); gain.gain.setTargetAtTime(0.08, audio.currentTime, 0.03); }
      else gain.gain.setTargetAtTime(0, audio.currentTime, 0.05);
    } catch (e) { /* audio not available */ }
  };

  // ---------------------------------------------------------------- engine
  class Engine {
    constructor(cfg) {
      this.cfg = cfg; this.state = cfg.st || 0;
      this.cur = null; this.level = 0; this.enterT = 0; this.lostAt = 0;
      this.onChange = null;
      if (cfg.k === 'g') {
        const g = cfg.gx;
        this.g = { left: g[0], top: g[1], unit: g[2], x0: g[3], x1: g[4], y0: g[5], y1: g[6], axX: g[7], axY: g[8] };
      }
    }
    // circuit hotspots: nearest centre or braille number within its radius
    hitCircuit(x, y) {
      let best = null, bestD = 1e9;
      this.cfg.hs.forEach((h, i) => {
        const d1 = Math.hypot(x - h[0], y - h[1]);
        const d2 = h[3] != null ? Math.hypot(x - h[3], y - h[4]) : 1e9;
        const d = Math.min(d1, d2 < 7 ? d2 : 1e9);
        const r = d === d1 ? h[2] : 7;
        if (d <= r && d < bestD) { best = i; bestD = d; }
      });
      return best === null ? null : 'h' + best;
    }
    curveY(xv) {
      const c = this.cfg.cv, g = this.g, n = c.length - 1;
      const t = (xv - g.x0) / (g.x1 - g.x0) * n;
      const i = Math.floor(t);
      if (i < 0 || i >= n) return null;
      const a = c[i], b = c[i + 1];
      if (a == null || b == null) return null;
      return a + (b - a) * (t - i);
    }
    hitGraph(x, y) {
      const g = this.g;
      const xv = g.x0 + (x - g.left) / g.unit;
      const X = v => g.left + (v - g.x0) * g.unit, Y = v => g.top + (g.y1 - v) * g.unit;
      if (xv < g.x0 - 0.3 || xv > g.x1 + 0.3) return null;
      const yc = this.curveY(xv);
      if (yc != null && Math.abs(Y(yc) - y) < 5) {
        for (const z of this.cfg.zs) if (Math.abs(X(z) - x) < 4) return 'z' + z;
        for (const m of this.cfg.mn) if (Math.abs(X(m[0]) - x) < 4) return 'n' + m[0];
        for (const m of this.cfg.mx) if (Math.abs(X(m[0]) - x) < 4) return 'x' + m[0];
        const step = (g.x1 - g.x0) <= 8 ? 0.5 : 1;
        return 'c' + (Math.round(xv / step) * step);
      }
      if (Math.abs(x - X(g.axX)) < 3 && Math.abs(y - Y(g.axY)) < 3) return 'o';
      if (Math.abs(y - Y(g.axY)) < 3) return 'ax';
      if (Math.abs(x - X(g.axX)) < 3) return 'ay';
      return null;
    }
    hit(x, y) { return this.cfg.k === 'g' ? this.hitGraph(x, y) : this.hitCircuit(x, y); }

    update(pt, now) {
      now = now === undefined ? performance.now() : now;
      if (!pt) {
        if (this.cur !== null && !this.lostAt) this.lostAt = now;
        if (this.cfg.k === 'g') TS.tone(0);
        return;
      }
      const h = this.hit(pt.x, pt.y);
      if (this.cfg.k === 'g') this.graphTone(pt, h);
      if (h !== this.cur) {
        this.cur = h; this.level = 0; this.enterT = now; this.lostAt = 0;
        if (this.onChange) this.onChange(h, 0);
        return;
      }
      if (h === null) return;
      if (this.lostAt) {
        const gap = now - this.lostAt; this.lostAt = 0;
        if (gap > 120 && gap < 1800 && this.level >= 1) { this.level++; this.speak(h, this.level); }
        return;
      }
      if (this.level === 0 && now - this.enterT > 450) { this.level = 1; this.speak(h, 1); }
    }
    graphTone(pt, h) {
      if (h && (h[0] === 'c' || h[0] === 'z' || h[0] === 'n' || h[0] === 'x')) {
        const g = this.g, yv = this.curveY(g.x0 + (pt.x - g.left) / g.unit);
        if (yv != null) TS.tone(220 + 660 * Math.max(0, Math.min(1, (yv - g.y0) / (g.y1 - g.y0))));
      } else TS.tone(0);
    }
    speak(h, level) {
      if (this.onChange) this.onChange(h, level);
      if (this.cfg.k === 'g') return this.speakGraph(h, level);
      const i = +h.slice(1), hs = this.cfg.hs[i];
      const l2 = hs[6].length ? hs[6][this.state] : '', l3 = hs[7].length ? hs[7][this.state] : '';
      const sw = this.cfg.sw.indexOf(i);
      if (level === 1) return TS.say(hs[5]);
      if (level === 2) return TS.say(l2 || hs[5]);
      if (level === 3 && sw >= 0) return this.toggle(sw);
      if (level === 3 && l3) return TS.say(l3);
      this.level = 1; TS.say(hs[5]);
    }
    toggle(bit) {
      const msg = this.cfg.tg[this.state][bit];
      this.state ^= (1 << bit);
      this.level = 1;
      TS.say(msg);
      if (this.onState) this.onState(this.state);
    }
    speakGraph(h, level) {
      const t = this.cfg.tx, g = this.g;
      const num = v => (Math.abs(v - Math.round(v)) < 1e-6 ? String(Math.round(v)) : v.toFixed(2).replace(/0+$/, '').replace('.', ','));
      const pointText = xv => { const yv = this.curveY(xv); return yv == null ? '' : t.g_point.replace('{x}', num(xv)).replace('{y}', num(Math.round(yv * 100) / 100)); };
      const kind = h[0], val = parseFloat(h.slice(1));
      if (h === 'o') return TS.say(t.g_origin);
      if (h === 'ax') return TS.say(t.g_axis_x);
      if (h === 'ay') return TS.say(t.g_axis_y);
      if (kind === 'z') return TS.say(level === 1 ? t.g_zero : pointText(val));
      if (kind === 'n') return TS.say(level === 1 ? t.g_min : pointText(val));
      if (kind === 'x') return TS.say(level === 1 ? t.g_max : pointText(val));
      if (kind === 'c') return TS.say(pointText(val));
    }
  }
  TS.Engine = Engine;

  // ---------------------------------------------------------------- geometry
  // Homography from >=4 point pairs (image -> mat), least squares via normal equations.
  TS.homography = function (src, dst) {
    const A = [], b = [];
    for (let i = 0; i < src.length; i++) {
      const [x, y] = src[i], [X, Y] = dst[i];
      A.push([x, y, 1, 0, 0, 0, -x * X, -y * X]); b.push(X);
      A.push([0, 0, 0, x, y, 1, -x * Y, -y * Y]); b.push(Y);
    }
    const n = 8, M = Array.from({ length: n }, () => new Array(n + 1).fill(0));
    for (let r = 0; r < A.length; r++)
      for (let i = 0; i < n; i++) {
        for (let j = 0; j < n; j++) M[i][j] += A[r][i] * A[r][j];
        M[i][n] += A[r][i] * b[r];
      }
    for (let c = 0; c < n; c++) {
      let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
      [M[c], M[p]] = [M[p], M[c]];
      if (Math.abs(M[c][c]) < 1e-12) return null;
      for (let r = 0; r < n; r++) if (r !== c) {
        const f = M[r][c] / M[c][c];
        for (let j = c; j <= n; j++) M[r][j] -= f * M[c][j];
      }
    }
    const h = M.map((row, i) => row[n] / row[i]);
    return [...h, 1];
  };
  TS.apply = function (H, x, y) {
    const w = H[6] * x + H[7] * y + H[8];
    return [(H[0] * x + H[1] * y + H[2]) / w, (H[3] * x + H[4] * y + H[5]) / w];
  };
  TS.invert = function (H) {
    const [a, b, c, d, e, f, g, h, i] = H;
    const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
    const det = a * A + b * B + c * C;
    return [A, -(b * i - c * h), b * f - c * e, B, a * i - c * g, -(a * f - c * d), C, -(a * h - b * g), a * e - b * d].map(v => v / det);
  };

  // ---------------------------------------------------------------- colour sticker
  function rgb2hsv(r, g, b) {
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    let h = 0;
    if (d) {
      if (mx === r) h = ((g - b) / d) % 6; else if (mx === g) h = (b - r) / d + 2; else h = (r - g) / d + 4;
      h *= 60; if (h < 0) h += 360;
    }
    return [h, mx ? d / mx : 0, mx / 255];
  }
  TS.PRESETS = { green: [130, 40], pink: [325, 30], orange: [25, 18], blue: [210, 25] };
  TS.findSticker = function (img, hue, tol, step) {
    step = step || 3;
    const { data, width, height } = img;
    let sx = 0, sy = 0, n = 0;
    for (let y = 0; y < height; y += step)
      for (let x = 0; x < width; x += step) {
        const k = (y * width + x) * 4;
        const [h, s, v] = rgb2hsv(data[k], data[k + 1], data[k + 2]);
        let dh = Math.abs(h - hue); if (dh > 180) dh = 360 - dh;
        if (dh <= tol && s > 0.38 && v > 0.32) { sx += x; sy += y; n++; }
      }
    return n >= 4 ? { x: sx / n, y: sy / n, n } : null;
  };
  TS.sampleHue = function (img, x, y) {
    const { data, width } = img;
    let hs = [];
    for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) {
      const k = ((Math.round(y) + dy) * width + Math.round(x) + dx) * 4;
      const hsv = rgb2hsv(data[k], data[k + 1], data[k + 2]);
      if (hsv[1] > 0.3) hs.push(hsv[0]);
    }
    if (!hs.length) return null;
    const sx = hs.reduce((a, h) => a + Math.cos(h * Math.PI / 180), 0), sy = hs.reduce((a, h) => a + Math.sin(h * Math.PI / 180), 0);
    let h = Math.atan2(sy, sx) * 180 / Math.PI; if (h < 0) h += 360;
    return h;
  };

  // ---------------------------------------------------------------- camera tracker
  class Tracker {
    constructor(cfg, video, canvas, engine, ui) {
      this.cfg = cfg; this.video = video; this.canvas = canvas; this.engine = engine; this.ui = ui || {};
      this.ctx = canvas.getContext('2d', { willReadFrequently: true });
      this.detector = new AR.Detector({ dictionaryName: 'ARUCO_4X4_1000' });
      this.H = null; this.frame = 0; this.seen = 0;
      let saved = null; try { saved = JSON.parse(localStorage.getItem('ts_hue') || 'null'); } catch (e) { saved = null; }
      [this.hue, this.tol] = saved || TS.PRESETS.green;
      this.running = false; this.pickNext = false;
      this.marks = {}; cfg.mk.forEach(m => { this.marks[m[0]] = m; });
    }
    matCorners(id) {
      const [, cx, cy, s] = this.marks[id]; const h = s / 2;
      return [[cx - h, cy - h], [cx + h, cy - h], [cx + h, cy + h], [cx - h, cy + h]];
    }
    setHue(h, tol) { this.hue = h; this.tol = tol || 22; try { localStorage.setItem('ts_hue', JSON.stringify([this.hue, this.tol])); } catch (e) { } }
    step() {
      const v = this.video; if (!v.videoWidth) return;
      const W = 640, H = Math.round(v.videoHeight / v.videoWidth * 640);
      if (this.canvas.width !== W) { this.canvas.width = W; this.canvas.height = H; }
      this.ctx.drawImage(v, 0, 0, W, H);
      const img = this.ctx.getImageData(0, 0, W, H);
      if (this.frame % 6 === 0 || !this.H) {
        const ms = this.detector.detect(img).filter(m => this.marks[m.id]);
        if (ms.length >= 2) {
          const src = [], dst = [];
          ms.forEach(m => { const mc = this.matCorners(m.id); m.corners.forEach((c, i) => { src.push([c.x, c.y]); dst.push(mc[i]); }); });
          const Hm = TS.homography(src, dst);
          if (Hm) { this.H = Hm; this.seen = ms.length; }
        } else if (this.frame % 30 === 0) { this.seen = 0; }
        if (this.ui.markers) this.ui.markers(this.seen);
        this.lastMarkers = ms;
      }
      if (this.pickNext) { const h = TS.sampleHue(img, this.pickNext[0], this.pickNext[1]); if (h != null) this.setHue(h, 22); this.pickNext = false; if (this.ui.picked) this.ui.picked(h); }
      const tip = TS.findSticker(img, this.hue, this.tol, 3);
      let plate = null;
      if (tip && this.H) {
        const [mx, my] = TS.apply(this.H, tip.x, tip.y);
        plate = { x: mx - this.cfg.off[0], y: my - this.cfg.off[1] };
      }
      this.engine.update(plate, performance.now());
      global.__lastPlate = plate;
      this.draw(tip, plate);
      this.frame++;
    }
    draw(tip, plate) {
      const c = this.ctx;
      if (this.H) {
        const Hi = TS.invert(this.H), [ox, oy] = this.cfg.off, W = this.cfg.pw, Hh = this.cfg.ph;
        const pts = [[0, 0], [W, 0], [W, Hh], [0, Hh]].map(([x, y]) => TS.apply(Hi, x + ox, y + oy));
        c.strokeStyle = '#2440c8'; c.lineWidth = 2; c.beginPath();
        pts.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y)); c.closePath(); c.stroke();
        if (this.engine.cur && this.engine.cur[0] === 'h') {
          const h = this.cfg.hs[+this.engine.cur.slice(1)];
          const [x, y] = TS.apply(Hi, h[0] + ox, h[1] + oy);
          c.fillStyle = 'rgba(36,64,200,.25)'; c.beginPath(); c.arc(x, y, 18, 0, 7); c.fill();
        }
      }
      if (tip) { c.strokeStyle = '#fff'; c.lineWidth = 3; c.beginPath(); c.arc(tip.x, tip.y, 10, 0, 7); c.stroke(); }
    }
    async start() {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
      this.video.srcObject = stream; await this.video.play();
      this.running = true;
      const loop = () => { if (!this.running) return; try { this.step(); } catch (e) { console.error(e); } requestAnimationFrame(loop); };
      loop();
    }
    stop() { this.running = false; const s = this.video.srcObject; if (s) s.getTracks().forEach(t => t.stop()); TS.tone(0); }
  }
  TS.Tracker = Tracker;

  // ---------------------------------------------------------------- click mode
  TS.bindClicks = function (el, cfg, engine) {
    let down = false;
    const toPlate = (e) => {
      const r = el.getBoundingClientRect();
      return { x: (e.clientX - r.left) / r.width * cfg.pw, y: (e.clientY - r.top) / r.height * cfg.ph };
    };
    let timer = null;
    const tick = () => { if (down && down.pt) engine.update(down.pt, performance.now()); };
    el.addEventListener('pointerdown', e => { e.preventDefault(); el.setPointerCapture(e.pointerId); down = { pt: toPlate(e) }; engine.update(down.pt, performance.now()); timer = setInterval(tick, 60); });
    el.addEventListener('pointermove', e => { if (down) { down.pt = toPlate(e); engine.update(down.pt, performance.now()); } });
    const up = () => { if (!down) return; down = false; clearInterval(timer); engine.update(null, performance.now()); };
    el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
  };

  global.TouchSTEM = TS;
})(window);
