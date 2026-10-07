#!/usr/bin/env python3
"""Offline, explicit public fingerprint asset bundles for ordinary website modules.
No app imports, credentials, DB, DNS, remote fetching, nginx reload or deployment.
"""
import argparse
import gzip
import hashlib
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
import zlib
from urllib.parse import urlsplit

MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_FILES = 1024
MAX_MANIFEST = 2 * 1024 * 1024
HEX = re.compile(r'[0-9a-f]{64}')
ASSET = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]*-[A-Za-z0-9_-]{8,64}\.(js|css|woff2?|ttf|otf|png|jpe?g|webp|gif|avif|svg|ico)')
PRIVATE_PARTS = {'api', 'auth', 'private', 'download', 'downloads', 'attachments', 'attachment', 'd', 'p', 'dav', 'data', 'secrets'}
SECRET_NAME = re.compile(r'(?:^|[_.-])(?:secrets?|credentials?|password|access[_-]?token|refresh[_-]?token|api[_-]?key|client[_-]?secret)(?:[_.-]|$)', re.I)
SECRET_BYTES = re.compile(rb'-----BEGIN (?:[A-Z ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----|(?:access[_-]?token|refresh[_-]?token|api[_-]?key|client[_-]?secret|password|authorization)[\"\x27]?\s*[:=]\s*[\"\x27][A-Za-z0-9/+=_.-]{12,}[\"\x27]|\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b', re.I)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def trusted(path, exists=True):
    """Owner-controlled trees only: reject symlinks, hardlinks and writable parents."""
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'absolute non-traversing path required')
    for part in reversed((path, *path.parents)):
        if not part.exists() and not part.is_symlink():
            require(not exists or part != path, 'path missing')
            continue
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode), 'symlink rejected')
        require(info.st_uid in {0, os.geteuid()} and not info.st_mode & 0o022, 'untrusted owner/mode')
        require(stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
                'regular unlinked file or directory required')
    return path


def read(path, limit=MAX_FILE):
    path = trusted(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= limit,
                'regular bounded file required')
        data = stream.read(limit + 1)
    require(len(data) <= limit, 'file too large')
    return data


def load_json(raw):
    def unique(items):
        value = {}
        for key, item in items:
            require(key not in value, 'duplicate JSON key')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique)


def identity(module_id, origin):
    require(isinstance(module_id, str) and re.fullmatch(r'[0-9a-f]{32}', module_id), 'module ID invalid')
    require(isinstance(origin, str) and len(origin) <= 253, 'origin invalid')
    pattern = r'https://app-' + module_id + r'\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?::[1-9][0-9]{0,4})?'
    require(re.fullmatch(pattern, origin), 'exact isolated module HTTPS origin required')
    url = urlsplit(origin)
    require(url.port is None or (1 <= url.port <= 65535 and url.port != 443), 'noncanonical origin port')
    return url


def fingerprint(entry, limit=MAX_FILE):
    require(isinstance(entry, dict) and set(entry) == {'sha256', 'size'}, 'fingerprint fields')
    require(isinstance(entry['sha256'], str) and HEX.fullmatch(entry['sha256']), 'full SHA256 required')
    require(type(entry['size']) is int and 0 < entry['size'] <= limit, 'file size bound')


