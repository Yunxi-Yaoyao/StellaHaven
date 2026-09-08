"""Local, opt-in media derivatives. Originals and the attachment index are never changed.

GET is strictly read-only. A request schedules one bounded worker; per-source flock
is held from queue admission through completion across all NFS-sharing replicas.
A crashed worker releases its lock, so the next POST can retry immediately.
"""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

PREFIX = '/assets/homebg/'
PROFILE = 'v1-h264-23-27-webp-85-75'
SAFE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:jpe?g|png|webp|gif|mp4)', re.I)
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='homebg-media')
# ThreadPoolExecutor itself has an unbounded queue: explicitly bound admission.
_SLOTS = threading.BoundedSemaphore(32)


def source_path(root: Path, url: str) -> Path:
    if not url.startswith(PREFIX):
        raise ValueError('Expected a local homebg URL')
    name = url[len(PREFIX):]
    if not SAFE_NAME.fullmatch(name) or '..' in name:
        raise ValueError('Invalid background basename')
    root = root.resolve()
    source = root / name
    if source.is_symlink() or source.resolve().parent != root:
        raise ValueError('Background must be a regular local file')
    if not source.is_file():
        raise FileNotFoundError(name)
    return source


def _identity(source: Path) -> str:
    stat = source.stat()
    # Cheap GET fingerprint. Worker content-hashes outputs for immutable URLs.
    return hashlib.sha256(f'{PROFILE}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()


def _sidecar(source: Path) -> Path:
    return source.with_name('.' + source.name + '.media.json')


def _lock_path(source: Path) -> Path:
    return source.with_name('.' + source.name + '.media.lock')


def _base(url: str) -> dict:
    return dict(url=url, status='missing', poster=None, thumbnail=None,
                variants={'original': url})


def metadata(root: Path, url: str) -> dict:
    source = source_path(root, url)
    result = _base(url)
    try:
        saved = json.loads(_sidecar(source).read_text())
        if saved.get('_identity') != _identity(source):
            return result
        for key in ('status', 'poster', 'thumbnail', 'variants', 'error', 'width', 'height'):
            if key in saved:
                result[key] = saved[key]
        if result['status'] == 'ready':
            urls = [result['poster'], result['thumbnail'], *result['variants'].values()]
            for asset in filter(None, urls):
                try:
                    source_path(root, asset)
                except (ValueError, FileNotFoundError):
                    return _base(url)
        if result['status'] in ('queued', 'processing'):
            # No mutation, no lock file creation. An unlocked job was interrupted.
            try:
                with _lock_path(source).open('r+b') as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return result
                    fcntl.flock(lock, fcntl.LOCK_UN)
            except FileNotFoundError:
                pass
            result['status'] = 'missing'
    except (OSError, ValueError, TypeError):
        pass
    return result


def _save(source: Path, data: dict) -> None:
    target = _sidecar(source)
    temporary = target.with_name(target.name + '.' + uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def schedule(root: Path, url: str) -> dict:
    source = source_path(root, url)
    current = metadata(root, url)
    if current['status'] == 'ready':
        return current
    lock = _lock_path(source).open('a+b')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return metadata(root, url)
    # Recheck after lock acquisition (another replica might have just finished).
    current = metadata(root, url)
    if current['status'] == 'ready':
        lock.close()
        return current
    if not _SLOTS.acquire(blocking=False):
        lock.close()
        current.update(status='error', error='Media queue is full; retry later')
        return current
    data = _base(url)
    data.update(status='queued', _identity=_identity(source))
    try:
        _save(source, data)
        response = {k: v for k, v in data.items() if not k.startswith('_')}
        _EXECUTOR.submit(_worker, source, data, lock)
        return response
    except Exception:
        lock.close()
        _SLOTS.release()
        raise


def _input(source: Path) -> list[str]:
    # Force demuxers: a renamed playlist must not open URLs or other local files.
    demuxer = {'mp4': 'mov', 'gif': 'gif'}.get(source.suffix[1:].lower(), 'image2')
    return ['-protocol_whitelist', 'file,pipe', '-f', demuxer, '-i', str(source)]


def _probe(source: Path) -> dict:
    result = subprocess.run(['ffprobe', '-v', 'error', *_input(source),
                             '-show_streams', '-show_format', '-of', 'json'],
                            capture_output=True, check=True, timeout=300)
    return json.loads(result.stdout)


def _scale(longest: int, shortest: int | None = None, even: bool = False) -> str:
    factor = f'min(1,{longest}/max(iw,ih))'
    if shortest:
        factor = f'min({factor},{shortest}/min(iw,ih))'
    divisor = 2 if even else 1
    return (f"scale=w='max({divisor},trunc(iw*{factor}/{divisor})*{divisor})':"
            f"h='max({divisor},trunc(ih*{factor}/{divisor})*{divisor})',setsar=1")


def _convert(source: Path, target: Path, options: list[str]) -> None:
    temp = target.with_name('.' + uuid4().hex + target.suffix)
    try:
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-threads', '2',
                        '-filter_threads', '2', *_input(source), '-map', '0:v:0',
                        *options, '-threads', '2', str(temp)],
                       capture_output=True, check=True, timeout=300)
        if not temp.is_file() or not temp.stat().st_size:
            raise ValueError('Empty derivative')
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def _worker(source: Path, data: dict, lock) -> None:
    try:
        # Revalidate after queue delay (explicit deletion may have removed source).
        source_path(source.parent, data['url'])
        data.update(status='processing')
        _save(source, data)
        digest = hashlib.sha256(PROFILE.encode())
        with source.open('rb') as original:
            for chunk in iter(lambda: original.read(1024 * 1024), b''):
                digest.update(chunk)
        stem = 'media-' + digest.hexdigest()[:24]
        probe = _probe(source)
        stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        data.update(width=int(stream['width']), height=int(stream['height']))
        video = source.suffix.lower() == '.mp4'
        for name, limit in [('thumbnail', 480), ('poster', 1920)]:
            target = source.with_name(f'{stem}-{name}.webp')
            _convert(source, target, ['-vf', _scale(limit), '-frames:v', '1',
                                     '-c:v', 'libwebp', '-quality', '80', '-an'])
            data[name] = PREFIX + target.name
        # GIF is deliberately not flattened. Static previews are safe, but all
        # background quality selections retain the animated original.
        if source.suffix.lower() == '.gif':
            data['variants'].update(compressed1=data['url'], compressed2=data['url'])
            data['error'] = 'GIF compression unsupported; animated original retained'
        else:
            for name, longest, shortest, cap, crf, quality in [
                ('compressed1', 2560, 1440, 60, 23, 85),
                ('compressed2', 1920, 1080, 30, 27, 75),
            ]:
                target = source.with_name(f'{stem}-{name}' + ('.mp4' if video else '.webp'))
                if video:
                    fps = Fraction(stream.get('avg_frame_rate', '0/1'))
                    if fps <= 0:
                        fps = Fraction(stream.get('r_frame_rate', '0/1'))
                    if fps <= 0 or min(data['width'], data['height']) < 2:
                        raise ValueError('Unsupported video dimensions or frame rate')
                    options = ['-vf', _scale(longest, shortest, True) + f',fps={min(fps, cap)}',
                               '-c:v', 'libx264', '-preset', 'medium', '-crf', str(crf),
                               '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an']
                else:
                    options = ['-vf', _scale(longest), '-frames:v', '1',
                               '-c:v', 'libwebp', '-quality', str(quality), '-an']
                _convert(source, target, options)
                if target.stat().st_size < source.stat().st_size:
                    data['variants'][name] = PREFIX + target.name
                else:
                    target.unlink(missing_ok=True)
                    data['variants'][name] = data['url']
        if _identity(source) != data['_identity']:
            raise ValueError('Source changed during optimization; retry')
        data['status'] = 'ready'
    except Exception as exc:
        data.update(status='error', error=f'Media optimization failed ({type(exc).__name__}); original retained')
    finally:
        try:
            if source.is_file():
                _save(source, data)
        finally:
            lock.close()
            _SLOTS.release()
