"""The Office canvas, run against a small software canvas: no errors in any scene, and the scenes say what they should."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node is required for the room checks')
class NotchRoomTests(unittest.TestCase):
    def run_node(self, body):
        script = f"""
import {{ renderScene, SCENES }} from '{(ROOT / 'tests/support/render_room.mjs').as_posix()}';
const assert = await import('node:assert/strict');
const count = (shim, [x0, y0, x1, y1], test) => {{ let n = 0; for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) if (test(shim.rgb(x, y))) n++; return n; }};
const purple = c => c[2] > 150 && c[1] > 110 && c[0] > 110;
{body}
"""
        result = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_every_scene_draws_at_every_time_of_day_without_errors(self):
        self.run_node("""
for (const name of Object.keys(SCENES)) for (const hour of [3, 7, 12.5, 18.5, 22]) for (const reducedMotion of [false, true]) for (const pulse of [null, 'retry', 'decision', 'approved', 'start']) {
  const { shim, room } = renderScene(name, { hour, reducedMotion, pulse, frames: 30 });
  assert.ok(shim.stats.fillRect > 200, name + ' drew almost nothing');
  for (const agent of Object.values(room.agents)) assert.ok(Number.isFinite(agent.x) && Number.isFinite(agent.y));
  for (let y = 0; y < 156; y += 13) for (let x = 0; x < 280; x += 11) for (const v of shim.rgb(x, y)) assert.ok(Number.isFinite(v) && v >= 0 && v <= 255.5, 'bad pixel in ' + name);
}
""")

    def test_scenes_show_their_state(self):
        self.run_node("""
// The AUTO sign only exists in Auto mode.
const auto = renderScene('auto').shim, plain = renderScene('builder').shim;
assert.ok(count(auto, [92, 9, 116, 17], purple) > 5, 'no AUTO sign');
assert.equal(count(plain, [92, 9, 116, 17], purple), 0);
// Done: a green sign over the door. Failed: a red one. Needs you: amber, and the Observer has left his desk.
const green = c => c[1] > 140 && c[0] < 140, red = c => c[0] > 200 && c[1] < 130, amber = c => c[0] > 200 && c[1] > 140 && c[2] < 110;
assert.ok(count(renderScene('done').shim, [90, 18, 118, 44], green) > 20);
assert.ok(count(renderScene('failed').shim, [90, 18, 118, 44], red) > 10);
const you = renderScene('you');
assert.ok(count(you.shim, [90, 18, 118, 44], amber) > 20);
assert.ok(you.room.agents.observer.y > 75 && you.room.agents.observer.x > 70, 'the Observer should walk to the door');
// Working agents keep their desk; the idle room is calmer than the working one.
const idle = renderScene('idle'), builder = renderScene('builder');
assert.ok(Math.abs(builder.room.agents.builder.y - 62) < 1);
assert.notEqual(idle.shim.ascii(4, 8), builder.shim.ascii(4, 8));
// Music keeps its level meter on the wall, in the agents' colours.
const music = renderScene('music').shim;
assert.ok(count(music, [123, 12, 145, 30], c => c[2] > 150 || c[0] > 200) > 8, 'no level meter');
// Time of day shows in the window: night is darker than noon.
const lum = shim => count(shim, [14, 12, 62, 24], c => (c[0] + c[1] + c[2]) / 3 > 90);
assert.ok(lum(renderScene('idle', { hour: 12.5 }).shim) > lum(renderScene('idle', { hour: 23 }).shim) + 100);
""")


if __name__ == '__main__':
    unittest.main()