def validate_source(spec):
    require(isinstance(spec, dict) and set(spec) == {'schema', 'module_id', 'origin', 'asset_prefix', 'public', 'files'},
            'source manifest fields')
    require(spec['schema'] == 'stella-public-assets-source-v1' and spec['public'] is True,
            'explicit public source approval required')
    identity(spec['module_id'], spec['origin'])
    prefix = spec['asset_prefix']
    require(isinstance(prefix, str) and len(prefix) <= 256 and
            re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*(?:assets|static)/', prefix), 'asset prefix invalid')
    require(not PRIVATE_PARTS.intersection(prefix.lower().split('/')), 'private prefix rejected')
    files = spec['files']
    require(isinstance(files, dict) and 0 < len(files) <= MAX_FILES, 'asset count bound')
    for name, entry in files.items():
        require(isinstance(name, str) and len(name) <= 200 and ASSET.fullmatch(name) and
                not SECRET_NAME.search(name), 'public fingerprint basename required')
        fingerprint(entry)
    require(sum(e['size'] for e in files.values()) <= MAX_TOTAL, 'bundle byte bound')
    return spec


def validate_content(name, data):
    # Defense in depth, NOT a proof that arbitrary JS is public. Only a reviewed
    # vendor/public build with pinned SHA and explicit public approval is eligible.
    require(not SECRET_BYTES.search(data), 'credential-like content rejected')
    if name.endswith(('.js', '.css', '.svg')):
        text = data.decode('utf-8-sig').lstrip()
        require('\x00' not in text and (name.endswith('.svg') or not text.startswith('<')),
                'HTML or non-text asset rejected')
        if name.endswith('.svg'):
            require(re.match(r'(?:<\?xml[^>]+>\s*)?<svg(?:\s|>)', text), 'SVG signature invalid')
    else:
        ext = name.rsplit('.', 1)[-1]
        magic = {'woff': (b'wOFF',), 'woff2': (b'wOF2',), 'ttf': (b'\x00\x01\x00\x00',),
                 'otf': (b'OTTO',), 'png': (b'\x89PNG\r\n\x1a\n',),
                 'jpg': (b'\xff\xd8\xff',), 'jpeg': (b'\xff\xd8\xff',),
                 'gif': (b'GIF87a', b'GIF89a'), 'ico': (b'\x00\x00\x01\x00',)}
        if ext == 'webp':
            require(data.startswith(b'RIFF') and data[8:12] == b'WEBP', 'WebP signature invalid')
        elif ext == 'avif':
            require(data[4:8] == b'ftyp' and b'avif' in data[8:32], 'AVIF signature invalid')
        else:
            require(data.startswith(magic[ext]), 'binary asset signature invalid')


def publish_tree(out, files):
    """Create a NEW local artifact atomically; never overwrite a release or config."""
    out = trusted(out, exists=False)
    require(not out.exists(), 'output already exists')
    out.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    trusted(out.parent)
    tmp = Path(tempfile.mkdtemp(prefix='.public-assets-', dir=out.parent))
    try:
        for name, data in files.items():
            target = tmp / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            with target.open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            target.chmod(0o644)
        tmp.chmod(0o755)
        os.rename(tmp, out)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)


def build(spec_file, expected_spec_sha256, source, out):
    raw = read(spec_file, MAX_MANIFEST)
    require(sha(raw) == expected_spec_sha256, 'source manifest hash mismatch')
    spec = validate_source(load_json(raw))
    source, out = trusted(source), trusted(out, exists=False)
    require(source.is_dir() and not out.exists(), 'source missing or bundle already exists')
    files, compressed = {}, {}
    for name, entry in spec['files'].items():
        data = read(source / name)
        require(dict(sha256=sha(data), size=len(data)) == entry, 'asset fingerprint mismatch')
        validate_content(name, data)
        zipped = gzip.compress(data, compresslevel=6, mtime=0)
        files['public/' + name] = data
        files['public/' + name + '.gz'] = zipped
        compressed[name] = dict(sha256=sha(zipped), size=len(zipped))
    manifest: dict = dict(schema='stella-public-assets-bundle-v1', source=spec, gzip=compressed)
    manifest['version'] = sha(encoded(manifest))
    files['manifest.json'] = encoded(manifest)
    publish_tree(out, files)
    return manifest


