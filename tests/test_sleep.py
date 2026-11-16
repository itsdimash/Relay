"""Closing the Mac's lid and opening it again: the notch, "Hey Relay" and the music strip must come back by themselves.
The native side cannot be built or run here, so its source is checked for the recovery steps that must not be lost."""
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
PACKAGING = ROOT / 'packaging'
PANEL = (PACKAGING / 'RelayNotchPanel.m').read_text()
WAKE = (PACKAGING / 'RelayWake.m').read_text()
PLAYING = (PACKAGING / 'RelayNowPlaying.m').read_text()
PLAYING_H = (PACKAGING / 'RelayNowPlaying.h').read_text()
NOTCH = (ROOT / 'static' / 'notch.js').read_text()


def body(source, signature):
    return source.split(signature, 1)[1].split('\n}\n', 1)[0]


class NotchTests(unittest.TestCase):
    def test_the_panel_listens_for_wake_and_screen_changes(self):
        observe = body(PANEL, '- (void)observeSleepAndScreens {')
        for name in ('NSWorkspaceDidWakeNotification', 'NSWorkspaceScreensDidWakeNotification',
                     'NSWorkspaceSessionDidBecomeActiveNotification', 'NSApplicationDidChangeScreenParametersNotification'):
            self.assertIn(name, observe)
        self.assertIn('[self observeSleepAndScreens];', body(PANEL, '- (instancetype)initWithPageURL:(NSURL *)pageURL {'))
        self.assertIn('removeObserver:self', body(PANEL, '- (void)dealloc {'))

    def test_a_wake_rebuilds_the_pointer_watch_the_music_and_the_page(self):
        recover = body(PANEL, '- (void)recoverAfterWake:(BOOL)heavy {')
        self.assertLess(recover.index('[self removeMonitors];'), recover.index('[self installMonitors];'))
        self.assertIn('[self.nowPlaying restart];', recover)
        self.assertIn('[self refreshScreenPlacement];', recover)
        self.assertIn('[self checkPageAfterWake];', recover)
        for stuck in ('self.commandDown = NO;', 'self.draggingOut = NO;', 'self.optionDown = NO;'):
            self.assertIn(stuck, recover)

    def test_the_recovery_runs_twice_because_the_mac_is_not_ready_at_once(self):
        wake = body(PANEL, '- (void)systemDidWake:(NSNotification *)note {')
        self.assertIn('recoverAfterWake:YES', wake)
        self.assertIn('recoverAfterWake:NO', wake)
        self.assertIn('recoveryToken', wake)

    def test_a_page_that_does_not_answer_is_loaded_again(self):
        check = body(PANEL, '- (void)checkPageAfterWake {')
        self.assertIn('evaluateJavaScript', check)
        self.assertIn('loadRequest', check)
        self.assertIn('relayResume', check)

    def test_the_panel_follows_the_screens_after_a_change(self):
        place = body(PANEL, '- (void)refreshScreenPlacement {')
        self.assertIn('self.screen = screen', place)
        self.assertIn('[self applyProgress:self.progress]', place)
        self.assertIn('[self.glow screensChanged]', place)

    def test_the_music_stream_can_be_restarted(self):
        self.assertIn('- (void)restart;', PLAYING_H)
        restart = body(PLAYING, '- (void)restart {')
        self.assertIn('if (!self.wanted) return;', restart)
        self.assertIn('self.failures = 0;', restart)
        self.assertIn('[self launchStream];', restart)


class WakeWordTests(unittest.TestCase):
    def test_the_microphone_is_let_go_at_sleep_and_taken_again_at_wake(self):
        self.assertIn('NSWorkspaceWillSleepNotification', WAKE)
        self.assertIn('NSWorkspaceDidWakeNotification', WAKE)
        self.assertIn('[strongSelf beginAfter:2.0]', WAKE)
        dealloc = body(WAKE, '- (void)dealloc {')
        self.assertIn('_sleepObserver', dealloc)
        self.assertIn('_wakeObserver', dealloc)

    def test_a_start_that_fails_right_after_waking_is_tried_again_not_switched_off(self):
        fail = body(WAKE, '- (void)failWith:(NSString *)code {')
        self.assertLess(fail.index('retryAfterWake'), fail.index('self.enabled = NO;'))
        retry = body(WAKE, '- (BOOL)retryAfterWake:(NSString *)code {')
        self.assertIn('MaxWakeRetries', retry)
        self.assertIn('WakeGraceSeconds', retry)
        # permission problems are the person's to fix: they are never retried
        self.assertNotIn('speech-denied', fail.split('retryAfterWake', 1)[0])
        self.assertNotIn('mic-denied', fail.split('retryAfterWake', 1)[0])


class PageTests(unittest.TestCase):
    def test_the_page_catches_up_after_a_sleep(self):
        resume = body(NOTCH, 'function resumeAfterSleep() {')
        for call in ('poll();', 'loadNotes();', 'loadDeliver();', 'syncWake();'):
            self.assertIn(call, resume)
        self.assertIn('wake.sent = null;', resume)  # not '': that would say "Hey Relay is on" again
        self.assertIn('window.relayResume = resumeAfterSleep;', NOTCH)

    def test_a_gap_in_the_beat_counts_as_a_sleep(self):
        self.assertIn('gap > 10000', NOTCH)


if __name__ == '__main__':
    unittest.main()
