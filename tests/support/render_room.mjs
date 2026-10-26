/** Run the notch room against the software canvas. Used by the tests and by the preview script. */
import { createCanvasShim } from './canvas_shim.mjs';
import { createRoom } from '../../static/js/notch-room.js';

export const SCENES = {
  idle: { scene: {} },
  observer: { scene: { actor: 'observer', steps: [{ state: 'current' }, { state: 'todo' }, { state: 'todo' }, { state: 'todo' }, { state: 'todo' }, { state: 'todo' }, { state: 'todo' }] } },
  builder: { scene: { actor: 'builder', steps: [{ state: 'done' }, { state: 'done' }, { state: 'done' }, { state: 'current' }, { state: 'todo' }, { state: 'todo' }, { state: 'todo' }] } },
  reviewer: { scene: { actor: 'reviewer', steps: [{ state: 'done' }, { state: 'done' }, { state: 'done' }, { state: 'done' }, { state: 'current' }, { state: 'todo' }, { state: 'todo' }] } },
  you: { scene: { actor: 'you' } },
  done: { scene: { terminal: 'done' } },
  failed: { scene: { terminal: 'failed' } },
  auto: { scene: { actor: 'builder', auto: true } },
  music: { scene: { actor: 'reviewer' }, music: true }
};

export function renderScene(name, { hour = 22.5, seconds = 6, reducedMotion = false, pulse = null, frames = 120 } = {}) {
  const shim = createCanvasShim(280, 156);
  let clockNow = 1000;
  const room = createRoom(shim.canvas, { reducedMotion, now: () => clockNow, clock: () => ({ getHours: () => Math.floor(hour), getMinutes: () => Math.round((hour % 1) * 60), getSeconds: () => 12 }) });
  const spec = SCENES[name];
  if (!spec) throw new Error('unknown scene ' + name);
  room.setScene({ id: 'run-1', ...spec.scene });
  if (spec.music) room.setMusic(true);
  if (pulse) room.pulse(pulse);
  for (let i = 0; i < frames; i++) {
    clockNow += (seconds * 1000) / frames;
    room.step(clockNow / 1000);
    if (i < frames - 1) continue;
    room.render(clockNow / 1000);
  }
  return { shim, room };
}