def verify(bundle, expected_version, module_id, origin):
    bundle = trusted(bundle)
    manifest = load_json(read(bundle / 'manifest.json', MAX_MANIFEST))
    require(isinstance(manifest, dict) and set(manifest) == {'schema', 'source', 'gzip', 'version'} and
            manifest['schema'] == 'stella-public-assets-bundle-v1', 'bundle manifest fields')
    spec = validate_source(manifest['source'])
    core = {k: v for k, v in manifest.items() if k != 'version'}
    require(manifest['version'] == expected_version == sha(encoded(core)), 'bundle version mismatch')
    identity(module_id, origin)
    require(spec['module_id'] == module_id and spec['origin'] == origin, 'module/origin mismatch')
    require(isinstance(manifest['gzip'], dict) and set(manifest['gzip']) == set(spec['files']), 'gzip set mismatch')
    expected = {'manifest.json', 'public'} | {'public/' + n + suffix for n in spec['files'] for suffix in ('', '.gz')}
    actual = set()
    for path in bundle.rglob('*'):
        trusted(path)
        actual.add(path.relative_to(bundle).as_posix())
    require(expected == actual, 'bundle extra/missing files')
    for name, entry in spec['files'].items():
        data = read(bundle / 'public' / name)
        require(dict(sha256=sha(data), size=len(data)) == entry, 'asset fingerprint mismatch')
        validate_content(name, data)
        fingerprint(manifest['gzip'][name], MAX_FILE + 65536)
        zipped = read(bundle / 'public' / (name + '.gz'), MAX_FILE + 65536)
        require(dict(sha256=sha(zipped), size=len(zipped)) == manifest['gzip'][name], 'gzip fingerprint mismatch')
        # Bounded decode tolerates Python/zlib header/compressor variation without
        # accepting bombs, concatenated members, trailing bytes or truncated gzip.
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            decoded = decoder.decompress(zipped, len(data) + 1)
        except zlib.error:
            raise ValueError('gzip content mismatch') from None
        require(decoded == data and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
                'gzip content mismatch')
    return manifest


MIME = {'js': 'application/javascript', 'css': 'text/css', 'svg': 'image/svg+xml',
        'woff': 'font/woff', 'woff2': 'font/woff2', 'ttf': 'font/ttf', 'otf': 'font/otf',
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'webp': 'image/webp',
        'gif': 'image/gif', 'avif': 'image/avif', 'ico': 'image/x-icon'}
MAX_VERSIONS = 16
MAX_RETAINED_BYTES = 256 * 1024 * 1024
ROLLBACK = b'''# Operator rollback plan (NOT executed by this tool)
Before any deployment, back up the exact existing integration vhost and any
previous snippet to a private, root-owned transaction directory; record SHA256.
Install verified immutable release directories before changing configuration.
Never overwrite an existing release, use symlinks, or remove retained versions.
Include locations.conf ONLY in the reviewed TLS integration server block.
Leave the original authenticated location /, TLS, Origin/CSP, DNS pins and
primary-role guards unchanged. Run nginx -t before reload. Read back the exact
config and all public body hashes + gzip/cache headers after reload. Verify
anonymous HTML/API/download remain denied and ordinary owner access still works.
On failure: restore the exact backed-up config/snippet atomically, nginx -t,
reload, and re-read exact config and HTTP behavior. Unknown recovery is BLOCKED.
Keep all static release files. Rolling back edge mappings while newer tabs or
HTML are active may break lazy chunks; prefer a corrected union snippet. If
security requires removing the bypass, old assets return to authenticated
upstream; missing upstream versions are not guaranteed. No automatic GC.
'''


def target_path(root, module_id):
    require(isinstance(root, str) and len(root) <= 512 and
            re.fullmatch(r'/(?:[A-Za-z0-9_.-]+/)*' + module_id, root), 'target root invalid')
    require(not {'.', '..'}.intersection(root.split('/')), 'target traversal rejected')
    return Path(root)


def collect(manifests):
    require(0 < len(manifests) <= MAX_VERSIONS, 'retained version bound; never auto-prune')
    require(sum(sum(e['size'] for e in m['source']['files'].values()) for m in manifests) <= MAX_RETAINED_BYTES,
            'retained byte bound')
    assets = {}
    for m in sorted(manifests, key=lambda m: m['version']):
        spec = m['source']
        for name, entry in sorted(spec['files'].items()):
            uri = spec['asset_prefix'] + name
            if uri in assets:
                require(assets[uri]['sha256'] == entry['sha256'], 'same URL different bytes rejected')
            else:
                assets[uri] = dict(entry, relative=f"releases/{m['version']}/public/{name}", name=name)
    require(len(assets) <= MAX_FILES * 4, 'retained URL bound')
    return assets


