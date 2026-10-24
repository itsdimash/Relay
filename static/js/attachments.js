import { state as appState } from './state.js';
import { $, e } from './dom.js';
export function createAttachments({
  updateButtons
}) {
  function imagePayload(prefix) {
    return appState.imageDrafts[prefix].map(({
      name,
      mime,
      data
    }) => ({
      name,
      mime,
      data
    }));
  }
  function clearImageDraft(prefix) {
    appState.imageDrafts[prefix] = [];
    $(prefix + 'ImageInput').value = '';
    renderImageDraft(prefix);
  }
  function renderImageDraft(prefix) {
    $(prefix + 'ImagePreviews').innerHTML = appState.imageDrafts[prefix].map((image, i) => `<div class="image-preview"><img src="data:${image.mime};base64,${image.data}" alt="${e(image.name)}"><div><strong>${e(image.name)}</strong><span>${(image.size / 1024 / 1024).toFixed(1)} MB</span></div><button type="button" data-remove-image="${i}" aria-label="Remove ${e(image.name)}">×</button></div>`).join('');
    $(prefix + 'ImageNotice').textContent = appState.imageDrafts[prefix].length ? `${appState.imageDrafts[prefix].length} selected · saved with your chat when sent. Reselect unsent images after reloading.` : '';
  }
  async function addImageFiles(prefix, files) {
    if (appState.imageLoading) {
      $(prefix + 'ImageNotice').textContent = 'Wait for the current images to finish loading.';
      return;
    }
    const inherited = prefix === 'followup' ? appState.runs.find(r => r.id === appState.selected)?.attachments?.length || 0 : appState.pendingSource ? appState.runs.find(r => r.id === appState.pendingSource.source_id)?.attachments?.length || 0 : 0;
    if (appState.imageDrafts[prefix].length + files.length + inherited > 4) {
      $(prefix + 'ImageNotice').textContent = `Up to four images are allowed, including ${inherited} inherited from this report.`;
      return;
    }
    appState.imageLoading++;
    updateButtons();
    $(prefix + 'ImageNotice').textContent = 'Reading images…';
    try {
      const added = [];
      for (const file of files) {
        const mime = file.type || (/\.png$/i.test(file.name) ? 'image/png' : /\.jpe?g$/i.test(file.name) ? 'image/jpeg' : /\.webp$/i.test(file.name) ? 'image/webp' : '');
        if (!['image/png', 'image/jpeg', 'image/webp'].includes(mime)) throw new Error('Choose PNG, JPEG, or WebP images. Convert HEIC files first.');
        if (!file.size || file.size > 4 * 1024 * 1024) throw new Error('Each image must be 4 MB or smaller.');
        const data = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result.split(',')[1]);
          reader.onerror = () => reject(new Error('Could not read this image.'));
          reader.readAsDataURL(file);
        });
        added.push({
          name: file.name || 'Screenshot.png',
          mime,
          data,
          size: file.size
        });
      }
      appState.imageDrafts[prefix].push(...added);
      renderImageDraft(prefix);
    } catch (error) {
      $(prefix + 'ImageNotice').textContent = error.message;
    } finally {
      appState.imageLoading--;
      updateButtons();
      $(prefix + 'ImageInput').value = '';
    }
  }
  function init() {
    for (const prefix of ['task', 'followup']) {
      const input = $(prefix + 'ImageInput'),
        drop = $(prefix + 'ImageDrop');
      $(prefix + 'AttachImages').addEventListener('click', () => input.click());
      input.addEventListener('change', () => addImageFiles(prefix, [...input.files]));
      $(prefix + 'ImagePreviews').addEventListener('click', event => {
        const button = event.target.closest('[data-remove-image]');
        if (button) {
          appState.imageDrafts[prefix].splice(Number(button.dataset.removeImage), 1);
          renderImageDraft(prefix);
        }
      });
      for (const kind of ['dragenter', 'dragover']) drop.addEventListener(kind, event => {
        event.preventDefault();
        drop.classList.add('is-dragging');
      });
      drop.addEventListener('dragleave', event => {
        if (!drop.contains(event.relatedTarget)) drop.classList.remove('is-dragging');
      });
      drop.addEventListener('drop', event => {
        event.preventDefault();
        drop.classList.remove('is-dragging');
        addImageFiles(prefix, [...event.dataTransfer.files]);
      });
      const textarea = $(prefix === 'task' ? 'task' : 'followupQuestion');
      textarea.addEventListener('dragover', event => {
        if ([...event.dataTransfer.types].includes('Files')) event.preventDefault();
      });
      textarea.addEventListener('drop', event => {
        if (event.dataTransfer.files.length) {
          event.preventDefault();
          addImageFiles(prefix, [...event.dataTransfer.files]);
        }
      });
      $(prefix === 'task' ? 'task' : 'followupQuestion').addEventListener('paste', event => {
        const files = [...event.clipboardData.items].filter(item => item.kind === 'file').map(item => item.getAsFile()).filter(Boolean);
        if (files.length) {
          event.preventDefault();
          addImageFiles(prefix, files);
        }
      });
    }
  }
  return {
    init,
    imagePayload,
    clearImageDraft
  };
}
