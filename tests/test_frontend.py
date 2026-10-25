"""Frontend behavior without installing a JavaScript framework or paid providers."""
from pathlib import Path
import shutil
import subprocess
import unittest


class RunHistoryInterfaceTests(unittest.TestCase):
    def test_saved_runs_are_distinct_from_the_composer_and_steps_are_interactive(self):
        root = Path(__file__).parents[1]
        conversation = (root / 'static/js/conversation.js').read_text()
        brand = (root / 'static/brand.css').read_text()

        self.assertIn("classList.toggle('run-open', !!r)", conversation)
        self.assertIn("Already submitted · this is the saved run", conversation)
        self.assertIn("setAttribute('role', 'tablist')", conversation)
        self.assertIn('data-run-step=', conversation)
        self.assertIn('No clarification was needed for this run.', conversation)
        self.assertIn('.content.run-open > .workspace-grid { display: none; }', brand)


@unittest.skipUnless(shutil.which('node'), 'Node is required for frontend checks')
class NotificationTests(unittest.TestCase):
    def test_notification_timing_focus_and_async_actions(self):
        module=Path(__file__).parents[1]/'static/js/notifications.js'
        script=r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  const { createNotifications } = await import('data:text/javascript;base64,' + fs.readFileSync(process.argv[1]).toString('base64'));
  let current = 0, ident = 0, focused = null;
  const timers = new Map();
  class Element extends EventTarget {
    hidden = true; disabled = false; textContent = ''; isConnected = true; children = [];
    contains(el) { return el === this || this.children.includes(el); }
    matches() { return false; }
    focus() { focused = this; }
  }
  const container = new Element(), message = new Element(), actionButton = new Element(), closeButton = new Element(), outside = new Element();
  container.children = [actionButton, closeButton]; focused = outside;
  const notification = createNotifications({ container, message, actionButton, closeButton,
    now: () => current, activeElement: () => focused,
    setTimer: (fn, delay) => { timers.set(++ident, { fn, due: current + delay }); return ident; },
    clearTimer: id => timers.delete(id),
  });
  const advance = ms => {
    current += ms;
    for (const [id, timer] of [...timers]) if (timer.due <= current) { timers.delete(id); timer.fn(); }
  };
  const fire = (el, name) => el.dispatchEvent(new Event(name));
  const flush = () => new Promise(resolve => setImmediate(resolve));

  notification.show('Saved'); advance(3999); assert.equal(container.hidden, false);
  advance(1); assert.equal(container.hidden, true);

  notification.show('Old'); const stale = [...timers.values()][0].fn;
  advance(1000); notification.show('New', { duration: 8000 }); stale();
  assert.equal(container.hidden, false); assert.equal(message.textContent, 'New');
  advance(7999); assert.equal(container.hidden, false); advance(1); assert.equal(container.hidden, true);

  notification.show('Undo available', { duration: 10000, actionLabel: 'Undo', onAction() {} });
  advance(2000); fire(container, 'mouseenter'); advance(30000);
  assert.equal(container.hidden, false);
  focused = actionButton; fire(container, 'focusin'); fire(container, 'mouseleave'); advance(30000);
  assert.equal(container.hidden, false, 'Leaving hover must not expire a focused action');
  focused = outside; fire(container, 'focusout'); await flush();
  advance(7999); assert.equal(container.hidden, false); advance(1); assert.equal(container.hidden, true);

  let resolveAction, calls = 0;
  notification.show('Undo', { duration: 10000, actionLabel: 'Undo', onAction: () => { calls++; return new Promise(resolve => resolveAction = resolve); } });
  fire(actionButton, 'click'); fire(actionButton, 'click'); assert.equal(calls, 1);
  advance(30000); assert.equal(container.hidden, false);
  notification.show('More recent message'); resolveAction(); await flush();
  assert.equal(message.textContent, 'More recent message'); assert.equal(container.hidden, false);

  notification.show('Persistent error', { duration: 0 }); advance(60000); assert.equal(container.hidden, false);
  focused = closeButton; fire(closeButton, 'click'); assert.equal(container.hidden, true);
  assert.equal(focused, outside, 'Dismiss should restore the previous focus');
  notification.show('Restored'); advance(4000); assert.equal(container.hidden, true);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        subprocess.run(['node','-e',script,str(module)],check=True,capture_output=True,text=True)
