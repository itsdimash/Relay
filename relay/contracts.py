"""Shared output contracts and workflow constants; no runtime state or I/O."""

TERMINAL = {'done', 'needs_attention', 'failed', 'stopped', 'interrupted'}

SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'status': {'type': 'string', 'enum': ['observed', 'approved', 'needs_changes']},
        'summary': {'type': 'string'},
        'overview': {'type': 'string'},
        'next_actions': {'type': 'array', 'items': {'type': 'string'}},
        'findings': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {**{k: {'type': 'string'} for k in ['id', 'file', 'problem', 'evidence', 'requested_change']}, 'priority': {'type': 'string', 'enum': ['critical', 'high', 'medium', 'low']}},
            'required': ['id', 'file', 'problem', 'evidence', 'requested_change', 'priority']}},
        'acceptance_checks': {'type': 'array', 'items': {'type': 'string'}},
        'questions': {'type': 'array', 'maxItems': 5, 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {'id': {'type': 'string'}, 'question': {'type': 'string'},
                           'options': {'type': 'array', 'maxItems': 5, 'items': {'type': 'string'}}},
            'required': ['id', 'question', 'options']}}},
    'required': ['status', 'summary', 'overview', 'next_actions', 'findings', 'acceptance_checks', 'questions']}

ROLES = ('observer', 'builder', 'reviewer')

PROVIDERS = ('claude', 'codex')

DEFAULT_TEAM = {'name': 'Claude reviews · Codex builds', 'roles': {
    role: {'provider': 'codex' if role == 'builder' else 'claude', 'model': '', 'effort': '', 'instructions': ''}
    for role in ROLES}}

TASK_MODES = ('observe', 'plan', 'build')

IMAGE_TYPES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}

MAX_IMAGE_BYTES = 4 * 1024 * 1024

class Stopped(Exception):
    pass