def render(manifests, module_id, origin, root):
    url = identity(module_id, origin)
    root = target_path(root, module_id)
    assets = collect(manifests)
    reject = '@stella_public_asset_reject_' + module_id
    lines = ['# Exact approved public fingerprints only. No prefix/root caching.',
             '# Unknown URLs: original authenticated upstream. Missing/variants: 404 no-store.']
    for uri, entry in sorted(assets.items()):
        alias = str(root / entry['relative'])
        lines += [f'location = {uri} {{',
                  f'    if ($http_host != "{url.netloc}") {{ return 404; }}',
                  '    if ($scheme != https) { return 404; }',
                  f'    if ($request_uri != "{uri}") {{ return 404; }}',
                  '    if ($request_method !~ "^(GET|HEAD)$") { return 405; }',
                  f'    if (!-f {alias}) {{ return 404; }}',
                  f'    alias {alias};', '    disable_symlinks on;',
                  f'    error_page 403 404 405 = {reject};',
                  '    types { }', '    default_type ' + MIME[entry['name'].rsplit('.', 1)[-1]] + ';',
                  '    gzip off;', '    gzip_static on;', '    gzip_vary on;', '    gzip_proxied any;',
                  '    etag on;', '    expires off;', '    max_ranges 1;',
                  '    add_header Cache-Control "public, max-age=31536000, immutable";',
                  '    add_header X-Content-Type-Options nosniff;',
                  '    add_header X-Stella-Static-SHA256 "' + entry['sha256'] + '";',
                  '    access_log off;', '    log_not_found off;', '}']
    lines += [f'location {reject} {{', '    add_header Cache-Control "no-store" always;',
              '    access_log off;', '    return 404;', '}', '']
    return '\n'.join(lines).encode()


def bundle_reference(ref):
    require(isinstance(ref, dict) and set(ref) == {'path', 'version'}, 'bundle reference fields')
    require(isinstance(ref['version'], str) and HEX.fullmatch(ref['version']), 'full version required')
    return trusted(ref['path']), ref['version']


def stage(plan_file, expected_plan_sha256, out):
    raw = read(plan_file, MAX_MANIFEST)
    require(sha(raw) == expected_plan_sha256, 'plan hash mismatch')
    plan = load_json(raw)
    require(isinstance(plan, dict) and set(plan) == {'schema', 'module_id', 'origin', 'target_root', 'bundles', 'previous'} and
            plan['schema'] == 'stella-public-assets-plan-v1', 'stage plan fields')
    module, origin, target = plan['module_id'], plan['origin'], plan['target_root']
    identity(module, origin)
    target_path(target, module)
    require(isinstance(plan['bundles'], list) and 0 < len(plan['bundles']) <= MAX_VERSIONS, 'new bundle count bound')
    refs = [bundle_reference(item) for item in plan['bundles']]
    previous_version = None
    if plan['previous'] is not None:
        previous, previous_version = bundle_reference(plan['previous'])
        receipt = verify_stage(previous, previous_version, module, origin)
        require(receipt['target_root'] == target, 'retained target root mismatch')
        refs += [(previous / 'releases' / v, v) for v in receipt['versions']]
    manifests, paths = {}, {}
    for path, version in refs:
        manifests[version] = verify(path, version, module, origin)
        paths[version] = path
    values = list(manifests.values())
    snippet = render(values, module, origin, target)
    receipt = dict(schema='stella-public-assets-stage-v1', module_id=module, origin=origin, target_root=target,
                   versions=sorted(manifests), previous_stage_version=previous_version,
                   locations_sha256=sha(snippet), rollback_sha256=sha(ROLLBACK),
                   unknown_policy='unchanged-authenticated-upstream', missing_policy='404-no-cache')
    receipt['version'] = sha(encoded(receipt))
    files = {'stage.json': encoded(receipt), 'locations.conf': snippet, 'ROLLBACK.md': ROLLBACK}
    for version, path in sorted(paths.items()):
        for name in ['manifest.json'] + ['public/' + n + suffix for n in manifests[version]['source']['files'] for suffix in ('', '.gz')]:
            files['releases/' + version + '/' + name] = read(path / name, MAX_FILE + 65536)
    publish_tree(out, files)
    return receipt


