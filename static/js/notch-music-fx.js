/** Music animations for the notch: a few quiet, minimal styles on small canvases (and "Off"), plus the little previews of
 *  the light the app draws around the notch on the screen. Relay cannot hear the music, so the motion is a gentle
 *  performance, not a meter: every track gets its own tempo and phrasing (seeded from its title), the colour comes from
 *  the cover, and everything settles when the music pauses. One shared clock feeds every canvas that is on screen;
 *  nothing runs while the panel is hidden or nothing is playing. With reduced motion each style shows one still frame. */
const TAU = Math.PI * 2;
const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
const lerp = (a, b, k) => a + (b - a) * k;
const fract = v => v - Math.floor(v);

export const STYLES = [
  { id: 'bars', name: 'Bars' },
  { id: 'line', name: 'Line' },
  { id: 'ripple', name: 'Ripple' },
  { id: 'glow', name: 'Glow' },
  { id: 'dots', name: 'Dots' },
  { id: 'off', name: 'Off' }
];
export const DEFAULT_STYLE = 'bars';
export const isStyle = id => STYLES.some(style => style.id === id);

// ---------------------------------------------------------------- randomness

function hashString(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

// A stable number in [0, 1) for an integer and a seed.
function rnd(i, seed = 0) {
  let h = Math.imul(i | 0, 374761393) + Math.imul(seed | 0, 668265263);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}

function noise(x, seed) {
  const i = Math.floor(x);
  const f = x - i;
  return lerp(rnd(i, seed), rnd(i + 1, seed), f * f * (3 - 2 * f));
}

function noise2(x, y, seed) {
  const ix = Math.floor(x);
  const iy = Math.floor(y);
  const fx = x - ix;
  const fy = y - iy;
  const ux = fx * fx * (3 - 2 * fx);
  const uy = fy * fy * (3 - 2 * fy);
  const a = rnd(ix + iy * 57, seed);
  const b = rnd(ix + 1 + iy * 57, seed);
  const c = rnd(ix + (iy + 1) * 57, seed);
  const d = rnd(ix + 1 + (iy + 1) * 57, seed);
  return lerp(lerp(a, b, ux), lerp(c, d, ux), uy);
}

// ------------------------------------------------------------------- colour

export function parseColour(text) {
  const s = String(text || '').trim().toLowerCase();
  let m = s.match(/^rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)/);
  if (m) return [Number(m[1]), Number(m[2]), Number(m[3])];
  m = s.match(/^#([0-9a-f]{6})/);
  if (m) return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16), parseInt(m[1].slice(4, 6), 16)];
  return null;
}

function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const high = Math.max(r, g, b);
  const low = Math.min(r, g, b);
  const l = (high + low) / 2;
  if (high === low) return [0, 0, l];
  const d = high - low;
  const s = l > 0.5 ? d / (2 - high - low) : d / (high + low);
  let h;
  if (high === r) h = (g - b) / d + (g < b ? 6 : 0);
  else if (high === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return [h * 60, s, l];
}

/** Four related colours from the cover's colour: main, a warmer neighbour, a cooler neighbour and a bright highlight.
 *  Each is a function from an alpha to a CSS colour. */
export function makePalette(css) {
  const rgb = parseColour(css) || [79, 181, 148];
  const [h, s0, l0] = rgbToHsl(...rgb);
  const s = clamp(s0, 0.55, 1);
  const l = clamp(l0, 0.58, 0.7);
  const make = (hue, sat, light) => {
    const head = `hsla(${Math.round(((hue % 360) + 360) % 360)}, ${Math.round(sat * 100)}%, ${Math.round(light * 100)}%, `;
    return alpha => `${head}${clamp(alpha).toFixed(3)})`;
  };
  return { hue: h, main: make(h, s, l), a: make(h + 30, s, clamp(l + 0.03, 0, 0.78)), b: make(h - 36, s, l), hi: make(h, clamp(s * 0.7, 0.4, 0.9), 0.9) };
}

// ------------------------------------------------------------------- signal

