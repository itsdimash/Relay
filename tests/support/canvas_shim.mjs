/** A tiny software Canvas 2D, just enough for the notch room: rects, gradients, polygons, ellipses.
 *  It exists so the room can be run, checked and previewed (PNG or text map) without a browser. */
import { deflateSync } from 'node:zlib';

const clamp = (v, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v));

export function parseColor(input) {
  if (input && typeof input === 'object') return input;
  const s = String(input).trim().toLowerCase();
  if (s === 'transparent') return [0, 0, 0, 0];
  let m = s.match(/^#([0-9a-f]{3})$/);
  if (m) return [...m[1]].map(c => parseInt(c + c, 16)).concat(1);
  m = s.match(/^#([0-9a-f]{6})([0-9a-f]{2})?$/);
  if (m) return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16), parseInt(m[1].slice(4, 6), 16), m[2] ? parseInt(m[2], 16) / 255 : 1];
  m = s.match(/^rgba?\(([^)]+)\)$/);
  if (m) {
    const p = m[1].split(',').map(x => parseFloat(x));
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  }
  throw new Error('shim cannot parse colour: ' + input);
}

function gradient(type, args) {
  const g = { type, args, stops: [], addColorStop(pos, color) { this.stops.push([pos, parseColor(color)]); this.stops.sort((a, b) => a[0] - b[0]); } };
  return g;
}

function colorAt(g, pos) {
  const s = g.stops;
  if (!s.length) return [0, 0, 0, 0];
  if (pos <= s[0][0]) return s[0][1];
  if (pos >= s[s.length - 1][0]) return s[s.length - 1][1];
  for (let i = 1; i < s.length; i++) {
    if (pos <= s[i][0]) {
      const [p0, c0] = s[i - 1];
      const [p1, c1] = s[i];
      const k = p1 === p0 ? 1 : (pos - p0) / (p1 - p0);
      // A transparent stop keeps its neighbour's hue so fades do not turn grey.
      const a = c0[3] === 0 ? [c1[0], c1[1], c1[2], 0] : c0;
      const b = c1[3] === 0 ? [c0[0], c0[1], c0[2], 0] : c1;
      return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k, a[3] + (b[3] - a[3]) * k];
    }
  }
  return s[s.length - 1][1];
}

