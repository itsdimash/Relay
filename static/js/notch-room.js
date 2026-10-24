/** Pixel-art room for the notch panel. Original artwork drawn with rectangles on a 180 x 100 canvas.
 *  Observer, Builder and Reviewer sit at their desks and pass a glowing baton. When Relay needs you,
 *  the Observer walks the baton to the gate and its lamp turns amber. */
const W = 180;
const H = 100;
const ROLES = ['observer', 'builder', 'reviewer'];
const HOME = { observer: 35, builder: 117, reviewer: 161 };
const DESK_X = { observer: 9, builder: 91, reviewer: 135 };
const GATE_X = 66;
const SEAT_Y = 41;
const WALK_Y = 53;
const COLORS = {
  observer: { body: '#2a7f92', glow: '#4db6c9', hair: '#2b1d14' },
  builder: { body: '#c4781f', glow: '#f0a63f', hair: '#4a2f1a' },
  reviewer: { body: '#6a58c9', glow: '#a18bf0', hair: '#1c1c2a' }
};
const SKIN = '#f1c9a5';
const Z = ['111', '001', '010', '100', '111'];
const CHECK = ['0001', '0010', '1100', '0100'];
const NOTE = ['0011', '0010', '0010', '1110', '1110'];

function hash(n) {
  const x = Math.sin(n * 127.1) * 43758.5453;
  return x - Math.floor(x);
}

