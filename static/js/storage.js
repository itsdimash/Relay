import { state as appState } from './state.js';
import { $ } from './dom.js';
import { request } from './api.js';

/** Disk use of saved chats, and the optional limits on how much history is kept. */
function readable(bytes) {
  if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(1) + ' GB';
  if (bytes >= 1024 ** 2) return Math.round(bytes / 1024 ** 2) + ' MB';
  return Math.max(1, Math.round(bytes / 1024)) + ' KB';
}

export function createStorage({ notifications }) {
  let pending = null;
  async function refresh() {
    try {
      const usage = await request('/api/storage');
      $('storageSummary').textContent = 'Storage · ' + readable(usage.bytes);
      $('storageChats').value = usage.policy.max_chats === null ? '' : String(usage.policy.max_chats);
      $('storageSize').value = usage.policy.max_mb === null ? '' : String(usage.policy.max_mb);
      $('storageNote').textContent = `${usage.chats} saved chats.`;
    } catch (_) {
      /* shown again the next time the section is opened */
    }
  }
  async function choose(key, value) {
    const change = { [key]: value === '' ? null : Number(value) };
    try {
      const preview = await request('/api/storage/policy', { ...change, preview: true });
      if (preview.would_delete > 0) {
        pending = change;
        $('storageDialogText').textContent = `${preview.would_delete} older finished ${preview.would_delete === 1 ? 'chat' : 'chats'} will be deleted permanently. Your project files stay as they are.`;
        $('storageDialog').showModal();
        return;
      }
      await apply(change);
    } catch (error) {
      notifications.show(error.message, { duration: 0 });
      refresh();
    }
  }
  async function apply(change) {
    const result = await request('/api/storage/policy', change);
    if (result.deleted.length) {
      appState.runs = appState.runs.filter(run => !result.deleted.includes(run.id));
      if (result.deleted.includes(appState.selected)) appState.selected = null;
      appState.rendered = '';
      notifications.show(`Deleted ${result.deleted.length} older ${result.deleted.length === 1 ? 'chat' : 'chats'}.`);
    }
    refresh();
  }
  function init() {
    $('storageChats').addEventListener('change', event => choose('max_chats', event.target.value));
    $('storageSize').addEventListener('change', event => choose('max_mb', event.target.value));
    $('storageCancel').addEventListener('click', () => {
      pending = null;
      $('storageDialog').close();
      refresh();
    });
    $('storageConfirm').addEventListener('click', async () => {
      const change = pending;
      pending = null;
      $('storageDialog').close();
      try {
        await apply(change);
      } catch (error) {
        notifications.show(error.message, { duration: 0 });
        refresh();
      }
    });
    $('storageDialog').addEventListener('cancel', () => {
      pending = null;
      refresh();
    });
    $('storage').addEventListener('toggle', () => {
      if ($('storage').open) refresh();
    });
    refresh();
  }
  return { init, refresh };
}
