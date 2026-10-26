/** Writes preview PNGs of the Office (3x) so the artwork can be looked at without launching the app.
 *  Usage: node tests/support/render_preview.mjs [output-folder] */
import { writeFileSync, mkdirSync } from 'node:fs';
import { renderScene, SCENES } from './render_room.mjs';

const folder = process.argv[2] || 'docs/office-preview';
mkdirSync(folder, { recursive: true });
const shots = [
  ['idle-night', 'idle', { hour: 22.5 }], ['idle-day', 'idle', { hour: 12.5 }],
  ['observer-working', 'observer', {}], ['builder-working', 'builder', { hour: 19 }], ['reviewer-working', 'reviewer', {}],
  ['needs-you', 'you', { seconds: 9 }], ['done', 'done', { seconds: 1.4 }], ['failed', 'failed', {}],
  ['auto-mode', 'auto', {}], ['music', 'music', {}]
];
for (const [file, scene, options] of shots) {
  const { shim } = renderScene(scene, { seconds: 6, ...options });
  writeFileSync(`${folder}/${file}.png`, shim.png(3));
}
console.log(`wrote ${shots.length} previews to ${folder}`);