def verify_stage(path, expected_version, module_id, origin):
    path = trusted(path)
    receipt = load_json(read(path / 'stage.json', MAX_MANIFEST))
    require(isinstance(receipt, dict) and set(receipt) == {'schema', 'module_id', 'origin', 'target_root', 'versions',
            'previous_stage_version', 'locations_sha256', 'rollback_sha256', 'unknown_policy', 'missing_policy', 'version'} and
            receipt['schema'] == 'stella-public-assets-stage-v1', 'stage receipt fields')
    core = {k: v for k, v in receipt.items() if k != 'version'}
    require(receipt['version'] == expected_version == sha(encoded(core)), 'stage version mismatch')
    identity(module_id, origin)
    require((receipt['module_id'], receipt['origin']) == (module_id, origin), 'stage module/origin mismatch')
    target_path(receipt['target_root'], module_id)
    versions = receipt['versions']
    require(isinstance(versions, list) and 0 < len(versions) <= MAX_VERSIONS and
            all(isinstance(v, str) and HEX.fullmatch(v) for v in versions) and versions == sorted(set(versions)), 'stage versions invalid')
    manifests = [verify(path / 'releases' / v, v, module_id, origin) for v in versions]
    require({p.name for p in path.iterdir()} == {'releases', 'stage.json', 'locations.conf', 'ROLLBACK.md'} and
            {p.name for p in (path / 'releases').iterdir()} == set(versions), 'stage extra/missing files')
    snippet = read(path / 'locations.conf', 16 * MAX_MANIFEST)
    require(sha(snippet) == receipt['locations_sha256'] and
            snippet == render(manifests, module_id, origin, receipt['target_root']), 'snippet mismatch')
    rollback = read(path / 'ROLLBACK.md')
    require(sha(rollback) == receipt['rollback_sha256'] and rollback == ROLLBACK, 'rollback plan mismatch')
    require(receipt['unknown_policy'] == 'unchanged-authenticated-upstream' and receipt['missing_policy'] == '404-no-cache',
            'stage policy mismatch')
    return receipt


