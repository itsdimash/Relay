import { $, e } from './dom.js';
import { request } from './api.js';
export function createProjects({
  clearSourceBrief
}) {
  let savedProjects = [];
  let browsingPath = '';
  let browsingParent = '';
  function projectChanged() {
    const project = savedProjects.find(p => p.path === $('project').value);
    $('projectPath').textContent = project ? project.path : '';
    $('removeProject').disabled = !project;
    try {
      localStorage.setItem('relay.project', $('project').value);
    } catch (_) {}
  }
  function selectedProject() {
    return $('project').value;
  }
  async function loadProjects(preferred) {
    try {
      const result = await request('/api/projects');
      savedProjects = result.projects;
      $('project').innerHTML = '<option value="">' + (savedProjects.length ? 'Choose a saved project…' : 'No saved projects — add your first') + '</option>' + savedProjects.map(p => `<option value="${e(p.path)}" ${p.exists ? '' : 'disabled'}>${e(p.name)}${p.exists ? '' : ' (folder not found)'}</option>`).join('');
      let saved = preferred || '';
      try {
        if (!saved) saved = localStorage.getItem('relay.project') || '';
      } catch (_) {}
      if ([...$('project').options].some(o => o.value === saved && !o.disabled)) $('project').value = saved;
      projectChanged();
    } catch (error) {
      $('project').innerHTML = '<option value="">Saved projects unavailable</option>';
      $('projectNotice').textContent = 'Could not load saved projects. Restart Relay and try again. ' + error.message;
    }
  }
  async function browseFolders(path) {
    $('folderError').textContent = '';
    $('folderList').setAttribute('aria-busy', 'true');
    $('chooseFolder').disabled = true;
    $('folderGo').disabled = true;
    $('folderUp').disabled = true;
    try {
      const result = await request('/api/folders', {
        path: path || null
      });
      browsingPath = result.path;
      browsingParent = result.parent;
      $('folderLocation').value = result.path;
      $('folderList').innerHTML = result.folders.length ? result.folders.map(p => `<button type="button" class="folder-row" data-folder="${e(p.path)}"><span aria-hidden="true">▱</span><span>${e(p.name)}</span><span aria-hidden="true">›</span></button>`).join('') : '<p class="muted">No visible subfolders. You can choose this folder.</p>';
      $('folderHint').textContent = result.truncated ? 'Showing the first 500 folders. Enter a full path above to open another.' : 'Only folders are shown. Hidden folders can be opened by entering their path above.';
      $('chooseFolder').disabled = false;
      $('folderUp').disabled = browsingPath === browsingParent;
    } catch (error) {
      $('folderError').textContent = error.message;
      $('folderList').innerHTML = '';
      browsingPath = '';
      $('folderUp').disabled = false;
    } finally {
      $('folderList').setAttribute('aria-busy', 'false');
      $('folderGo').disabled = false;
    }
  }
  function init() {
    $('project').addEventListener('change', projectChanged);
    $('addProject').addEventListener('click', () => {
      $('projectForm').reset();
      $('projectError').textContent = '';
      $('projectDialog').showModal();
      $('projectName').focus();
    });
    $('cancelProject').addEventListener('click', () => $('projectDialog').close());
    $('projectForm').addEventListener('submit', async event => {
      event.preventDefault();
      $('projectError').textContent = '';
      $('saveProject').disabled = true;
      try {
        const project = await request('/api/projects/save', {
          name: $('projectName').value.trim(),
          path: $('projectFolder').value.trim()
        });
        await loadProjects(project.path);
        $('projectDialog').close();
        $('projectNotice').textContent = 'Project saved on this computer.';
      } catch (error) {
        $('projectError').textContent = error.message;
      } finally {
        $('saveProject').disabled = false;
      }
    });
    $('removeProject').addEventListener('click', async () => {
      const project = savedProjects.find(p => p.path === $('project').value);
      if (!project) return;
      $('removeProject').disabled = true;
      try {
        await request('/api/projects/remove', {
          id: project.id
        });
        await loadProjects();
        $('projectNotice').textContent = 'Saved project removed. The folder and its files are unchanged.';
      } catch (error) {
        $('projectNotice').textContent = error.message;
        projectChanged();
      }
    });
    $('browseFolder').addEventListener('click', () => {
      $('folderDialog').showModal();
      browseFolders($('projectFolder').value.trim());
    });
    $('cancelFolder').addEventListener('click', () => $('folderDialog').close());
    $('folderGo').addEventListener('click', () => browseFolders($('folderLocation').value.trim()));
    $('folderLocation').addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        if (!$('folderGo').disabled) browseFolders($('folderLocation').value.trim());
      }
    });
    $('folderUp').addEventListener('click', () => browseFolders(browsingParent));
    $('folderList').addEventListener('click', event => {
      const button = event.target.closest('[data-folder]');
      if (button && $('folderList').getAttribute('aria-busy') === 'false') browseFolders(button.dataset.folder);
    });
    $('chooseFolder').addEventListener('click', () => {
      if (browsingPath) {
        $('projectFolder').value = browsingPath;
        $('folderDialog').close();
        $('projectFolder').focus();
      }
    });
  }
  return {
    init,
    projectChanged,
    selectedProject,
    loadProjects
  };
}