export function createRoom(canvas, { reducedMotion = false, now = () => performance.now() } = {}) {
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = false;
  const agents = Object.fromEntries(ROLES.map(role => [role, { x: HOME[role], y: SEAT_Y }]));
  const baton = { x: HOME.observer + 5, y: 56, trail: [] };
  const particles = [];
  let scene = { actor: null, terminal: null };
  let music = false;
  let previousTerminal = null;
  let holder = 'observer';
  let timer = null;
  let last = 0;

  const rect = (x, y, w, h, color) => {
    ctx.fillStyle = color;
    ctx.fillRect(Math.round(x), Math.round(y), w, h);
  };
  const glyph = (rows, x, y, color) => {
    rows.forEach((row, j) => [...row].forEach((bit, i) => bit === '1' && rect(x + i, y + j, 1, 1, color)));
  };

  function setScene(next) {
    scene = { actor: next.actor || null, terminal: next.terminal || null };
    if (ROLES.includes(scene.actor)) holder = scene.actor;
    else if (scene.actor === 'you') holder = 'observer';
    if (scene.terminal === 'done' && previousTerminal !== 'done' && !reducedMotion) confetti();
    previousTerminal = scene.terminal;
    if (reducedMotion) {
      for (let i = 0; i < 60; i++) step(i / 10);
      render(0);
    }
  }

  // Music playing: the agents wear headphones, nod along, and little notes float up in their colours.
  function setMusic(playing) {
    music = !!playing;
    if (reducedMotion) render(0);
  }

  function confetti() {
    for (let i = 0; i < 26; i++) {
      const color = ['#4fb594', '#f0a63f', '#a18bf0', '#4db6c9', '#fff6c2'][i % 5];
      particles.push({ x: GATE_X, y: 36, vx: (hash(i) - 0.5) * 2.6, vy: -1 - hash(i + 40) * 1.8, life: 1, decay: 0.012, color, gravity: 0.06 });
    }
  }

  function spawn(role, t) {
    if (reducedMotion) return;
    const a = agents[role];
    const c = COLORS[role].glow;
    if (hash(t * 7 + role.length) > 0.82) {
      particles.push({ x: DESK_X[role] + 9 + hash(t) * 6, y: 44, vx: (hash(t + 3) - 0.5) * 0.3, vy: -0.35 - hash(t + 9) * 0.3, life: 1, decay: 0.03, color: c, gravity: 0 });
    }
    if (role === 'reviewer' && hash(t * 3 + 1) > 0.95) {
      particles.push({ x: a.x - 2, y: a.y - 4, vx: 0, vy: -0.25, life: 1, decay: 0.02, color: '#7dd9a8', gravity: 0, check: true });
    }
  }

  function step(t) {
    // Agents walk to their target; only the Observer ever leaves the desk.
    const away = scene.actor === 'you';
    for (const role of ROLES) {
      const a = agents[role];
      const targetX = role === 'observer' && away ? GATE_X - 13 : HOME[role];
      const targetY = role === 'observer' && away ? WALK_Y : SEAT_Y;
      a.x += Math.max(-0.9, Math.min(0.9, targetX - a.x));
      a.y += Math.max(-0.7, Math.min(0.7, targetY - a.y));
      a.moving = Math.abs(targetX - a.x) > 0.5 || Math.abs(targetY - a.y) > 0.5;
    }
    // Baton eases to the holder's hand, or rests above the gate when the task is finished.
    const h = agents[holder];
    const tx = scene.terminal === 'done' ? GATE_X : h.x + 5;
    const ty = scene.terminal === 'done' ? 29 : h.y + 15;
    const distance = Math.abs(tx - baton.x);
    baton.x += (tx - baton.x) * 0.14;
    baton.y += (ty - baton.y) * 0.14 - Math.min(2.2, distance * 0.06);
    baton.trail.push([baton.x, baton.y]);
    if (baton.trail.length > 7) baton.trail.shift();
    for (const role of ROLES) if (scene.actor === role) spawn(role, t);
    if (music && !reducedMotion && hash(t * 5 + 1) > 0.93) {
      const role = ROLES[Math.floor(hash(t * 11) * 3)];
      const a = agents[role];
      particles.push({ x: a.x + 3, y: a.y - 3, vx: 0, vy: -0.5 - hash(t + 4) * 0.3, life: 1, decay: 0.017, color: COLORS[role].glow, gravity: 0, note: true, sway: hash(t * 3) * 6.28 });
    }
    for (const p of particles) {
      p.x += p.vx + (p.note ? Math.sin(p.life * 9 + p.sway) * 0.3 : 0);
      p.y += p.vy;
      p.vy += p.gravity || 0;
      p.life -= p.decay;
    }
    for (let i = particles.length - 1; i >= 0; i--) if (particles[i].life <= 0) particles.splice(i, 1);
  }

  function drawBackground(t) {
    rect(0, 0, W, 34, '#111822');
    rect(0, 34, W, 2, '#1a2330');
    rect(0, 36, W, H - 36, '#0c1117');
    for (let x = 0; x < W; x += 20) rect(x, 36, 1, H - 36, '#10161e');
    for (let y = 52; y < H; y += 16) rect(0, y, W, 1, '#10161e');
    for (const x of [14, 100]) {
      rect(x, 6, 34, 20, '#0a1019');
      rect(x + 1, 7, 15, 18, '#142033');
      rect(x + 18, 7, 15, 18, '#142033');
    }
    rect(70, 8, 22, 12, '#0f1620');
    rect(72, 10, 18, 2, '#1d2a3b');
    rect(72, 14, 12, 2, '#1d2a3b');
    rect(150, 8, 20, 18, '#0f1620');
    rect(152, 10, 16, 2, '#1d2a3b');
    rect(152, 14, 16, 2, '#1d2a3b');
    rect(152, 18, 16, 2, '#1d2a3b');
    if (music) {
      // The picture on the wall becomes a level meter.
      rect(72, 10, 18, 8, '#0a1019');
      const tick = reducedMotion ? 0 : Math.floor(t * 8);
      for (let i = 0; i < 5; i++) {
        const level = 1 + Math.floor((reducedMotion ? 0.6 : hash(tick * 5 + i)) * 6);
        rect(73 + i * 3.4, 18 - level, 2, level, COLORS[ROLES[i % 3]].glow);
      }
    }
    if (music) {
      // A slow colour wash over the floor, in the three agents' colours in turn.
      const wash = COLORS[ROLES[Math.floor(t / 1.6) % 3]].glow;
      ctx.globalAlpha = reducedMotion ? 0.05 : 0.04 + 0.04 * Math.sin(t * 6.5);
      rect(0, 36, W, H - 36, wash);
      ctx.globalAlpha = 1;
    }
  }

  function drawMonitor(role, working, t) {
    const x = DESK_X[role] + 3;
    const y = 46;
    const c = COLORS[role].glow;
    rect(x - 1, y - 1, 14, 11, '#2b3340');
    rect(x, y, 12, 9, working ? '#0a1016' : '#0b0f15');
    if (working) {
      ctx.globalAlpha = 0.16;
      rect(x - 4, y + 10, 20, 7, c);
      ctx.globalAlpha = 1;
      const tick = reducedMotion ? 0 : Math.floor(t * 5);
      for (let row = 0; row < 4; row++) rect(x + 1, y + 1 + row * 2, 2 + Math.floor(hash(tick + row * 3 + role.length) * 8), 1, c);
    } else {
      rect(x + 5, y + 4, 2, 1, '#26303d');
    }
    rect(x + 4, y + 10, 4, 2, '#2b3340');
  }

  function drawDesk(role) {
    const x = DESK_X[role];
    rect(x, 56, 34, 3, '#4a3b2e');
    rect(x, 59, 34, 8, '#2e241b');
    rect(x + 1, 67, 3, 5, '#241b14');
    rect(x + 30, 67, 3, 5, '#241b14');
  }

  function drawAgent(role, t) {
    const a = agents[role];
    const c = COLORS[role];
    const x = Math.round(a.x);
    const y = Math.round(a.y);
    const working = scene.actor === role;
    const phase = ROLES.indexOf(role) * 1.3;
    let bob = 0;
    if (!reducedMotion) {
      if (working) bob = Math.round(Math.sin(t * 9) * 0.6 + 0.4);
      else if (music) bob = Math.round(Math.sin(t * 6.5 + phase) * 0.5 + 0.5); // nodding to the beat
    }
    if (working && !reducedMotion) {
      // A halo in the agent's colour, so it is clear who has the baton.
      ctx.globalAlpha = 0.14 + 0.08 * Math.sin(t * 4);
      rect(x - 8, y - 3, 16, 24, c.glow);
      ctx.globalAlpha = 1;
    }
    const blink = !reducedMotion && Math.floor(t * 2.2) % 9 === 0;
    // body
    rect(x - 4, y + 6 + bob, 8, 9, c.body);
    rect(x - 4, y + 6 + bob, 8, 1, 'rgba(255,255,255,0.16)');
    // head
    rect(x - 3, y + bob, 6, 6, SKIN);
    rect(x - 3, y + bob, 6, 2, c.hair);
    if (role === 'builder') {
      rect(x - 4, y - 1 + bob, 8, 3, '#f5c542');
      rect(x - 2, y - 2 + bob, 4, 1, '#f5c542');
    }
    if (!blink) {
      rect(x - 2, y + 3 + bob, 1, 1, '#1a1a22');
      rect(x + 1, y + 3 + bob, 1, 1, '#1a1a22');
    }
    if (role === 'observer') {
      rect(x - 3, y + 2 + bob, 3, 3, 'rgba(191,231,239,0.35)');
      rect(x, y + 2 + bob, 3, 3, 'rgba(191,231,239,0.35)');
    }
    if (role === 'reviewer') rect(x + 4, y + 8 + bob, 3, 5, '#e8e0c8');
    if (music) {
      // Headphones: a band over the head and a glowing cup on each ear.
      if (role !== 'builder') rect(x - 3, y - 1 + bob, 6, 1, '#2b3340');
      rect(x - 4, y + 1 + bob, 1, 4, '#2b3340');
      rect(x + 3, y + 1 + bob, 1, 4, '#2b3340');
      ctx.globalAlpha = reducedMotion ? 0.8 : 0.55 + 0.45 * Math.sin(t * 6.5 + phase);
      rect(x - 5, y + 2 + bob, 1, 2, c.glow);
      rect(x + 4, y + 2 + bob, 1, 2, c.glow);
      ctx.globalAlpha = 1;
    }
    // arms: forward while typing, down otherwise
    const armY = working ? y + 9 + bob + (Math.floor(t * 8) % 2) : y + 8;
    rect(x - 6, armY, 2, 4, c.body);
    rect(x + 4, working ? armY - ((Math.floor(t * 8) + 1) % 2) : y + 8, 2, 4, c.body);
    // legs only show while walking
    if (a.moving || a.y > SEAT_Y + 2) {
      const phase = Math.floor(t * 8) % 2;
      rect(x - 3, y + 15, 3, 6 - phase, '#1b2230');
      rect(x, y + 15, 3, 5 + phase, '#1b2230');
    }
  }

  function drawGate(t) {
    rect(GATE_X - 9, 38, 3, 36, '#26303d');
    rect(GATE_X + 6, 38, 3, 36, '#26303d');
    rect(GATE_X - 9, 36, 18, 3, '#303b4a');
    let lamp = '#303a47';
    let glow = null;
    const pulse = reducedMotion ? 1 : 0.55 + 0.45 * Math.sin(t * 5);
    if (scene.actor === 'you') {
      lamp = '#f2b24c';
      glow = ['#f2b24c', pulse * 0.45];
    } else if (scene.terminal === 'done') {
      lamp = '#4fb594';
      glow = ['#4fb594', 0.4];
    } else if (scene.terminal === 'failed') {
      lamp = '#ef6b6b';
      glow = ['#ef6b6b', 0.4];
    } else if (scene.actor === 'relay') {
      lamp = pulse > 0.8 ? '#f2b24c' : '#4a4030';
    }
    if (glow) {
      ctx.globalAlpha = glow[1];
      rect(GATE_X - 12, 30, 24, 14, glow[0]);
      ctx.globalAlpha = 1;
    }
    // The lamp only exists while it means something; an unlit one looked like a stray mark above the door.
    if (glow || scene.actor === 'relay') rect(GATE_X - 2, 31, 4, 4, lamp);
    rect(GATE_X - 6, 44, 12, 30, scene.actor === 'you' ? '#1f1a10' : '#0e131a');
    rect(GATE_X + 2, 58, 2, 2, scene.actor === 'you' ? '#f2b24c' : '#2b3340');
  }

  function drawBaton() {
    for (let i = 0; i < baton.trail.length; i++) {
      ctx.globalAlpha = (i / baton.trail.length) * 0.35;
      rect(baton.trail[i][0], baton.trail[i][1], 2, 6, '#fff6c2');
    }
    ctx.globalAlpha = 0.25;
    rect(baton.x - 2, baton.y - 2, 6, 10, '#ffe38a');
    ctx.globalAlpha = 1;
    rect(baton.x, baton.y, 2, 6, '#fff6c2');
    rect(baton.x, baton.y, 2, 1, '#ffd45e');
  }

  function drawParticles() {
    for (const p of particles) {
      ctx.globalAlpha = Math.max(0, Math.min(1, p.life));
      if (p.check) glyph(CHECK, Math.round(p.x), Math.round(p.y), p.color);
      else if (p.note) glyph(NOTE, Math.round(p.x), Math.round(p.y), p.color);
      else rect(p.x, p.y, 2, 2, p.color);
    }
    ctx.globalAlpha = 1;
  }

  function render(t) {
    drawBackground(t);
    const seated = role => !agents[role].moving && Math.abs(agents[role].y - SEAT_Y) < 1;
    for (const role of ROLES) if (seated(role)) drawAgent(role, t);
    for (const role of ROLES) {
      drawMonitor(role, scene.actor === role, t);
    }
    for (const role of ROLES) drawDesk(role);
    drawGate(t);
    for (const role of ROLES) if (!seated(role)) drawAgent(role, t);
    if (!scene.actor && !scene.terminal && !reducedMotion) {
      const phase = (t * 0.8) % 3;
      if (phase < 2) glyph(Z, 38 + Math.round(phase * 2), 34 - Math.round(phase * 3), '#566274');
    }
    drawBaton();
    drawParticles();
  }

  function loop(timestamp) {
    timer = requestAnimationFrame(loop);
    if (timestamp - last < 33) return;
    last = timestamp;
    const t = now() / 1000;
    step(t);
    render(t);
  }

  function start() {
    if (reducedMotion) {
      for (let i = 0; i < 60; i++) step(i / 10);
      render(0);
      return;
    }
    if (timer === null) timer = requestAnimationFrame(loop);
  }
  function stop() {
    if (timer !== null) cancelAnimationFrame(timer);
    timer = null;
  }

  return { setScene, setMusic, start, stop, step, render, agents };
}
