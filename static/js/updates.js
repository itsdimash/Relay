/** Offers app updates found on GitHub Releases. Only active inside the packaged Relay app. */
import { $ } from './dom.js';
import { request } from './api.js';
import { state } from './state.js';

export function createUpdates({ recheckMs = 30 * 60 * 1000 } = {}) {
  let dismissed = '';
  function show(info) {
    const banner = $('updateBanner');
    if (!info.available || info.latest === dismissed) {
      banner.hidden = true;
      return;
    }
    $('updateText').textContent = `Relay ${info.latest} is available (you have ${info.current}).`;
    $('updateNow').disabled = false;
    $('updateError').textContent = '';
    banner.hidden = false;
    banner.dataset.version = info.latest;
  }
  async function check() {
    try {
      show(await request('/api/update'));
    } catch (_) {
      /* Offline: try again later. */
    }
  }
  async function install() {
    const button = $('updateNow');
    button.disabled = true;
    $('updateText').textContent = 'Downloading the update… Relay will restart in a moment.';
    $('updateError').textContent = '';
    try {
      await request('/api/update/install', {});
      $('updateText').textContent = 'Restarting Relay with the new version…';
      $('updateNow').hidden = true;
      $('updateLater').hidden = true;
    } catch (error) {
      $('updateText').textContent = `Relay ${$('updateBanner').dataset.version} is available.`;
      $('updateError').textContent = error.message;
      button.disabled = false;
    }
  }
  function init() {
    $('updateNow').addEventListener('click', install);
    $('updateLater').addEventListener('click', () => {
      dismissed = $('updateBanner').dataset.version || '';
      $('updateBanner').hidden = true;
    });
    // The dashboard token arrives with the first state poll; check once it is there.
    const wait = setInterval(() => {
      if (!state.token) return;
      clearInterval(wait);
      check();
      setInterval(check, recheckMs);
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden) check();
      });
    }, 500);
  }
  return { init, check };
}