/** The shared "sound": a tempo, a beat envelope and 32 smoothed bands, all made up but musical in shape
 *  (strong low end, gentle highs, a kick on every beat, a louder one on the bar line). */
function createSignal() {
  const N = 32;
  const s = { N, t: 0, level: 0, bpm: 108, phase: 0, seed: 1, bands: new Float32Array(N), peaks: new Float32Array(N), bass: 0, mid: 0, high: 0, energy: 0, beat: 0, hat: 0, beatPos: 0, dt: 0 };
  s.setTrack = text => {
    const h = hashString(text || 'relay');
    s.seed = h & 0xffff;
    s.bpm = 84 + ((h >>> 8) % 45);
    s.phase = rnd(1, s.seed) * 4;
    s.t = 5 + rnd(2, s.seed) * 200;
  };
  s.update = (dt, playing, snap = false) => {
    s.dt = dt;
    const target = playing ? 1 : 0;
    if (snap) s.level = playing ? 0.62 : 0;
    else {
      s.level += (target - s.level) * (1 - Math.exp(-dt * (playing ? 3.2 : 2.4)));
      if (!playing && s.level < 0.003) s.level = 0;
    }
    s.t += dt * s.level; // time stands still while paused
    const pos = (s.t * s.bpm) / 60 + s.phase;
    const index = Math.floor(pos);
    s.beatPos = pos;
    const accent = index % 4 === 0 ? 1 : 0.5 + 0.4 * rnd(index, s.seed);
    s.beat = Math.exp(-(pos - index) * 4.4) * accent * s.level;
    s.hat = Math.exp(-fract(pos * 2) * 9) * (0.25 + 0.2 * rnd(Math.floor(pos * 2), s.seed + 9)) * s.level;
    let bass = 0, mid = 0, high = 0;
    for (let i = 0; i < N; i++) {
      const x = i / (N - 1);
      const tilt = 1 - 0.55 * Math.pow(x, 0.8);
      const n = noise2(i * 0.55, s.t * (1 + 2.5 * x), s.seed);
      const raw = clamp((tilt * (0.2 + 0.8 * Math.pow(n, 1.25)) + s.beat * Math.pow(1 - x, 2) * 0.6 + s.hat * x * 0.5) * s.level);
      const old = s.bands[i];
      s.bands[i] = snap ? raw : old + (raw - old) * Math.min(1, dt * (raw > old ? 28 : 7));
      s.peaks[i] = Math.max(s.bands[i], s.peaks[i] - dt * 0.5);
      if (i < 6) bass += s.bands[i];
      else if (i < 17) mid += s.bands[i];
      else high += s.bands[i];
    }
    s.bass = bass / 6;
    s.mid = mid / 11;
    s.high = high / (N - 17);
    s.energy = (bass + mid + high) / N;
  };
  return s;
}

const sample = (array, position) => {
  const i = Math.floor(position);
  return lerp(array[Math.min(array.length - 1, Math.max(0, i))], array[Math.min(array.length - 1, i + 1)], position - i);
};

// ----------------------------------------------------------------- drawing

