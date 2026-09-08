"""Isolated media tests: .venv/bin/pytest --noconftest tests/test_homebg_media.py."""
import importlib
import importlib.util
import shutil
import subprocess
import time

import pytest


def media_module():
    assert importlib.util.find_spec('app.services.homebg_media'), 'media service is missing'
    return importlib.import_module('app.services.homebg_media')


def test_read_only_missing_and_safe_paths(tmp_path):
    media = media_module()
    (tmp_path / 'background.mp4').write_bytes(b'original')
    before = list(tmp_path.iterdir())
    result = media.metadata(tmp_path, '/assets/homebg/background.mp4')
    assert result == {'url': '/assets/homebg/background.mp4', 'status': 'missing',
                      'poster': None, 'thumbnail': None,
                      'variants': {'original': '/assets/homebg/background.mp4'}}
    assert list(tmp_path.iterdir()) == before
    for url in ['https://evil/a.mp4', '/assets/homebg/../a.mp4',
                '/assets/homebg/%2e%2e%2fa.mp4', '/assets/homebg/a.mp4?x=1',
                '/assets/homebg/index.json']:
        with pytest.raises(ValueError):
            media.metadata(tmp_path, url)
    with pytest.raises(FileNotFoundError):
        media.metadata(tmp_path, '/assets/homebg/absent.mp4')
    (tmp_path / 'link.mp4').symlink_to('/etc/passwd')
    with pytest.raises(ValueError):
        media.metadata(tmp_path, '/assets/homebg/link.mp4')


def ffmpeg(*args):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg and ffprobe required')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-threads', '2', *args],
                   check=True, capture_output=True, timeout=60)


def wait_ready(media, root, url):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        result = media.metadata(root, url)
        if result['status'] not in ('queued', 'processing'):
            return result
        time.sleep(.05)
    pytest.fail('worker did not finish')


@pytest.mark.parametrize('size,rate', [('320x180', 24), ('180x320', 75)])
def test_real_video_derivatives(tmp_path, size, rate):
    media = media_module()
    source = tmp_path / 'sample.mp4'
    ffmpeg('-f', 'lavfi', '-i', f'testsrc2=size={size}:rate={rate}',
           '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '0.8',
           '-c:v', 'libx264', '-threads', '2', '-crf', '0', '-c:a', 'aac', str(source))
    original = source.read_bytes()
    url = '/assets/homebg/sample.mp4'
    assert hasattr(media, 'schedule'), 'background scheduling is missing'
    assert media.schedule(tmp_path, url)['status'] == 'queued'
    result = wait_ready(media, tmp_path, url)
    assert result['status'] == 'ready', result
    assert source.read_bytes() == original
    for key, cap in [('compressed1', 60), ('compressed2', 30)]:
        variant = tmp_path / result['variants'][key].rsplit('/', 1)[1]
        assert variant != source
        assert variant.stat().st_size < len(original)
        probe = media._probe(variant)
        stream = probe['streams'][0]
        from fractions import Fraction
        assert float(Fraction(stream['avg_frame_rate'])) <= min(rate, cap) + .01
        assert stream['codec_name'] == 'h264'
        assert all(s['codec_type'] != 'audio' for s in probe['streams'])
        assert stream['width'] <= int(size.split('x')[0])
        assert stream['height'] <= int(size.split('x')[1])
        payload = variant.read_bytes()
        assert payload.index(b'moov') < payload.index(b'mdat')
    for key, maximum in [('poster', 1920), ('thumbnail', 480)]:
        image = tmp_path / result[key].rsplit('/', 1)[1]
        stream = media._probe(image)['streams'][0]
        assert max(stream['width'], stream['height']) <= maximum
    assert media.schedule(tmp_path, url)['status'] == 'ready'


@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import homebg
    monkeypatch.setattr(homebg, 'HOMEBG_DIR', tmp_path)
    monkeypatch.setattr(homebg, 'INDEX', tmp_path / 'index.json')
    app = FastAPI()
    app.include_router(homebg.router)
    with TestClient(app) as client:
        yield client, app, homebg


def test_public_metadata_authenticated_optimize_and_upload(api, tmp_path, monkeypatch):
    from types import SimpleNamespace
    client, app, homebg = api
    (tmp_path / 'test.mp4').write_bytes(b'not video')
    entries = [dict(id='own', file='test.mp4', name='test', ext='mp4', owner='42'),
               dict(id='other', file='test.mp4', name='test', ext='mp4', owner='99')]
    homebg._save(entries)
    url = '/assets/homebg/test.mp4'
    before = set(tmp_path.iterdir())
    assert client.get('/homebg/media', params={'url': url}).status_code == 200
    assert set(tmp_path.iterdir()) == before
    assert client.post('/homebg/own/optimize').status_code == 401
    app.dependency_overrides[homebg.current_user] = lambda: SimpleNamespace(id=42, is_admin=False)
    calls = []
    def scheduled(root, url):
        calls.append(url)
        return dict(url=url, status='queued', poster=None, thumbnail=None, variants={'original': url})
    monkeypatch.setattr(media_module(), 'schedule', scheduled)
    assert client.post('/homebg/other/optimize').status_code == 404
    assert client.post('/homebg/own/optimize').json()['status'] == 'queued'
    assert calls == [url]
    listing = client.get('/homebg/').json()
    assert len(listing) == 1 and listing[0]['media']['status'] == 'missing'
    uploaded = client.post('/homebg/upload', files={'file': ('new.png', b'png', 'image/png')})
    assert uploaded.status_code == 200
    assert uploaded.json()['media']['status'] == 'queued'
    assert calls[-1] == uploaded.json()['url']
    assert client.get('/homebg/media', params={'url': '/assets/homebg/../x.mp4'}).status_code == 400


