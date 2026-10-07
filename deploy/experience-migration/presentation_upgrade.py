"""Offline per-website presentation update. Never imports app/DB or writes files."""
from copy import deepcopy
import hashlib
import json


def fingerprint(module):
    return hashlib.sha256(json.dumps(module, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def prepare(module, *, expected_sha256, old_bridge, new_bridge):
    """CAS-bound, literal bridge update; independent user drafts fail closed."""
    if fingerprint(module) != expected_sha256:
        raise ValueError('website changed since approved snapshot')
    if module.get('adapter') != 'generic' or module.get('mode') != 'isolated_proxy':
        raise ValueError('not the approved generic isolated website')
    if not old_bridge or not new_bridge or old_bridge == new_bridge:
        raise ValueError('exact distinct bridge sources required')
    injection = module.get('injection', {})
    active, draft = injection.get('active'), injection.get('draft')
    if not isinstance(active, dict) or not active.get('enabled'):
        raise ValueError('active user code is disabled or absent')
    if active.get('js', '').count(old_bridge) != 1:
        raise ValueError('active source no longer matches the exact old bridge')
    if draft is not None:
        fields = ['enabled', 'css', 'js', 'timing', 'csp_policy']
        if any(draft.get(k) != active.get(k) for k in fields):
            raise ValueError('independent user draft must not be overwritten')
    result = deepcopy(module)
    result['background'] = 'home'
    result['keep_alive'] = True
    upgraded = deepcopy(active)
    upgraded['js'] = active['js'].replace(old_bridge, new_bridge, 1)
    upgraded['version'] = 'experience-' + hashlib.sha256(upgraded['js'].encode()).hexdigest()[:24]
    result['injection']['previous'] = deepcopy(active)
    result['injection']['active'] = upgraded
    if draft is not None:
        result['injection']['draft']['js'] = upgraded['js']
        if 'version' in result['injection']['draft']:
            result['injection']['draft']['version'] = upgraded['version']
    return result


def restore(current, *, expected_upgraded_sha256, before):
    if fingerprint(current) != expected_upgraded_sha256:
        raise ValueError('website changed since upgrade; do not clobber later edits')
    if current.get('id') != before.get('id'):
        raise ValueError('wrong website snapshot')
    return deepcopy(before)