// A rounded rectangle added to the current path (so many can be filled in one go).
function roundedRect(ctx, x, y, w, h, r) {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  if (ctx.roundRect) {
    ctx.roundRect(x, y, w, h, r);
    return;
  }
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function vertical(ctx, y0, y1, stops) {
  const g = ctx.createLinearGradient(0, y0, 0, y1);
  for (const [at, colour] of stops) g.addColorStop(at, colour);
  return g;
}

function glowDot(ctx, x, y, r, colour, halo = 0.12) {
  ctx.fillStyle = colour(halo);
  ctx.beginPath();
  ctx.arc(x, y, r * 3, 0, TAU);
  ctx.fill();
  ctx.fillStyle = colour(0.9);
  ctx.beginPath();
  ctx.arc(x, y, r, 0, TAU);
  ctx.fill();
}

// Every style is restrained on purpose: one colour, thin marks, low contrast, no bloom, so it never competes with
// the title and the controls. `draw` fills the Music view (anchored to the cover when it needs a centre); `mini` is the
// small version beside the title and in the track-change pill.

// --- Bars: slim bars along the bottom edge, mirrored from the middle.
function bars(ctx, v, s, p) {
  const { w, h, u } = v;
  const gap = 8 * u;
  const bar = 2 * u;
  const count = Math.max(6, Math.floor((w + gap) / (bar + gap)));
  const step = (w + gap) / count;
  const base = h - 4 * u;
  const room = h * 0.26;
  ctx.fillStyle = p.main(0.55);
  ctx.beginPath();
  for (let i = 0; i < count; i++) {
    const m = Math.abs(((i + 0.5) / count) * 2 - 1);
    const level = sample(s.bands, Math.pow(m, 0.85) * (s.N - 1) * 0.75);
    const ht = Math.max(bar, Math.min(room, level * room * 1.3));
    roundedRect(ctx, i * step, base - ht, bar, ht, bar / 2);
  }
  ctx.fill();
}

function barsMini(ctx, v, s, p) {
  const { w, h, kind } = v;
  const bands = kind === 'pill' ? [2, 6, 0, 9, 4] : [2, 6, 0, 9];
  const bar = 2.4;
  const gap = 3.2;
  const x0 = (w - (bands.length * bar + (bands.length - 1) * gap)) / 2;
  ctx.fillStyle = p.main(0.9);
  ctx.beginPath();
  bands.forEach((band, i) => {
    const ht = Math.min(h, 3 + clamp(s.bands[band] * 1.4) * (h - 3));
    roundedRect(ctx, x0 + i * (bar + gap), (h - ht) / 2, bar, ht, bar / 2);
  });
  ctx.fill();
}

// --- Line: one thin line that swells with the music and lies flat when it stops.
function line(ctx, v, s, p) {
  const { w, h, u } = v;
  const cy = h * 0.82;
  const amp = h * 0.07 * clamp(s.energy * 1.4 + s.beat * 0.4);
  const step = Math.max(2, w / 140);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.strokeStyle = p.main(0.7);
  ctx.lineWidth = 1.5 * u;
  ctx.beginPath();
  for (let x = 0; x <= w + step; x += step) {
    const nx = Math.min(1, x / w);
    const env = Math.pow(Math.sin(Math.PI * nx), 1.2);
    ctx.lineTo(x, cy + (Math.sin(nx * TAU * 2.2 + s.t * 1.6) * 0.7 + Math.sin(nx * TAU * 3.7 - s.t * 1.1) * 0.3) * amp * env);
  }
  ctx.stroke();
}

function lineMini(ctx, v, s, p) {
  const { w, h } = v;
  const amp = h * (0.1 + 0.3 * clamp(s.energy * 1.4 + s.beat * 0.4)) * s.level;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.strokeStyle = p.main(0.9);
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  for (let x = 0; x <= w + 1.5; x += 1.5) {
    const nx = Math.min(1, x / w);
    ctx.lineTo(x, h / 2 + Math.sin(nx * TAU * 1.6 + s.t * 2.4) * amp * Math.pow(Math.sin(Math.PI * nx), 1.2));
  }
  ctx.stroke();
}

// --- Ripple: two thin rings leave the cover, slowly, and follow its shape.
function ripple(ctx, v, s, p) {
  const { w, h, u, anchor: a } = v;
  const reach = Math.max(40, Math.min(w * 0.4, h * 0.9));
  ctx.lineWidth = u;
  for (let r = 0; r < 2; r++) {
    const age = s.beatPos / 4 - r / 2;
    const ph = age - Math.floor(age);
    const alpha = Math.pow(1 - ph, 2) * Math.min(1, ph * 8) * 0.55 * s.level;
    if (alpha < 0.01) continue;
    const d = 3 + Math.pow(ph, 0.6) * reach;
    ctx.strokeStyle = p.main(alpha);
    ctx.beginPath();
    roundedRect(ctx, a.x - d, a.y - d, a.w + 2 * d, a.h + 2 * d, a.r + d);
    ctx.stroke();
  }
}

function rippleMini(ctx, v, s, p) {
  const { w, h } = v;
  const age = s.beatPos / 2;
  const ph = age - Math.floor(age);
  ctx.strokeStyle = p.main(Math.pow(1 - ph, 1.6) * 0.8 * s.level);
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.arc(w / 2, h / 2, 3 + ph * Math.min(w, h) * 0.5, 0, TAU);
  ctx.stroke();
  ctx.fillStyle = p.main(0.9);
  ctx.beginPath();
  ctx.arc(w / 2, h / 2, 2, 0, TAU);
  ctx.fill();
}

// --- Glow: a single soft light behind the cover that breathes.
function glow(ctx, v, s, p) {
  const { w, h, anchor: a } = v;
  const cx = a.x + a.w / 2;
  const cy = a.y + a.h / 2;
  const radius = Math.max(a.w, a.h) * (1.2 + 0.2 * s.bass + 0.08 * s.beat);
  const g = ctx.createRadialGradient(cx, cy, radius * 0.15, cx, cy, radius * 1.9);
  g.addColorStop(0, p.main(0.3 * (0.3 + 0.7 * s.level) + 0.08 * s.beat));
  g.addColorStop(1, p.main(0));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
}

function glowMini(ctx, v, s, p) {
  const { w, h } = v;
  const reach = h * (0.4 + 0.08 * s.beat + 0.05 * s.level);
  const g = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, reach);
  g.addColorStop(0, p.main(0.55));
  g.addColorStop(1, p.main(0));
  ctx.fillStyle = g;
  ctx.fillRect(w / 2 - reach, 0, reach * 2, h);
  ctx.fillStyle = p.main(0.95);
  ctx.beginPath();
  ctx.arc(w / 2, h / 2, 2.2, 0, TAU);
  ctx.fill();
}

