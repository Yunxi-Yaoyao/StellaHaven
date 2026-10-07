"""Template COPY/export helpers. Runtime delivery never reads these presets."""
import copy
import os
from app.services import builtin_injection as builtin
from app.services.integrations_injection import safe_json


def export_code(site, appearance=None, active=None, *, main_origin=None):
    main_origin = main_origin or os.getenv('STELLA_MAIN_ORIGIN', 'https://stella.xiya.live')
    builtin.gallery_head_loader(main_origin)  # exact deployment origin validation
    css, js = builtin.presets(site, appearance)
    # The old iframe was same-origin. Materialize the explicit parent boundary
    # in the editable code, not in a hidden runtime patch.
    js = js.replace('event.origin!==location.origin', 'event.origin!==' + safe_json(main_origin))
    old_origin = os.getenv('STELLA_BUILTIN_MAIN_ORIGIN', 'https://stella.xiya.live')
    js = js.replace('const mainOrigin=' + safe_json(old_origin), 'const mainOrigin=' + safe_json(main_origin))
    if active and active.get('enabled'):
        css += '\n' + active.get('css', '')
        js += '\n' + active.get('js', '')
    return dict(enabled=True, css=css, js=js, timing=(active or {}).get('timing', 'document_start'))


def catalog(*, main_origin=None):
    from app.services.openlist_access import READ_POST
    return copy.deepcopy([
        dict(id='openlist', name='OpenList', description='复制完整主题、简洁布局、背景、目录缓存和管理提示代码；可独立编辑与删除。', draft=dict(
            name='网盘', icon='drive', open_behavior='embedded',
            custom=export_code('drive', main_origin=main_origin),
            connection=dict(transport='proxy', auth_mode='original', header_name='Authorization', injection_delivery='proxy'),
            background='solid', request_policy=dict(management_prefixes=['/api/admin', '/api/fs/other'], read_post_paths=['/' + p for p in sorted(READ_POST)], protect_other_writes=True))),
        dict(id='immich', name='Immich', description='原域名直连，保留原站登录/OIDC；安装通用加载器后执行这里的代码。', draft=dict(
            name='图库', icon='image', open_behavior='embedded',
            custom=export_code('gallery', main_origin=main_origin),
            connection=dict(transport='direct', auth_mode='oidc', header_name='Authorization', injection_delivery='loader'),
            background='solid', request_policy=dict(management_prefixes=[], read_post_paths=[], protect_other_writes=False))),
    ])
