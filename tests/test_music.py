from pathlib import Path
import re
import unittest

ROOT = Path(__file__).parents[1]
ADAPTER = ROOT / 'third_party' / 'mediaremote-adapter'


class VendoredAdapterTests(unittest.TestCase):
    def test_licence_and_source_are_shipped_with_the_code(self):
        self.assertIn('BSD 3-Clause', (ADAPTER / 'LICENSE').read_text())
        source = (ADAPTER / 'SOURCE.txt').read_text()
        self.assertIn('v0.7.7', source)
        self.assertRegex(source, r'Commit:\s+[0-9a-f]{40}')

    def test_build_script_compiles_signs_and_bundles_it(self):
        script = (ROOT / 'scripts' / 'build_macos_app.sh').read_text()
        for needle in ('third_party/mediaremote-adapter', 'MediaRemoteAdapter.framework', 'mediaremote-adapter.pl',
                       'MediaRemoteAdapter-LICENSE.txt', 'packaging/RelayNowPlaying.m', 'packaging/RelayNotchGlow.m'):
            self.assertIn(needle, script)
        # Every step of the adapter build must be able to fail without stopping the whole app build.
        body = script.split('build_now_playing_adapter() {', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('return 1', body)
        self.assertIn('if ! build_now_playing_adapter', script)

    def test_every_adapter_source_the_build_globs_exists(self):
        for folder in ('adapter', 'private', 'utility'):
            self.assertTrue(list((ADAPTER / 'src' / folder).glob('*.m')), folder)
        self.assertTrue((ADAPTER / 'bin' / 'mediaremote-adapter.pl').is_file())
        self.assertTrue((ADAPTER / 'include' / 'MediaRemoteAdapter.h').is_file())


    def test_every_quoted_import_in_the_adapter_resolves(self):
        # The build compiles with -I include -I src, so an import must be next to the file or under one of those.
        roots = [ADAPTER / 'include', ADAPTER / 'src']
        missing = []
        for source in (ADAPTER / 'src').rglob('*'):
            if source.suffix not in ('.m', '.h'):
                continue
            for name in re.findall(r'^#(?:import|include)\s+"([^"]+)"', source.read_text(), re.M):
                if not any((base / name).is_file() for base in [source.parent, *roots]):
                    missing.append(f'{source.relative_to(ADAPTER)} -> {name}')
        self.assertEqual(missing, [])


class CommandCodeTests(unittest.TestCase):
    def test_native_command_codes_match_the_adapter_header(self):
        header = (ADAPTER / 'include' / 'MediaRemoteAdapter.h').read_text()
        codes = {name: int(value) for name, value in re.findall(r'(kMRA\w+)\s*=\s*(\d+)', header)}
        native = (ROOT / 'packaging' / 'RelayNowPlaying.m').read_text()
        table = dict(re.findall(r'@"(toggle|next|previous)":\s*@"(\d+)"', native))
        self.assertEqual({key: int(value) for key, value in table.items()},
                         {'toggle': codes['kMRATogglePlayPause'], 'next': codes['kMRANextTrack'], 'previous': codes['kMRAPreviousTrack']})


class MusicViewTests(unittest.TestCase):
    def test_page_has_the_player_and_its_controls(self):
        html = (ROOT / 'static' / 'notch.html').read_text()
        for element in ('id="music"', 'id="musicArt"', 'id="musicTitle"', 'id="musicArtist"', 'id="musicPrev"', 'id="musicToggle"',
                        'id="musicNext"', 'id="musicElapsed"', 'id="musicRemaining"', 'id="progressFill"'):
            self.assertIn(element, html)
        self.assertNotIn('style="', html)

    def test_page_listens_for_the_app_and_sends_only_known_commands(self):
        script = (ROOT / 'static' / 'notch.js').read_text()
        self.assertIn('window.relayNowPlaying', script)
        sent = set(re.findall(r"\['music(?:Prev|Toggle|Next)', '(\w+)'\]", script))
        self.assertEqual(sent, {'previous', 'toggle', 'next'})
        self.assertIn("type: 'media'", script)

    def test_native_side_only_accepts_plain_image_types_for_artwork(self):
        native = (ROOT / 'packaging' / 'RelayNowPlaying.m').read_text()
        self.assertNotIn('svg', native.lower())
        for kind in ('image/png', 'image/jpeg', 'image/gif', 'image/webp'):
            self.assertIn(kind, native)

    def test_native_side_sends_progress_and_detects_track_changes(self):
        native = (ROOT / 'packaging' / 'RelayNowPlaying.m').read_text()
        for key in ('elapsedTime', 'duration', 'playbackRate', 'timestamp', 'trackChangeHandler', 'primed'):
            self.assertIn(key, native)


class PanelShapeTests(unittest.TestCase):
    """The panel has a tab row, a pill for track changes, and three shapes chosen by the app."""

    def test_page_has_four_tabs_and_a_pill(self):
        html = (ROOT / 'static' / 'notch.html').read_text()
        for element in ('id="tabMusic"', 'id="tabNotes"', 'id="tabTask"', 'id="tabOffice"', 'id="pill"', 'id="pillArt"',
                        'id="pillTitle"', 'id="pillArtist"', 'class="eq"', 'data-mode='):
            self.assertIn(element, html)
        # Every tab is an icon with an accessible name.
        for tab in re.findall(r'<button[^>]*role="tab"[^>]*>', html):
            self.assertIn('aria-label=', tab)

    def test_office_tab_is_always_there_and_opens_the_full_panel(self):
        css = (ROOT / 'static' / 'notch.css').read_text()
        self.assertNotIn('#tabOffice { display: none', css)
        script = (ROOT / 'static' / 'notch.js').read_text()
        self.assertIn("type: 'expand', view: 'office'", script)
        self.assertIn("type: 'shrink'", script)  # leaving the Office returns to the small panel
        self.assertIn("next === 'office' && mode !== 'full'", script)  # the room itself never shows in the small panel

    def test_page_answers_the_app_about_its_shape(self):
        script = (ROOT / 'static' / 'notch.js').read_text()
        self.assertIn('window.relayPanelMode', script)
        self.assertIn("type: 'ready'", script)
        self.assertIn("['pill', 'compact', 'full']", script)

    def test_native_panel_has_three_shapes_and_the_right_triggers(self):
        native = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        for name in ('RelayPanelModePill', 'RelayPanelModeCompact', 'RelayPanelModeFull'):
            self.assertIn(name, native)
        # Hovering opens the small panel; the keyboard shortcut opens the full one on the Office tab.
        hover = native.split('- (void)scheduleShow', 1)[1].split('- (void)scheduleHide', 1)[0]
        self.assertIn('mode:RelayPanelModeCompact', hover)
        toggle = native.split('- (void)toggle {', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('mode:RelayPanelModeFull view:@"office"', toggle)
        for message in ('ready', 'expand', 'hold', 'media'):
            self.assertIn('isEqualToString:@"%s"' % message, native)

    def test_every_message_the_page_sends_is_handled_by_the_app(self):
        script = (ROOT / 'static' / 'notch.js').read_text()
        native = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        for message in set(re.findall(r"type: '(\w+)'", script)):
            self.assertIn('isEqualToString:@"%s"' % message, native, message)


class AmbientLightTests(unittest.TestCase):
    """The notch glows while agents work or music plays, even with the panel closed."""

    def test_glow_window_never_takes_the_pointer_and_sits_under_the_panel(self):
        glow = (ROOT / 'packaging' / 'RelayNotchGlow.m').read_text()
        self.assertIn('ignoresMouseEvents = YES', glow)
        # Only a non-activating panel stays over other apps, full-screen apps and every Space.
        for needle in ('NSPanel', 'NSWindowStyleMaskNonactivatingPanel', 'NSWindowCollectionBehaviorCanJoinAllSpaces', 'NSWindowCollectionBehaviorFullScreenAuxiliary', 'canHide = NO', 'constrainFrameRect'):
            self.assertIn(needle, glow)
        self.assertIn('NSMainMenuWindowLevel + 1', glow)
        self.assertIn('accessibilityDisplayShouldReduceMotion', glow)
        panel = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        self.assertIn('NSMainMenuWindowLevel + 2', panel)

    def test_glow_is_only_lines_around_the_notch_with_a_burst(self):
        glow = (ROOT / 'packaging' / 'RelayNotchGlow.m').read_text()
        for needle in ('self.halo', 'self.outline', 'self.sparks', '- (void)burst', 'strokeStart'):
            self.assertIn(needle, glow)
        # No bars or dots hanging below the notch: only the lines that run around it.
        for gone in ('self.bars', 'self.dots', 'transform.scale.y'):
            self.assertNotIn(gone, glow)
        header = (ROOT / 'packaging' / 'RelayNotchGlow.h').read_text()
        for method in ('showMusicColor:', 'showAgentActor:', 'burst', 'hide'):
            self.assertIn(method, header)
        panel = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        self.assertIn('[weakSelf.glow burst]', panel)  # a new track ripples the light

    def test_panel_drives_the_glow_from_agents_and_music(self):
        panel = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        for needle in ('RelayNotchGlow', '/api/notch', 'refreshGlow', 'DominantColor', 'stopAmbient'):
            self.assertIn(needle, panel)
        # Agents at work win over music.
        order = panel.split('- (void)refreshGlow', 1)[1]
        self.assertLess(order.index('agentActor'), order.index('playing'))

    def test_native_side_names_the_app_the_sound_comes_from(self):
        native = (ROOT / 'packaging' / 'RelayNowPlaying.m').read_text()
        for needle in ('appName', 'appIcon', 'parentApplicationBundleIdentifier', 'URLForApplicationWithBundleIdentifier'):
            self.assertIn(needle, native)

    def test_page_shows_the_source_and_uses_the_new_buttons(self):
        html = (ROOT / 'static' / 'notch.html').read_text()
        for element in ('id="musicSource"', 'id="musicApp"', 'id="musicAppIcon"', 'class="music-btn skip"', 'class="music-btn main"'):
            self.assertIn(element, html)
        script = (ROOT / 'static' / 'notch.js').read_text()
        self.assertIn("startsWith('data:image/png')", script)  # only a plain PNG icon is ever used

    def test_build_script_keeps_its_executable_bit(self):
        import os
        for name in ('build_macos_app.sh', 'make_dmg.sh', 'setup_macos_packaging.sh'):
            self.assertTrue(os.access(ROOT / 'scripts' / name, os.X_OK), name)


if __name__ == '__main__':
    unittest.main()