// --- Dots: a sparse row of dots near the bottom that lift with the music.
function dots(ctx, v, s, p) {
  const { w, h, u } = v;
  const count = Math.max(8, Math.floor(w / 22));
  const step = w / count;
  const base = h - 8 * u;
  for (let i = 0; i < count; i++) {
    const m = Math.abs(((i + 0.5) / count) * 2 - 1);
    const level = sample(s.bands, Math.pow(m, 0.85) * (s.N - 1) * 0.75);
    ctx.fillStyle = p.main(0.3 + 0.45 * clamp(level * 1.3));
    ctx.beginPath();
    ctx.arc(step * (i + 0.5), base - clamp(level * 1.3) * h * 0.2, 1.6 * u, 0, TAU);
    ctx.fill();
  }
}

function dotsMini(ctx, v, s, p) {
  const { w, h, kind } = v;
  const count = kind === 'pill' ? 4 : 3;
  const step = 7;
  const x0 = (w - (count - 1) * step) / 2;
  ctx.fillStyle = p.main(0.9);
  for (let i = 0; i < count; i++) {
    ctx.beginPath();
    ctx.arc(x0 + i * step, h / 2 - clamp(s.bands[[1, 5, 2, 8][i]] * 1.4) * h * 0.3, 2, 0, TAU);
    ctx.fill();
  }
}

// --- Previews of the light the app draws around the notch on the screen (Line, Halo, Sparks): a notch outline.
function notchOutline(ctx, w, h) {
  const nw = w * 0.5;
  const x0 = (w - nw) / 2;
  const x1 = x0 + nw;
  const y1 = h * 0.52;
  const r = Math.min(7, h * 0.22);
  ctx.beginPath();
  ctx.moveTo(x0, -2);
  ctx.lineTo(x0, y1 - r);
  ctx.arcTo(x0, y1, x0 + r, y1, r);
  ctx.lineTo(x1 - r, y1);
  ctx.arcTo(x1, y1, x1, y1 - r, r);
  ctx.lineTo(x1, -2);
  return 2 * (y1 + 2 - r) + nw - 2 * r + Math.PI * r; // the length of that line
}

