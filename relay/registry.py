"""Saved projects, team presets, and folder browsing."""
import json
from pathlib import Path
import uuid
from .contracts import DEFAULT_TEAM


def team_presets(app):
    with app.LOCK:
        path = app.DATA / 'teams.json'
        presets = json.loads(path.read_text()) if path.exists() else []
        if not isinstance(presets, list):
            raise ValueError('Saved team presets could not be read.')
        return {'default': app.validate_team(DEFAULT_TEAM), 'presets': [{'id': p['id'], 'team': app.validate_team(p['team'])} for p in presets]}


def save_team_preset(app, team, preset_id=None):
    team = app.validate_team(team)
    with app.LOCK:
        presets = app.team_presets()['presets']
        if preset_id is not None and (not isinstance(preset_id, str) or not any(p['id'] == preset_id for p in presets)):
            raise ValueError('Saved preset was not found.')
        if any(p['team']['name'].casefold() == team['name'].casefold() and p['id'] != preset_id for p in presets):
            raise ValueError('A preset with this name already exists. Choose it to update or use a different name.')
        entry = {'id': preset_id or uuid.uuid4().hex, 'team': team}
        presets = [entry if p['id'] == preset_id else p for p in presets] if preset_id else presets + [entry]
        app.DATA.mkdir(parents=True, exist_ok=True)
        temporary = app.DATA / 'teams.tmp'
        temporary.write_text(json.dumps(presets, ensure_ascii=False, indent=2))
        temporary.replace(app.DATA / 'teams.json')
        return entry


def read_projects(app):
    path = app.DATA / 'projects.json'
    if not path.exists():
        return []
    projects = json.loads(path.read_text())
    if not isinstance(projects, list):
        raise ValueError('Saved projects could not be read.')
    return projects


def project_choices(app):
    with app.LOCK:
        projects = app.read_projects()
        return {'projects': [dict(p, exists=Path(p['path']).is_dir()) for p in projects]}


def save_project(app, name, path):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        raise ValueError('Enter a project name between 1 and 80 characters.')
    if not isinstance(path, str) or not path.strip():
        raise ValueError('Choose a project folder.')
    folder = Path(path).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError('Choose an existing folder.')
    name = name.strip()
    with app.LOCK:
        projects = app.read_projects()
        if any(p['name'].casefold() == name.casefold() for p in projects):
            raise ValueError('A project with that name is already saved.')
        if any(p['path'] == str(folder) for p in projects):
            raise ValueError('That folder is already saved. Select it from the project list.')
        project = dict(id=uuid.uuid4().hex, name=name, path=str(folder))
        projects.append(project)
        app.write_projects(projects)
    return project


def write_projects(app, projects):
    app.DATA.mkdir(parents=True, exist_ok=True)
    temp = app.DATA / 'projects.tmp'
    temp.write_text(json.dumps(projects, ensure_ascii=False, indent=2))
    temp.replace(app.DATA / 'projects.json')


def remove_project(app, project_id):
    with app.LOCK:
        projects = app.read_projects()
        remaining = [p for p in projects if p['id'] != project_id]
        if len(remaining) == len(projects):
            raise ValueError('Saved project was not found.')
        app.write_projects(remaining)


def folder_choices(path=None):
    if path is not None and not isinstance(path, str):
        raise ValueError('Enter a valid folder path.')
    folder = Path(path).expanduser().resolve() if path else Path.home()
    if not folder.is_dir():
        raise ValueError('This folder does not exist.')
    children = []
    for child in folder.iterdir():
        try:
            if not child.name.startswith('.') and child.is_dir():
                children.append(dict(name=child.name, path=str(child)))
        except OSError:
            continue
    children.sort(key=lambda p: p['name'].casefold())
    return dict(path=str(folder), parent=str(folder.parent), folders=children[:500],
                truncated=len(children) > 500)
