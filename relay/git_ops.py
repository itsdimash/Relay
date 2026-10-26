"""Git inspection and complete patch export; never stage into the real index."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

LARGE_FILE = 5 * 1024 * 1024
LARGE_FOLDER = 50 * 1024 * 1024
CACHE_FILES = ('.DS_Store',)
CACHE_DIRS = ('node_modules', '.venv', 'venv', '__pycache__', '.mypy_cache', '.pytest_cache', '.tox', '.ipynb_checkpoints')


def git_command(path, shadow=None):
    """Plain `git -C path`, or a private baseline store that tracks the folder without touching it."""
    if shadow:
        return ['git', '--git-dir', str(shadow), '--work-tree', str(path)]
    return ['git', '-C', str(path)]


def git(path, *args, timeout=30, shadow=None):
    p = subprocess.run([*git_command(path, shadow), *args], cwd=str(path) if shadow else None, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise ValueError(p.stderr.strip() or 'Git operation failed')
    return p.stdout


def _escape(pattern):
    return re.sub(r'([\\*?\[\]#!])', r'\\\1', pattern)


def create_baseline(folder, shadow, skip=()):
    """Record a folder's files in a private Git store outside it, so direct edits can be reviewed as a diff against this moment.

    Ignored files follow the folder's own .gitignore. Caches, nested repositories, very large files and
    very large top-level folders are left out of the baseline (and so out of the diff); they are returned.
    """
    folder, shadow = Path(folder).resolve(), Path(shadow)
    if shadow.exists():
        shutil.rmtree(shadow)
    shadow.parent.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != 'GIT_WORK_TREE'}
    env['GIT_DIR'] = str(shadow)
    init = subprocess.run(['git', 'init', '-q'], env=env, capture_output=True, text=True, timeout=30)
    if init.returncode:
        raise ValueError(init.stderr.strip() or 'Could not prepare the baseline.')
    skipped, sizes = [], {}
    for current, dirs, files in os.walk(folder):
        relative = Path(current).relative_to(folder)
        keep = []
        for name in dirs:
            full = Path(current) / name
            if name in CACHE_DIRS or name == '.git' or full.is_symlink():
                continue
            if (full / '.git').exists():
                skipped.append('/' + (relative / name).as_posix() + '/')
                continue
            keep.append(name)
        dirs[:] = keep
        for name in files:
            full = Path(current) / name
            try:
                size = 0 if full.is_symlink() else full.stat().st_size
            except OSError:
                continue
            if size > LARGE_FILE:
                skipped.append('/' + (relative / name).as_posix())
            if relative.parts:
                sizes[relative.parts[0]] = sizes.get(relative.parts[0], 0) + size
    skipped += ['/' + name + '/' for name, total in sorted(sizes.items()) if total > LARGE_FOLDER]
    for path in skip:
        # Folders Relay itself writes to (its data folder) must never count as the Builder's changes.
        try:
            skipped.append('/' + Path(path).resolve().relative_to(folder).as_posix() + '/')
        except ValueError:
            pass
    excludes = [name + '/' for name in CACHE_DIRS] + list(CACHE_FILES) + [_escape(item) for item in skipped if '\n' not in item]
    (shadow / 'info').mkdir(exist_ok=True)
    (shadow / 'info' / 'exclude').write_text('\n'.join(excludes) + '\n')
    quiet = ['-c', 'user.name=Relay', '-c', 'user.email=relay@localhost', '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null']
    def run(*args):
        result = subprocess.run([*git_command(folder, shadow), *quiet, *args], cwd=str(folder), capture_output=True, text=True, timeout=600)
        if result.returncode:
            raise ValueError(result.stderr.strip() or 'Could not record the baseline.')
        return result.stdout
    run('add', '-A')
    run('commit', '-q', '--allow-empty', '-m', 'Relay baseline')
    return run('rev-parse', 'HEAD').strip(), skipped


def capture_file_reviews(workspace, shadow=None):
    root = Path(workspace).resolve()
    records = git(root, 'diff', '--no-renames', '--name-status', '-z', 'HEAD', '--', shadow=shadow).split('\0')
    entries = [(records[i], records[i+1]) for i in range(0, len(records)-1, 2)]
    entries += [('?', name) for name in git(root, 'ls-files', '--others', '--exclude-standard', '-z', shadow=shadow).split('\0') if name]
    reviews, budget = [], 600000
    for status, name in entries:
        item = dict(path=name, status={'?':'new','A':'added','D':'deleted','M':'modified','T':'type_changed'}.get(status,'modified'), content='', notice='', additions=0, deletions=0)
        limit = min(100000, budget)
        if limit <= 0:
            item['notice'] = 'Preview budget reached. Inspect this file in the working copy.'
        elif status == '?':
            candidate = root / name
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(root) or not candidate.is_file():
                item['notice'] = 'Link or non-regular file. Preview is unavailable.'
            else:
                try:
                    with candidate.open('rb') as stream: raw = stream.read(limit+1)
                    if b'\0' in raw:
                        item['notice'] = 'Binary file. Inspect it in your folder.'
                    else:
                        item['content'] = raw[:limit].decode('utf-8')
                        item['additions'] = len(item['content'].splitlines())
                        if len(raw)>limit:item['notice'] = 'Preview truncated. The complete file is in your folder.'
                except (UnicodeError, OSError):
                    item['notice'] = 'This file cannot be shown as text. Inspect it in your folder.'
        else:
            text = git(root, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', 'HEAD', '--', name, shadow=shadow)
            item['content'] = text[:limit]
            item['additions'] = sum(line.startswith('+') and not line.startswith('+++') for line in text.splitlines())
            item['deletions'] = sum(line.startswith('-') and not line.startswith('---') for line in text.splitlines())
            if len(text)>limit:item['notice'] = 'Diff preview truncated. Inspect the full diff in your folder.'
            if 'Binary files ' in text or 'GIT binary patch' in text:item['notice'] = 'Binary file changed. Inspect it in your folder.'
        budget -= len(item['content'])
        reviews.append(item)
    return reviews


def complete_patch(workspace, shadow=None):
    """Build a complete binary patch without touching the project's real index."""
    with tempfile.TemporaryDirectory(prefix='relay-export-') as folder:
        env = os.environ.copy()
        env['GIT_INDEX_FILE'] = str(Path(folder) / 'index')
        def command(*args):
            result = subprocess.run([*git_command(workspace, shadow), *args], env=env, cwd=str(workspace) if shadow else None,
                                    capture_output=True, timeout=60)
            if result.returncode:
                raise ValueError(result.stderr.decode('utf-8', errors='replace').strip() or 'Could not export changes.')
            return result.stdout
        command('read-tree', 'HEAD')
        command('add', '-A', '--', '.')
        return command('diff', '--cached', '--binary', '--full-index', '--no-renames',
                       '--no-ext-diff', '--no-textconv', '--src-prefix=a/', '--dst-prefix=b/', 'HEAD', '--')


def git_common_directory(workspace):
    common = Path(git(workspace, 'rev-parse', '--git-common-dir').strip())
    return str((Path(workspace) / common).resolve() if not common.is_absolute() else common.resolve())