export function createCanvasShim(width, height) {
  const buf = new Float32Array(width * height * 3);
  const stack = [];
  let path = [];
  let current = null;
  const state = { fillStyle: '#000', strokeStyle: '#000', lineWidth: 1, globalAlpha: 1, globalCompositeOperation: 'source-over' };
  const stats = { fillRect: 0, fill: 0, stroke: 0, gradients: 0 };

  function paintColor(style, x, y) {
    if (style && typeof style === 'object' && style.stops) {
      const a = style.args;
      let pos;
      if (style.type === 'radial') {
        const d = Math.hypot(x - a[0], y - a[1]);
        const r0 = a[2], r1 = a[5];
        pos = r1 === r0 ? 1 : (d - r0) / (r1 - r0);
      } else {
        const dx = a[2] - a[0], dy = a[3] - a[1];
        const len = dx * dx + dy * dy || 1;
        pos = ((x - a[0]) * dx + (y - a[1]) * dy) / len;
      }
      return colorAt(style, clamp(pos));
    }
    return parseColor(style);
  }

  function blend(ix, iy, c) {
    if (ix < 0 || iy < 0 || ix >= width || iy >= height) return;
    const a = clamp(c[3]) * clamp(state.globalAlpha);
    if (a <= 0) return;
    const o = (iy * width + ix) * 3;
    if (state.globalCompositeOperation === 'lighter') {
      for (let k = 0; k < 3; k++) buf[o + k] = Math.min(255, buf[o + k] + c[k] * a);
    } else {
      for (let k = 0; k < 3; k++) buf[o + k] = buf[o + k] * (1 - a) + c[k] * a;
    }
  }

  const ctx = {
    imageSmoothingEnabled: true,
    get fillStyle() { return state.fillStyle; }, set fillStyle(v) { state.fillStyle = v; },
    get strokeStyle() { return state.strokeStyle; }, set strokeStyle(v) { state.strokeStyle = v; },
    get lineWidth() { return state.lineWidth; }, set lineWidth(v) { state.lineWidth = v; },
    get globalAlpha() { return state.globalAlpha; }, set globalAlpha(v) { state.globalAlpha = v; },
    get globalCompositeOperation() { return state.globalCompositeOperation; }, set globalCompositeOperation(v) { state.globalCompositeOperation = v; },
    save() { stack.push({ ...state }); },
    restore() { Object.assign(state, stack.pop() || {}); },
    createLinearGradient(...a) { stats.gradients++; return gradient('linear', a); },
    createRadialGradient(...a) { stats.gradients++; return gradient('radial', a); },
    fillRect(x, y, w, h) {
      stats.fillRect++;
      const x0 = Math.max(0, Math.floor(x)), y0 = Math.max(0, Math.floor(y));
      const x1 = Math.min(width, Math.ceil(x + w)), y1 = Math.min(height, Math.ceil(y + h));
      const solid = !(state.fillStyle && typeof state.fillStyle === 'object');
      const flat = solid ? parseColor(state.fillStyle) : null;
      for (let iy = y0; iy < y1; iy++) for (let ix = x0; ix < x1; ix++) blend(ix, iy, flat || paintColor(state.fillStyle, ix + .5, iy + .5));
    },
    beginPath() { path = []; current = null; },
    moveTo(x, y) { current = [[x, y]]; path.push(current); },
    lineTo(x, y) { if (!current) { current = [[x, y]]; path.push(current); } else current.push([x, y]); },
    closePath() { if (current && current.length) current.push(current[0]); },
    arc(cx, cy, r, a0, a1) { this.ellipse(cx, cy, r, r, 0, a0, a1); },
    ellipse(cx, cy, rx, ry, _rot, a0, a1) {
      const n = 48;
      const pts = [];
      for (let i = 0; i <= n; i++) {
        const a = a0 + (a1 - a0) * i / n;
        pts.push([cx + Math.cos(a) * rx, cy + Math.sin(a) * ry]);
      }
      path.push(pts);
      current = pts;
    },
    fill() {
      stats.fill++;
      for (const poly of path) {
        if (poly.length < 3) continue;
        const ys = poly.map(p => p[1]);
        const y0 = Math.max(0, Math.floor(Math.min(...ys))), y1 = Math.min(height - 1, Math.ceil(Math.max(...ys)));
        for (let iy = y0; iy <= y1; iy++) {
          const yy = iy + .5;
          const xs = [];
          for (let i = 0; i < poly.length - 1 + (poly[0] === poly[poly.length - 1] ? 0 : 1); i++) {
            const a = poly[i], b = poly[(i + 1) % poly.length];
            if ((a[1] <= yy && b[1] > yy) || (b[1] <= yy && a[1] > yy)) xs.push(a[0] + (yy - a[1]) / (b[1] - a[1]) * (b[0] - a[0]));
          }
          xs.sort((p, q) => p - q);
          for (let k = 0; k + 1 < xs.length; k += 2) for (let ix = Math.round(xs[k]); ix < Math.round(xs[k + 1]); ix++) blend(ix, iy, paintColor(state.fillStyle, ix + .5, yy));
        }
      }
    },
    stroke() {
      stats.stroke++;
      const weight = Math.min(1, state.lineWidth);
      for (const poly of path) for (let i = 0; i + 1 < poly.length; i++) {
        const [ax, ay] = poly[i], [bx, by] = poly[i + 1];
        const steps = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) * 2));
        for (let s = 0; s <= steps; s++) {
          const x = ax + (bx - ax) * s / steps, y = ay + (by - ay) * s / steps;
          const c = paintColor(state.strokeStyle, x, y);
          blend(Math.floor(x), Math.floor(y), [c[0], c[1], c[2], c[3] * weight]);
        }
      }
    }
  };
  const canvas = { width, height, getContext: () => ctx, stats };

  function rgb(ix, iy) {
    const o = (iy * width + ix) * 3;
    return [buf[o], buf[o + 1], buf[o + 2]];
  }

  function png(scale = 1) {
    const w = width * scale, h = height * scale;
    const raw = Buffer.alloc((w * 3 + 1) * h);
    for (let y = 0; y < h; y++) {
      raw[y * (w * 3 + 1)] = 0;
      for (let x = 0; x < w; x++) {
        const c = rgb(Math.floor(x / scale), Math.floor(y / scale));
        const o = y * (w * 3 + 1) + 1 + x * 3;
        raw[o] = Math.round(c[0]); raw[o + 1] = Math.round(c[1]); raw[o + 2] = Math.round(c[2]);
      }
    }
    const crcTable = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
    const crc = b => { let c = 0xffffffff; for (const x of b) c = crcTable[(c ^ x) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
    const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const td = Buffer.concat([Buffer.from(type), data]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td)); return Buffer.concat([len, td, c]); };
    const head = Buffer.alloc(13); head.writeUInt32BE(w, 0); head.writeUInt32BE(h, 4); head[8] = 8; head[9] = 2;
    return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', head), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
  }

  /** A text map: lightness ramp for greys, a letter per hue for colours (UPPER bright, lower dark). */
  function ascii(cellW = 2, cellH = 4, region = [0, 0, width, height]) {
    const ramp = ' .:-=+*#%@';
    const rows = [];
    for (let y = region[1]; y < region[3]; y += cellH) {
      let line = '';
      for (let x = region[0]; x < region[2]; x += cellW) {
        let r = 0, g = 0, b = 0, n = 0;
        for (let yy = y; yy < Math.min(height, y + cellH); yy++) for (let xx = x; xx < Math.min(width, x + cellW); xx++) { const c = rgb(xx, yy); r += c[0]; g += c[1]; b += c[2]; n++; }
        r /= n; g /= n; b /= n;
        const max = Math.max(r, g, b), min = Math.min(r, g, b), light = (r + g + b) / 3 / 255;
        const sat = max === 0 ? 0 : (max - min) / max;
        if (sat > 0.32 && max > 70) {
          let hue = 0;
          const d = max - min;
          if (max === r) hue = ((g - b) / d + 6) % 6; else if (max === g) hue = (b - r) / d + 2; else hue = (r - g) / d + 4;
          hue *= 60;
          const letter = hue < 18 || hue >= 340 ? 'r' : hue < 45 ? 'o' : hue < 70 ? 'y' : hue < 160 ? 'g' : hue < 200 ? 'c' : hue < 255 ? 'b' : 'p';
          line += max > 165 ? letter.toUpperCase() : letter;
        } else line += ramp[Math.min(9, Math.floor(light * 10 * 1.6))];
      }
      rows.push(line);
    }
    return rows.join('\n');
  }

  return { canvas, ctx, png, ascii, rgb, stats };
}
