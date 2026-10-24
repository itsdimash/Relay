"""Git inspection and complete patch export; never stage into the real index."""
import os
from pathlib import Path
import subprocess
import tempfile


def git(path, *args, timeout=30):
    p = subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise ValueError(p.stderr.strip() or 'Git operation failed')
    return p.stdout


def capture_file_reviews(workspace):
    root = Path(workspace).resolve()
    records = git(root, 'diff', '--no-renames', '--name-status', '-z', 'HEAD', '--').split('\0')
    entries = [(records[i], records[i+1]) for i in range(0, len(records)-1, 2)]
    entries += [('?', name) for name in git(root, 'ls-files', '--others', '--exclude-standard', '-z').split('\0') if name]
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
                        item['notice'] = 'Binary file. Inspect it in the working copy.'
                    else:
                        item['content'] = raw[:limit].decode('utf-8')
                        item['additions'] = len(item['content'].splitlines())
                        if len(raw)>limit:item['notice'] = 'Preview truncated. The complete file remains in the working copy.'
                except (UnicodeError, OSError):
                    item['notice'] = 'This file cannot be shown as text. Inspect it in the working copy.'
        else:
            text = git(root, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', 'HEAD', '--', name)
            item['content'] = text[:limit]
            item['additions'] = sum(line.startswith('+') and not line.startswith('+++') for line in text.splitlines())
            item['deletions'] = sum(line.startswith('-') and not line.startswith('---') for line in text.splitlines())
            if len(text)>limit:item['notice'] = 'Diff preview truncated. Inspect the full diff in the working copy.'
            if 'Binary files ' in text or 'GIT binary patch' in text:item['notice'] = 'Binary file changed. Inspect it in the working copy.'
        budget -= len(item['content'])
        reviews.append(item)
    return reviews


def complete_patch(workspace):
    """Build a complete binary patch without touching the project's real index."""
    with tempfile.TemporaryDirectory(prefix='relay-export-') as folder:
        env = os.environ.copy()
        env['GIT_INDEX_FILE'] = str(Path(folder) / 'index')
        def command(*args):
            result = subprocess.run(['git', '-C', str(workspace), *args], env=env,
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