@pytest.mark.parametrize('extension', ['png', 'gif'])
def test_real_static_and_animated_original(tmp_path, extension):
    media = media_module()
    source = tmp_path / ('image.' + extension)
    args = ['-f', 'lavfi', '-i', 'testsrc2=size=2600x100:rate=5']
    if extension == 'png':
        args += ['-frames:v', '1', '-c:v', 'png', '-threads', '2']
    else:
        args += ['-t', '0.4']
    ffmpeg(*args, str(source))
    original = source.read_bytes()
    url = '/assets/homebg/' + source.name
    media.schedule(tmp_path, url)
    result = wait_ready(media, tmp_path, url)
    assert result['status'] == 'ready', result
    assert source.read_bytes() == original
    if extension == 'gif':
        assert result['variants']['compressed1'] == url
        assert result['variants']['compressed2'] == url
        assert 'unsupported' in result['error']
    else:
        for key, limit in [('compressed1', 2560), ('compressed2', 1920)]:
            target = tmp_path / result['variants'][key].rsplit('/', 1)[1]
            assert target != source
            assert max(media._probe(target)['streams'][0][v] for v in ('width', 'height')) <= limit
    for key, limit in [('poster', 1920), ('thumbnail', 480)]:
        target = tmp_path / result[key].rsplit('/', 1)[1]
        assert max(media._probe(target)['streams'][0][v] for v in ('width', 'height')) <= limit


def test_real_failure_retry_and_crash_recovery(tmp_path):
    media = media_module()
    source = tmp_path / 'broken.mp4'
    source.write_bytes(b'not media')
    url = '/assets/homebg/broken.mp4'
    media.schedule(tmp_path, url)
    result = wait_ready(media, tmp_path, url)
    assert result['status'] == 'error'
    assert result['variants']['original'] == url
    assert source.read_bytes() == b'not media'
    media._save(source, dict(result, status='processing', _identity=media._identity(source)))
    before = media._sidecar(source).read_bytes()
    assert media.metadata(tmp_path, url)['status'] == 'missing'
    assert media._sidecar(source).read_bytes() == before
    assert media.schedule(tmp_path, url)['status'] == 'queued'
    assert wait_ready(media, tmp_path, url)['status'] == 'error'


def test_cross_process_lock_prevents_duplicate_and_crash_is_retryable(tmp_path):
    import sys
    media = media_module()
    source = tmp_path / 'locked.mp4'
    source.write_bytes(b'original')
    url = '/assets/homebg/locked.mp4'
    script = ('import fcntl,sys; f=open(sys.argv[1],"a+b"); '
              'fcntl.flock(f,fcntl.LOCK_EX); print("locked",flush=True); sys.stdin.read()')
    process = subprocess.Popen([sys.executable, '-c', script, str(media._lock_path(source))],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'locked'
        media._save(source, dict(media._base(url), status='processing', _identity=media._identity(source)))
        assert media.metadata(tmp_path, url)['status'] == 'processing'
        assert media.schedule(tmp_path, url)['status'] == 'processing'
    finally:
        process.communicate(timeout=5)
    assert media.metadata(tmp_path, url)['status'] == 'missing'


def test_missing_derivative_is_retryable(tmp_path):
    media = media_module()
    source = tmp_path / 'sample.png'
    source.write_bytes(b'original')
    url = '/assets/homebg/sample.png'
    media._save(source, dict(media._base(url), status='ready', poster='/assets/homebg/lost.webp',
                            _identity=media._identity(source)))
    assert media.metadata(tmp_path, url)['status'] == 'missing'


@pytest.mark.parametrize('size', ['2700x1500', '1500x2700'])
def test_real_video_resolution_bounds(tmp_path, size):
    media = media_module()
    source = tmp_path / 'large.mp4'
    ffmpeg('-f', 'lavfi', '-i', f'testsrc2=size={size}:rate=24', '-frames:v', '2',
           '-c:v', 'libx264', '-crf', '0', '-threads', '2', str(source))
    url = '/assets/homebg/large.mp4'
    media.schedule(tmp_path, url)
    result = wait_ready(media, tmp_path, url)
    assert result['status'] == 'ready', result
    for key, long_cap, short_cap in [('compressed1', 2560, 1440), ('compressed2', 1920, 1080)]:
        target = tmp_path / result['variants'][key].rsplit('/', 1)[1]
        assert target != source
        stream = media._probe(target)['streams'][0]
        assert max(stream['width'], stream['height']) <= long_cap
        assert min(stream['width'], stream['height']) <= short_cap
        width, height = map(int, size.split('x'))
        assert abs(stream['width'] / stream['height'] - width / height) < .01


def test_larger_derivative_uses_original(tmp_path, monkeypatch):
    media = media_module()
    source = tmp_path / 'tiny.png'
    ffmpeg('-f', 'lavfi', '-i', 'color=red:size=8x8', '-frames:v', '1',
           '-c:v', 'png', '-threads', '2', str(source))
    original = source.read_bytes()
    convert = media._convert
    def inflated(src, target, options):
        convert(src, target, options)
        if 'compressed' in target.name:
            with target.open('ab') as out:
                out.write(b'padding' * 1000)
    monkeypatch.setattr(media, '_convert', inflated)
    url = '/assets/homebg/tiny.png'
    media.schedule(tmp_path, url)
    result = wait_ready(media, tmp_path, url)
    assert result['status'] == 'ready', result
    assert result['variants'] == dict(original=url, compressed1=url, compressed2=url)
    assert source.read_bytes() == original
    assert not list(tmp_path.glob('*compressed*'))