def capture(port, paths_file, expected_paths_sha256, module_id, origin, prefix, out):
    """ONLY explicit paths on numeric 127.0.0.1, no credentials/DNS/redirect/crawl.
    Produces a candidate source manifest for review, not a deployment approval.
    """
    require(type(port) is int and 1 <= port <= 65535, 'loopback port invalid')
    raw = read(paths_file, MAX_MANIFEST)
    require(sha(raw) == expected_paths_sha256, 'path list hash mismatch')
    paths = load_json(raw)
    require(isinstance(paths, list) and 0 < len(paths) <= MAX_FILES and
            all(isinstance(p, str) for p in paths) and paths == sorted(set(paths)), 'sorted unique paths required')
    require(isinstance(prefix, str) and all(p.startswith(prefix) for p in paths), 'path outside asset prefix')
    names = [p[len(prefix):] for p in paths]
    spec: dict = dict(schema='stella-public-assets-source-v1', module_id=module_id, origin=origin,
                asset_prefix=prefix, public=True, files={n: dict(sha256='0' * 64, size=1) for n in names})
    validate_source(spec)  # All scope validation before any network or output write.
    trusted(out, exists=False)
    require(not Path(out).exists(), 'capture output already exists')
    files, total = {}, 0
    deadline = time.monotonic() + 60
    for path, name in zip(paths, names):
        require(time.monotonic() < deadline, 'capture deadline exceeded')
        conn = HTTPConnection('127.0.0.1', port, timeout=min(5, deadline - time.monotonic()))
        try:
            conn.request('GET', path, headers={'Accept-Encoding': 'identity', 'Connection': 'close'})
            response = conn.getresponse()
            require(response.status == 200, 'capture requires 200; redirects never followed')
            require(response.getheader('Set-Cookie') is None and response.getheader('Content-Disposition') is None,
                    'cookie/attachment response rejected')
            cache = response.getheader('Cache-Control', '').lower()
            vary = response.getheader('Vary', '').lower()
            require('private' not in cache and 'no-store' not in cache and 'cookie' not in vary and 'authorization' not in vary,
                    'private response rejected')
            mime = response.getheader('Content-Type', '').split(';')[0].strip().lower()
            expected = MIME[name.rsplit('.', 1)[-1]]
            require(mime == expected or (expected == 'application/javascript' and mime == 'text/javascript'), 'asset MIME mismatch')
            require(response.getheader('Content-Encoding', 'identity') == 'identity', 'unexpected content encoding')
            length = response.getheader('Content-Length', '')
            assert length is not None
            require(length is not None and length.isascii() and length.isdecimal() and 0 < int(length) <= MAX_FILE,
                    'bounded Content-Length required')
            require(total + int(length) <= MAX_TOTAL, 'capture total bound')
            data = bytearray()
            while True:
                require(time.monotonic() < deadline, 'capture deadline exceeded')
                part = response.read1(min(65536, MAX_FILE + 1 - len(data)))
                if not part:
                    break
                data.extend(part)
                require(len(data) <= MAX_FILE, 'capture file bound')
            data = bytes(data)
            require(len(data) == int(length), 'truncated response')
            validate_content(name, data)
            total += len(data)
            files['source/' + name] = data
            spec['files'][name] = dict(sha256=sha(data), size=len(data))
        finally:
            conn.close()
    validate_source(spec)
    files['source.json'] = encoded(spec)
    files['capture.json'] = encoded(dict(schema='stella-public-assets-capture-v1',
                                        transport=f'http://127.0.0.1:{port}', paths_sha256=sha(raw),
                                        source_sha256=sha(encoded(spec)), files=len(names), bytes=total,
                                        auth='none', redirects=False, recursive_discovery=False))
    publish_tree(out, files)
    return spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    capture_parser = commands.add_parser('capture', help='explicit read-only loopback HTTP; candidate manifest only')
    capture_parser.add_argument('--port', type=int, required=True)
    capture_parser.add_argument('--paths', type=Path, required=True)
    capture_parser.add_argument('--paths-sha256', required=True)
    capture_parser.add_argument('--asset-prefix', required=True)
    capture_parser.add_argument('--module-id', required=True)
    capture_parser.add_argument('--origin', required=True)
    capture_parser.add_argument('--out', type=Path, required=True)
    builder = commands.add_parser('build', help='offline approved manifest + local bytes -> immutable bundle')
    builder.add_argument('--spec', type=Path, required=True)
    builder.add_argument('--spec-sha256', required=True)
    builder.add_argument('--source', type=Path, required=True)
    builder.add_argument('--out', type=Path, required=True)
    stager = commands.add_parser('stage', help='offline retained union + nginx snippet + rollback plan; NO install/reload')
    stager.add_argument('--plan', type=Path, required=True)
    stager.add_argument('--plan-sha256', required=True)
    stager.add_argument('--out', type=Path, required=True)
    for action in ('verify', 'verify-stage'):
        verifier = commands.add_parser(action, help='offline content/scope verification against reviewed version')
        verifier.add_argument('--bundle', type=Path, required=True)
        verifier.add_argument('--version', required=True)
        verifier.add_argument('--module-id', required=True)
        verifier.add_argument('--origin', required=True)
    args = parser.parse_args()
    if args.action == 'capture':
        result = capture(args.port, args.paths, args.paths_sha256, args.module_id, args.origin, args.asset_prefix, args.out)
    elif args.action == 'build':
        result = build(args.spec, args.spec_sha256, args.source, args.out)
    elif args.action == 'stage':
        result = stage(args.plan, args.plan_sha256, args.out)
    else:
        action = verify if args.action == 'verify' else verify_stage
        result = action(args.bundle, args.version, args.module_id, args.origin)
    print(encoded(result).decode(), end='')


if __name__ == '__main__':
    main()
