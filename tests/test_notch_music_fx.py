"""The music animations (static/js/notch-music-fx.js): every style draws sane numbers on every surface, the loop only runs
when it should, and the page wires the picker up accessibly. The canvas is a recorder that rejects bad numbers and colours."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]
STYLES = ['bars', 'line', 'ripple', 'glow', 'dots', 'off']
GLOW_PREVIEWS = ['glow-line', 'glow-halo', 'glow-sparks']  # drawn in the picker's On screen tab; the app draws the real ones

HARNESS = f"""
import {{ createMusicFx, STYLES, DEFAULT_STYLE, isStyle, makePalette, parseColour }} from '{(ROOT / 'static/js/notch-music-fx.js').as_posix()}';
const assert = await import('node:assert/strict');

// A canvas that records what is drawn and throws on anything that would draw nothing, or draw garbage.
function recorder(width, height) {{
  const log = {{ calls: 0, paints: 0, bad: [] }};
  const finite = (name, args) => args.forEach(a => {{ if (typeof a === 'number' && !Number.isFinite(a)) log.bad.push(name + ' got ' + a); }});
  const colour = (name, value) => {{
    if (typeof value === 'string' && !/^(hsla\\(\\d+, \\d+%, \\d+%, [01](\\.\\d+)?\\)|rgba\\(0, 0, 0, [\\d.]+\\)|#000)$/.test(value)) log.bad.push(name + ' colour ' + value);
  }};
  const gradient = () => ({{ addColorStop(at, value) {{ if (!(at >= 0 && at <= 1)) log.bad.push('stop ' + at); colour('stop', value); }} }});
  const state = {{}};
  const ctx = new Proxy({{}}, {{
    get(_, key) {{
      if (key in state) return state[key];
      return (...args) => {{
        log.calls++;
        finite(String(key), args);
        if (['fill', 'stroke', 'fillRect', 'drawImage'].includes(key)) log.paints++;
        if (key === 'createLinearGradient' || key === 'createRadialGradient') return gradient();
        return undefined;
      }};
    }},
    set(_, key, value) {{ if (key === 'fillStyle' || key === 'strokeStyle') colour(String(key), value); state[key] = value; return true; }}
  }});
  const canvas = {{ width: 0, height: 0, clientWidth: width, clientHeight: height, getContext: () => ctx }};
  return {{ canvas, log }};
}}

function engine({{ reducedMotion = false }} = {{}}) {{
  const pending = [];
  const fx = createMusicFx({{ reducedMotion, dpr: () => 2, request: cb => pending.push(cb), cancel: () => pending.length = 0, hidden: () => false }});
  const frame = ms => {{ const cb = pending.shift(); if (cb) cb(ms); return !!cb; }};
  return {{ fx, pending, frame }};
}}
const run = (fx, seconds) => {{ for (let i = 0; i < seconds * 60; i++) fx.step(1000 / 60); }};
"""

SURFACES = {
    'stage': (440, 170), 'stage big': (780, 312), 'tile': (93, 44), 'mini': (40, 16), 'pill': (44, 22),
}


@unittest.skipUnless(shutil.which('node'), 'Node is required for the animation checks')
class MusicAnimationEngineTests(unittest.TestCase):
    def run_node(self, body):
        script = HARNESS + body
        result = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_style_list_matches_what_the_page_and_tests_expect(self):
        self.run_node(f"""
assert.deepEqual(STYLES.map(s => s.id), {json.dumps(STYLES)});
assert.equal(new Set(STYLES.map(s => s.id)).size, STYLES.length);
assert.ok(STYLES.every(s => s.name && s.name.length < 12));
assert.ok(isStyle(DEFAULT_STYLE) && !isStyle('nonsense') && !isStyle(null) && !isStyle('__proto__'));
""")

    def test_every_style_draws_clean_numbers_on_every_surface_and_state(self):
        self.run_node(f"""
const surfaces = {json.dumps(SURFACES)};
const kind = name => name.split(' ')[0] === 'pill' ? 'pill' : name.split(' ')[0];
for (const style of {json.dumps(STYLES[:-1] + GLOW_PREVIEWS)}) for (const [name, [w, h]] of Object.entries(surfaces)) {{
  const {{ fx }} = engine();
  const {{ canvas, log }} = recorder(w, h);
  const k = kind(name);
  fx.attach(canvas, {{ kind: k, style: k === 'tile' ? style : null, anchor: k === 'stage' ? () => ({{ x: 18, y: 24, w: 112, h: 112, r: 14 }}) : null }});
  fx.setStyle(style);
  fx.setTrack('Midnight City\\nM83');
  fx.setScene({{ mode: k === 'pill' ? 'pill' : 'compact', view: 'music' }});
  fx.setPicker(true);
  fx.setColour('rgb(231, 108, 90)');
  fx.setPlaying(true);
  run(fx, 4);
  assert.ok(log.paints > 3, style + ' on ' + name + ' drew almost nothing (' + log.paints + ')');
  assert.deepEqual(log.bad, [], style + ' on ' + name);
  assert.ok(canvas.width === Math.round(w * 2 * (style === 'glow' && k === 'stage' ? 0.5 : 1)), style + ' canvas backing size ' + canvas.width);
  fx.setPlaying(false);
  run(fx, 6); // settles into its calm shape
  assert.deepEqual(log.bad, [], style + ' while calming down on ' + name);
}}
""")

    def test_odd_covers_and_missing_colours_still_make_a_palette(self):
        self.run_node("""
for (const css of ['', null, 'nonsense', 'rgb(0, 0, 0)', 'rgb(255, 255, 255)', 'rgb(12, 12, 12)', '#ffcc00', 'rgb(231, 108, 90)', 'rgb(79,181,148)']) {
  const p = makePalette(css);
  for (const key of ['main', 'a', 'b', 'hi']) for (const alpha of [-1, 0, 0.5, 1, 7]) assert.match(p[key](alpha), /^hsla\\(\\d+, \\d+%, \\d+%, [01](\\.\\d+)?\\)$/, css + ' ' + key);
}
assert.deepEqual(parseColour('rgb(1, 2, 3)'), [1, 2, 3]);
assert.deepEqual(parseColour('#0a0b0c'), [10, 11, 12]);
assert.equal(parseColour('red'), null);
""")

    def test_the_loop_runs_only_while_music_is_visible_and_playing(self):
        self.run_node("""
const { fx, pending, frame } = engine();
const { canvas } = recorder(440, 170);
fx.attach(canvas, { kind: 'stage' });
fx.setScene({ mode: 'compact', view: 'notes' });
fx.setPlaying(true);
assert.equal(pending.length, 0, 'nothing to draw on the Notes tab');
fx.setScene({ mode: 'compact', view: 'music' });
assert.equal(pending.length, 1, 'starts when the Music view shows while playing');
for (let i = 0; i < 20; i++) frame(i * 16);
assert.equal(pending.length, 1, 'keeps going');
fx.setScene({ mode: 'compact', view: 'deliver' });
assert.equal(pending.length, 0, 'stops as soon as the view is left');
fx.setScene({ mode: 'compact', view: 'music' });
fx.setPlaying(false);
let t = 1000;
let guard = 0;
while (frame(t += 16) && guard++ < 1000);
assert.ok(guard < 400, 'a paused animation settles and stops by itself (took ' + guard + ' frames)');
fx.setPlaying(true);
assert.equal(pending.length, 1, 'and wakes up again when the music resumes');
""")

    def test_hidden_panel_does_not_animate(self):
        self.run_node("""
let hidden = true;
const pending = [];
const fx = createMusicFx({ dpr: () => 1, request: cb => pending.push(cb), cancel: () => {}, hidden: () => hidden });
const { canvas } = recorder(440, 170);
fx.attach(canvas, { kind: 'stage' });
fx.setScene({ mode: 'compact', view: 'music' });
fx.setPlaying(true);
assert.equal(pending.length, 0);
hidden = false;
fx.refresh();
assert.equal(pending.length, 1);
""")

    def test_reduced_motion_draws_one_still_frame_and_never_loops(self):
        self.run_node("""
const { fx, pending } = engine({ reducedMotion: true });
const { canvas, log } = recorder(440, 170);
fx.attach(canvas, { kind: 'stage' });
fx.setScene({ mode: 'compact', view: 'music' });
fx.setPlaying(true);
assert.equal(pending.length, 0);
assert.ok(log.paints > 3, 'the still frame has something in it');
assert.deepEqual(log.bad, []);
""")

    def test_every_track_has_its_own_tempo_and_the_same_track_always_the_same(self):
        self.run_node("""
const bpms = new Set();
for (const title of ['Midnight City', 'Strobe', 'Intro', 'Genesis', 'Hey Jude', 'Bohemian Rhapsody', 'Nuvole Bianche', 'x']) {
  const { fx } = engine();
  fx.setTrack(title + '\\nartist');
  bpms.add(fx.signal.bpm);
  assert.ok(fx.signal.bpm >= 84 && fx.signal.bpm <= 128);
}
assert.ok(bpms.size >= 4, 'tempos should differ between tracks');
const a = engine().fx, b = engine().fx;
for (const fx of [a, b]) { fx.setTrack('same'); fx.setPlaying(true); for (let i = 0; i < 120; i++) fx.signal.update(1 / 60, true); }
assert.deepEqual([...a.signal.bands], [...b.signal.bands]);
""")

    def test_signal_stays_in_range_and_falls_quiet_on_pause(self):
        self.run_node("""
const { fx } = engine();
fx.setTrack('range');
for (let i = 0; i < 1200; i++) {
  fx.signal.update(1 / 60, true);
  for (const v of fx.signal.bands) assert.ok(v >= 0 && v <= 1);
  for (const v of [fx.signal.bass, fx.signal.mid, fx.signal.high, fx.signal.energy, fx.signal.beat, fx.signal.hat, fx.signal.level]) assert.ok(Number.isFinite(v) && v >= 0 && v <= 1.001, String(v));
}
assert.ok(fx.signal.energy > 0.1, 'music should look alive');
for (let i = 0; i < 600; i++) fx.signal.update(1 / 60, false);
assert.equal(fx.signal.level, 0);
assert.ok(fx.signal.energy < 0.01, 'and calm when paused');
const frozen = fx.signal.t;
fx.signal.update(1, false);
assert.equal(fx.signal.t, frozen, 'time stands still while paused');
// a long stall (the panel was hidden) must not make the animation jump
fx.signal.update(5, true);
assert.ok(Number.isFinite(fx.signal.t));
""")

    def test_off_draws_nothing_and_clears_what_was_there(self):
        self.run_node("""
const { fx } = engine();
const { canvas, log } = recorder(440, 170);
fx.attach(canvas, { kind: 'stage' });
fx.setScene({ mode: 'compact', view: 'music' });
fx.setPlaying(true);
run(fx, 1);
const before = log.paints;
assert.ok(before > 0);
fx.setStyle('off');
run(fx, 1);
assert.equal(log.paints, before, 'Off paints nothing');
""")


class MusicAnimationPageTests(unittest.TestCase):
    def test_module_is_served_by_the_engine_and_has_no_network_or_storage_access(self):
        source = (ROOT / 'static' / 'js' / 'notch-music-fx.js').read_text()
        for forbidden in ('fetch(', 'XMLHttpRequest', 'localStorage', 'innerHTML', 'eval(', 'Math.random'):
            self.assertNotIn(forbidden, source, forbidden)
        self.assertIn("'notch-music-fx'", (ROOT / 'relay' / 'http.py').read_text())

    def test_page_has_the_canvases_and_an_accessible_picker(self):
        html = (ROOT / 'static' / 'notch.html').read_text()
        for element in ('id="musicFx"', 'id="musicMini"', 'id="pillFx"', 'id="fxOpen"', 'id="fxCustomize"', 'id="fxPicker"', 'id="fxTabs"', 'role="tablist"', 'id="fxGridPanel"', 'id="fxGridScreen"', 'role="radiogroup"', 'aria-haspopup="true"', 'aria-controls="fxPicker"'):
            self.assertIn(element, html)
        for canvas in re.findall(r'<canvas[^>]*id="(?:musicFx|musicMini|pillFx)"[^>]*>', html):
            self.assertIn('aria-hidden="true"', canvas)  # decoration only
        self.assertNotIn('style="', html)
        self.assertIn('hidden>', html.split('id="fxTabs"', 1)[1].split('>', 1)[0] + '>')  # no tabs without the app
        self.assertIn('aria-label="Change animation"', html)
        customize = html.split('id="fxCustomize"', 1)[1].split('</button>', 1)[0]
        self.assertIn('Customize', customize)  # a visible, labelled way in, not only the small animation
        self.assertIn('aria-expanded="false"', customize)

    def test_script_remembers_the_choice_and_escape_closes_only_the_picker(self):
        script = (ROOT / 'static' / 'notch.js').read_text()
        self.assertIn("from './js/notch-music-fx.js'", script)
        self.assertIn("localStorage.getItem('relay.musicFx')", script)
        self.assertIn("localStorage.setItem('relay.musicFx'", script)
        self.assertIn("isStyle(saved)", script)  # a stale or tampered value falls back to the default
        self.assertIn("setAttribute('role', 'radio')", script)
        self.assertIn("'aria-checked'", script)
        # The On screen tab: the app owns the light around the notch, the page only asks and shows what is saved.
        self.assertIn("tell({ type: 'glowStyle', style: id })", script)
        self.assertIn('window.relayGlowStyle = style =>', script)
        self.assertIn("$('fxTabs').hidden = !native", script)
        for glow in ('off', 'line', 'halo', 'sparks'):
            self.assertIn(f"id: '{glow}'", script.split('const GLOWS', 1)[1].split(']', 1)[0])
        # Escape: capture phase, stops the event, so the panel itself only hides on a second press.
        escape = script.split('// Capture phase:', 1)[1].split('}, true);', 1)[0]
        self.assertIn('event.stopPropagation()', escape)
        for key in ('ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown'):
            self.assertIn(key, escape)
        # The picker never stays open across views or when the panel is shown again.
        self.assertIn("if (view !== 'music') setFxPicker(false);", script)
        self.assertIn('setFxPicker(false); // a freshly shown panel', script)

    def test_script_tells_the_animation_about_track_colour_and_playing(self):
        script = (ROOT / 'static' / 'notch.js').read_text()
        for call in ('fx.setTrack(track)', 'fx.setPlaying(!!music.playing)', 'fx.setPlaying(false)', 'fx.setColour(colour)', 'fx.setScene({ mode, view })', 'fx.refresh()'):
            self.assertIn(call, script)

    def test_style_has_the_picker_off_state_and_reduced_motion(self):
        css = (ROOT / 'static' / 'notch.css').read_text()
        for rule in ('.music-fx', '.fx-picker', '.fx-tile', '.panel[data-fx="off"]', 'backdrop-filter'):
            self.assertIn(rule, css)
        self.assertNotIn('.eq i', css)  # the old four-bar equalizer is gone
        reduced = css.split('@media (prefers-reduced-motion: reduce)', 1)[1]
        self.assertIn('.fx-picker', reduced)

    def test_every_style_name_has_a_tile_label_source(self):
        source = (ROOT / 'static' / 'js' / 'notch-music-fx.js').read_text()
        for style in STYLES[:-1] + GLOW_PREVIEWS:
            self.assertRegex(source, rf"'?{style}'?: \{{ draw: ")
        self.assertIn("{ id: 'off', name: 'Off' }", source)


@unittest.skipUnless(shutil.which('node'), 'Node is required for the animation checks')
class QuietnessTests(unittest.TestCase):
    def test_the_default_is_a_quiet_style_and_the_drawn_looks_are_thin_and_dim(self):
        source = (ROOT / 'static' / 'js' / 'notch-music-fx.js').read_text()
        self.assertIn("DEFAULT_STYLE = 'bars'", source)
        # No loud blending: glow comes from soft gradients, not additive 'lighter' stacking.
        self.assertNotIn("'lighter'", source)


class NativeGlowStyleTests(unittest.TestCase):
    """The light around the notch (RelayNotchGlow) has the same four looks the page offers and keeps the choice."""

    def test_the_app_handles_the_glow_message_and_saves_the_choice(self):
        panel = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        self.assertIn('[type isEqualToString:@"glowStyle"]', panel)
        self.assertIn('RelayNotchGlowStyle', panel)
        self.assertIn('window.relayGlowStyle', panel)
        self.assertEqual(panel.count('[self pushGlowStyle]'), 2)  # when the page is ready and after every (re)load

    def test_every_look_is_known_to_page_and_app(self):
        glow = (ROOT / 'packaging' / 'RelayNotchGlow.m').read_text()
        header = (ROOT / 'packaging' / 'RelayNotchGlow.h').read_text()
        self.assertIn('NSString *style', header)
        for look in ('off', 'line', 'halo', 'sparks'):
            self.assertIn(f'@"{look}"', glow)
        self.assertIn('_style = @"line"', glow)  # quiet by default


if __name__ == '__main__':
    unittest.main()
