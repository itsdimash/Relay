"""Provider discovery, capability-limited commands, and response adapters."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
from .contracts import PROVIDERS, ROLES, SCHEMA


def executable(name):
    candidates = [os.environ.get('RELAY_' + name.upper()), shutil.which(name)]
    if name == 'codex':
        candidates += [
            '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex',
            '/Applications/Codex.app/Contents/Resources/codex',
            '/opt/homebrew/bin/codex',
            '/usr/local/bin/codex',
            str(Path.home() / '.local/bin/codex'),
        ]
    else:
        candidates += [
            '/opt/homebrew/bin/claude',
            '/usr/local/bin/claude',
            str(Path.home() / '.local/bin/claude'),
            str(Path.home() / '.claude/local/claude'),
        ]
    return next((p for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), None)


def model_catalog():
    levels = ['low', 'medium', 'high', 'xhigh', 'max']
    claude = [{'id': name, 'label': name.capitalize(), 'efforts': levels[:]} for name in ['haiku', 'sonnet', 'opus', 'fable']]
    fallback = [('gpt-6.1-sol', 'GPT-6.1 Sol', True), ('gpt-6-astra', 'GPT-6 Astra', True),
                ('gpt-6-sol', 'GPT-6 Sol', True), ('gpt-6-luna', 'GPT-6 Luna', False),
                ('gpt-5.6-sol', 'GPT-5.6 Sol', True), ('gpt-5.6-terra', 'GPT-5.6 Terra', True),
                ('gpt-5.6-luna', 'GPT-5.6 Luna', False)]
    codex = [{'id': name, 'label': label, 'efforts': levels + (['ultra'] if ultra else [])} for name, label, ultra in fallback]
    cache_path = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'models_cache.json'
    source = 'Built-in model list; availability depends on your CLI and account.'
    try:
        cache = json.loads(cache_path.read_text())
        cached = []
        for model in cache.get('models', []):
            if not isinstance(model, dict) or model.get('visibility') != 'list':
                continue
            name = model.get('slug')
            if not isinstance(name, str) or not name or name.startswith('-'):
                continue
            efforts = [entry.get('effort') for entry in model.get('supported_reasoning_levels', []) if isinstance(entry, dict) and entry.get('effort') in levels + ['ultra']]
            cached.append({'id': name, 'label': model.get('display_name') or name, 'efforts': efforts or levels[:]})
        if cached:
            codex = cached
            source = 'From the local Codex model cache; account access is checked when the tool runs.'
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return {'claude': {'models': claude, 'default_efforts': levels},
            'codex': {'models': codex, 'default_efforts': levels}, 'codex_source': source}


def validate_team(team):
    if not isinstance(team, dict) or not isinstance(team.get('roles'), dict) or set(team['roles']) != set(ROLES):
        raise ValueError('A team needs an observer, builder, and reviewer.')
    name = team.get('name', '')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError('Enter a team name between 1 and 80 characters.')
    result = {'name': name.strip(), 'roles': {}}
    catalogs = model_catalog()
    for role in ROLES:
        profile = team['roles'][role]
        if not isinstance(profile, dict) or profile.get('provider') not in PROVIDERS:
            raise ValueError(f'Choose Claude or Codex for the {role}.')
        model, instructions = profile.get('model', ''), profile.get('instructions', '')
        if not isinstance(model, str) or len(model) > 150 or model.strip().startswith('-') or any(c in model for c in '\r\n\x00'):
            raise ValueError('Model must be a single name, at most 150 characters.')
        if not isinstance(instructions, str) or len(instructions) > 4000:
            raise ValueError('Role instructions must be at most 4,000 characters.')
        effort = profile.get('effort', '')
        provider = profile['provider']
        if not isinstance(effort, str) or effort not in ['', 'low', 'medium', 'high', 'xhigh', 'max'] + (['ultra'] if provider == 'codex' else []):
            raise ValueError('Choose a supported effort level for this tool.')
        catalog = catalogs[provider]
        chosen = next((m for m in catalog['models'] if m['id'] == model.strip()), None)
        if effort and ((chosen is not None and effort not in chosen['efforts']) or (not model.strip() and effort not in catalog['default_efforts'])):
            raise ValueError('This model does not offer the selected effort level. Choose another effort or use the tool default.')
        result['roles'][role] = {'provider': provider, 'model': model.strip(), 'effort': effort, 'instructions': instructions.strip()}
    return result


def provider_command(provider, role, profile, workspace, output, schema_file, images=()):
    """Provider adapter boundary: role capabilities are set here, never by free text."""
    builder = role == 'builder'
    if provider == 'claude':
        tools = 'Read,Glob,Grep,Edit,Write,Bash' if builder else 'Read,Glob,Grep'
        args = [executable('claude'), '-p', '--output-format', 'stream-json', '--verbose',
                '--restricted', '--tools', tools, '--allowedTools', tools,
                '--permission-mode', 'dontAsk', '--strict-mcp-config',
                '--mcp-config', '{"mcpServers":{}}', '--setting-sources', '']
        if not builder:
            args += ['--json-schema', json.dumps(SCHEMA)]
    elif provider == 'codex':
        args = [executable('codex'), 'exec', '--json', '--sandbox', 'workspace-write' if builder else 'read-only',
                '--skip-git-repo-check', '-C', str(workspace), '-o', str(output)]
        if not builder:
            args += ['--output-schema', str(schema_file)]
    else:
        raise ValueError('Unsupported provider.')
    if profile['model']:
        args += ['--model', profile['model']]
    if profile.get('effort'):
        args += ['--effort', profile['effort']] if provider == 'claude' else ['-c', 'model_reasoning_effort=' + json.dumps(profile['effort'])]
    if images:
        if provider == 'claude':
            args += ['--input-format', 'stream-json']
        else:
            for image in images:args += ['--image', str(image)]
    if provider == 'codex':
        args += ['--', '-'] if images else ['-']
    return args


def tool_status():
    result = {}
    for name in ['codex', 'claude']:
        binary = executable(name)
        item = {'installed': bool(binary), 'signed_in': False, 'version': '', 'message': 'Not installed'}
        if binary:
            try:
                ver = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=10)
                item['version'] = ver.stdout.strip()
                args = [binary, 'login', 'status'] if name == 'codex' else [binary, 'auth', 'status']
                p = subprocess.run(args, capture_output=True, text=True, timeout=15)
                item['signed_in'] = p.returncode == 0
                if name == 'claude':
                    item['signed_in'] = json.loads(p.stdout).get('loggedIn', False)
                item['message'] = 'Ready' if item['signed_in'] else 'Sign in from your terminal'
            except (OSError, ValueError, subprocess.TimeoutExpired):
                item['message'] = 'Could not verify sign-in'
        result[name] = item
    return result


class ProviderCalls:
    """Run-owned CLI requests and structured response parsing."""

    def parse_review(self, result, text, provider):
        if result is None:
            try:
                result = json.loads(text.strip().removeprefix('```json').removesuffix('```').strip())
            except ValueError:
                raise RuntimeError(f'{provider} did not return a structured review. The response is saved; no approval was assumed.')
        self.app.validate_review(result)
        if self.current_role != 'observer' and result.get('questions'):
            raise ValueError('Only the Observer may request clarification.')
        self.emit(provider, 'review', result['summary'], review=result)
        return result

    def claude(self, prompt):
        role = self.current_role or 'reviewer'
        profile = self.info['team']['roles'][role]
        images = [self.app.saved_image_path(self.info,image['id']) for image in self.info.get('attachments',[])]
        args = self.app.provider_command('claude', role, profile, self.info['workspace'], '', '', images)
        if images:
            content = [{'type':'text','text':prompt}]
            content += [{'type':'image','source':{'type':'base64','media_type':image['mime'],'data':base64.b64encode(path.read_bytes()).decode('ascii')}} for image,path in zip(self.info['attachments'],images)]
            message = json.dumps({'type':'user','message':{'role':'user','content':content},'parent_tool_use_id':None})+'\n'
            result, text = self.launch('Claude', args, prompt, input_data=message)
        else:
            result, text = self.launch('Claude', args, prompt)
        if role != 'builder':
            return self.parse_review(result, text, 'Claude')
        if not text.strip():
            raise RuntimeError('Claude returned no implementation report.')
        (self.folder / f'builder-{self.info["round"]}{self.attempt_suffix()}.txt').write_text(text)
        return text

    def codex(self, prompt):
        role = self.current_role or 'builder'
        profile = self.info['team']['roles'][role]
        output = self.folder / (f'builder-{self.info["round"]}{self.attempt_suffix()}.txt' if role == 'builder' else f'{role}-{self.info["round"]}-turn-{len(self.info.get("turns", []))}-observation-{self.info.get("observation_round", 0)}{self.attempt_suffix()}.json')
        schema_file = self.folder / 'review-schema.json'
        if role != 'builder':
            schema_file.write_text(json.dumps(SCHEMA))
        args = self.app.provider_command('codex', role, profile, self.info['workspace'], output, schema_file, [self.app.saved_image_path(self.info,image['id']) for image in self.info.get('attachments',[])])
        _, text = self.launch('Codex', args, prompt)
        if role != 'builder':
            # Codex's final schema-constrained message is distinct from progress messages.
            if not output.exists():
                raise RuntimeError('Codex did not write its structured review result.')
            return self.parse_review(None, output.read_text(), 'Codex')
        if not text.strip():
            raise RuntimeError('Codex returned no implementation report. Check the saved provider events.')
        return text