function glowPreview(kind) {
  return (ctx, v, s, p) => {
    const { w, h } = v;
    const breath = 0.5 + 0.5 * Math.sin(s.t * 2.2);
    const length = notchOutline(ctx, w, h);
    ctx.fillStyle = '#000';
    ctx.fill();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    if (kind !== 'line') {
      for (const [width, alpha] of [[13, 0.05], [8, 0.09], [4, 0.16]]) {
        ctx.lineWidth = width;
        ctx.strokeStyle = p.main(alpha * (0.6 + 0.4 * breath));
        ctx.stroke();
      }
    }
    ctx.lineWidth = kind === 'line' ? 1.4 : 1.8;
    ctx.strokeStyle = kind === 'line' ? p.main(0.5 + 0.4 * breath) : p.hi(0.75);
    ctx.stroke();
    if (kind === 'sparks') {
      ctx.lineWidth = 2.4;
      ctx.strokeStyle = p.hi(0.95);
      for (let i = 0; i < 2; i++) {
        ctx.setLineDash([length * 0.16, length * 0.84]);
        ctx.lineDashOffset = -(fract(s.t * 0.45 + i / 2) * length);
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }
  };
}

const IMPL = {
  bars: { draw: bars, mini: barsMini, fade: true },
  line: { draw: line, mini: lineMini, fade: true, edges: true },
  ripple: { draw: ripple, mini: rippleMini },
  glow: { draw: glow, mini: glowMini, soft: true },
  dots: { draw: dots, mini: dotsMini, fade: true },
  'glow-line': { draw: glowPreview('line') },
  'glow-halo': { draw: glowPreview('halo') },
  'glow-sparks': { draw: glowPreview('sparks') }
};

// ------------------------------------------------------------------ engine

/** Surfaces: 'stage' (the whole Music view, behind the controls), 'mini' (next to the title), 'pill' (beside the
 *  notch when a track changes) and 'tile' (a preview in the picker, which always shows its own style). */
export function createMusicFx({ reducedMotion = false, dpr = () => Math.min(2, globalThis.devicePixelRatio || 1), request = callback => requestAnimationFrame(callback), cancel = id => cancelAnimationFrame(id), hidden = () => globalThis.document?.hidden === true } = {}) {
  const signal = createSignal();
  const surfaces = [];
  let style = DEFAULT_STYLE;
  let palette = makePalette();
  let playing = false;
  let scene = { mode: 'compact', view: 'notes' };
  let picker = false;
  let frameId = null;
  let last = 0;
  let tail = 0;

  const styleOf = surface => surface.style || style;
  const isActive = surface => {
    if (!IMPL[styleOf(surface)]) return false;
    if (surface.kind === 'tile') return picker;
    if (surface.kind === 'pill') return scene.mode === 'pill';
    return scene.mode !== 'pill' && scene.view === 'music';
  };

  function measure(surface, impl) {
    const { canvas } = surface;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return false;
    const scale = impl.soft && surface.kind === 'stage' ? 0.5 : 1;
    const pixelsX = Math.max(1, Math.round(width * dpr() * scale));
    const pixelsY = Math.max(1, Math.round(height * dpr() * scale));
    if (canvas.width !== pixelsX || canvas.height !== pixelsY) {
      canvas.width = pixelsX;
      canvas.height = pixelsY;
      surface.state = null;
    }
    surface.w = width;
    surface.h = height;
    return true;
  }

  function drawSurface(surface) {
    const id = styleOf(surface);
    const impl = IMPL[id];
    if (!impl || !measure(surface, impl)) return;
    const { ctx, canvas, w, h, kind } = surface;
    const mini = kind === 'mini' || kind === 'pill';
    ctx.setTransform(canvas.width / w, 0, 0, canvas.height / h, 0, 0);
    if (surface.drawn !== id) {
      surface.drawn = id;
      surface.state = null;
      ctx.globalCompositeOperation = 'source-over';
      ctx.clearRect(0, 0, w, h);
    }
    if (mini || !impl.persist) {
      ctx.globalCompositeOperation = 'source-over';
      ctx.clearRect(0, 0, w, h);
    }
    const view = {
      w, h, kind, surface,
      u: kind === 'tile' ? 0.5 : mini ? 1 : clamp(h / 150, 0.8, 1.4),
      anchor: (surface.anchor && surface.anchor()) || { x: w * 0.12, y: h * 0.18, w: h * 0.64, h: h * 0.64, r: h * 0.1 }
    };
    ctx.save();
    (mini ? impl.mini : impl.draw)(ctx, view, signal, palette);
    ctx.restore();
    if (mini && impl.edges) {
      ctx.globalCompositeOperation = 'destination-in';
      const g = ctx.createLinearGradient(0, 0, w, 0);
      g.addColorStop(0, 'rgba(0, 0, 0, 0)');
      g.addColorStop(0.24, 'rgba(0, 0, 0, 1)');
      g.addColorStop(0.76, 'rgba(0, 0, 0, 1)');
      g.addColorStop(1, 'rgba(0, 0, 0, 0)');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    }
    if (impl.fade && !mini) {
      ctx.globalCompositeOperation = 'destination-in';
      ctx.fillStyle = vertical(ctx, 0, h, [[0, 'rgba(0, 0, 0, 0)'], [0.5, 'rgba(0, 0, 0, 1)'], [1, 'rgba(0, 0, 0, 1)']]);
      ctx.fillRect(0, 0, w, h);
    }
    ctx.globalCompositeOperation = 'source-over';
  }

  const clearSurface = surface => {
    const { canvas, ctx } = surface;
    if (canvas.width && canvas.height) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    surface.drawn = null;
    surface.state = null;
  };

  function drawAll() {
    for (const surface of surfaces) {
      if (isActive(surface)) drawSurface(surface);
      else if (surface.drawn) clearSurface(surface);
    }
  }

  // The picker's previews move even when nothing is playing, so the choices can be compared.
  const alive = () => playing || picker;
  const wantsLoop = () => !reducedMotion && !hidden() && surfaces.some(isActive) && (alive() || signal.level > 0.002 || tail > 0);

  function frame(timestamp) {
    frameId = null;
    const dt = last ? clamp((timestamp - last) / 1000, 0, 0.05) : 1 / 60;
    last = timestamp;
    signal.update(dt, alive());
    tail = signal.level > 0.002 ? 40 : Math.max(0, tail - 1);
    drawAll();
    if (wantsLoop()) frameId = request(frame);
  }

  function refresh() {
    if (reducedMotion) signal.update(0, alive(), true);
    else signal.update(0, alive());
    drawAll();
    if (frameId === null && wantsLoop()) {
      last = 0;
      frameId = request(frame);
    } else if (frameId !== null && !wantsLoop()) {
      cancel(frameId);
      frameId = null;
    }
  }

  return {
    signal,
    attach(canvas, { kind = 'stage', style: own = null, anchor = null } = {}) {
      const surface = { canvas, ctx: canvas.getContext('2d'), kind, style: own, anchor, w: 0, h: 0, state: null, drawn: null };
      surfaces.push(surface);
      return surface;
    },
    setStyle(id) {
      if (!isStyle(id) || id === style) return;
      style = id;
      refresh();
    },
    getStyle: () => style,
    setColour(css) {
      palette = makePalette(css);
      refresh();
    },
    setTrack(text) {
      signal.setTrack(text);
    },
    setPlaying(on) {
      if (on === playing) return;
      playing = on;
      refresh();
    },
    setScene(next) {
      if (next.mode === scene.mode && next.view === scene.view) return;
      scene = { mode: next.mode, view: next.view };
      refresh();
    },
    setPicker(open) {
      if (open === picker) return;
      picker = open;
      refresh();
    },
    refresh,
    /** Advance the clock by hand and draw (tests, and still frames). */
    step(ms) {
      signal.update(ms / 1000, alive());
      drawAll();
    }
  };
}
