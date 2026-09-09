"""Bounded, path-addressed ZIP imports; no global title resolution."""
import io
import hashlib
import json
import mimetypes
import re
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from sqlalchemy import text
from app.models.document import Document
from app.models.attachment import Attachment
from app.models.document_link import DocumentLink
from app.models.config import AppConfig
import posixpath
import zipfile
import unicodedata
import zlib
from pathlib import PurePosixPath

from fastapi import HTTPException

MAX_COMPRESSED = 32 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_FILE = 25 * 1024 * 1024
MAX_ENTRIES = 2000
MAX_DEPTH = 32
MAX_PATH_BYTES = 1024
MAX_NAME_BYTES = 255


def decode_body(data, encoding):
    codecs = {'auto': ('utf-8-sig', 'gb18030'), 'utf8': ('utf-8-sig',),
              'utf-8': ('utf-8-sig',), 'bom': ('utf-8-sig',),
              'utf-8-sig': ('utf-8-sig',), 'gb18030': ('gb18030',)}
    if encoding not in codecs:
        raise HTTPException(400, 'Unsupported encoding')
    candidates = ('utf-16',) if encoding in ('auto', 'bom') and data.startswith((b'\xff\xfe', b'\xfe\xff')) else codecs[encoding]
    for codec in candidates:
        try:
            decoded = data.decode(codec).replace('\r\n', '\n').replace('\r', '\n')
            if '\0' in decoded:
                raise HTTPException(400, 'NUL in text document')
            return decoded
        except UnicodeDecodeError:
            pass
    raise HTTPException(400, 'Cannot decode Markdown')


def parse_archive(data, encoding='auto'):
    decode_body(b'', encoding)
    if len(data) > MAX_COMPRESSED:
        raise HTTPException(413, 'ZIP exceeds compressed limit')
    files, directories, seen = {}, set(), set()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if len(z.infolist()) > MAX_ENTRIES:
                raise HTTPException(413, 'Too many ZIP entries')
            total = 0
            for info in z.infolist():
                raw = info.orig_filename
                path = raw.rstrip('/')
                parts = path.split('/')
                if (len(parts) > MAX_DEPTH or len(path.encode('utf-8')) > MAX_PATH_BYTES
                        or any(len(p.encode('utf-8')) > MAX_NAME_BYTES for p in parts)):
                    raise HTTPException(413, 'ZIP path length or depth limit exceeded')
                if (not path or raw.startswith('/') or '\\' in raw or ':' in raw
                        or any(p in ('', '.', '..') for p in parts)
                        or any(ord(c) < 32 for c in raw)):
                    raise HTTPException(400, 'Unsafe ZIP path')
                normalized = unicodedata.normalize('NFC', path)
                if normalized in seen:
                    raise HTTPException(400, 'Duplicate ZIP path')
                seen.add(normalized)
                mode = (info.external_attr >> 16) & 0o170000
                if mode not in (0, 0o100000, 0o040000) or (mode == 0o040000 and not info.is_dir()):
                    raise HTTPException(400, 'Unsupported ZIP file type')
                if info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise HTTPException(400, 'Encrypted or unsupported ZIP')
                total += info.file_size
                if (info.file_size > MAX_FILE or total > MAX_TOTAL
                        or info.file_size > max(1, info.compress_size) * 200):
                    raise HTTPException(413, 'ZIP expansion limit exceeded')
                for i in range(1, len(parts)):
                    directories.add('/'.join(parts[:i]))
                if info.is_dir():
                    directories.add(path)
                else:
                    files[path] = z.read(info)
            if directories.intersection(files):
                raise HTTPException(400, 'ZIP file/directory collision')
            if len(files) + len(directories) > MAX_ENTRIES:
                raise HTTPException(413, 'Too many implied directories')
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, ValueError, zlib.error) as exc:
        raise HTTPException(400, 'Invalid ZIP archive') from exc
    entries, bodies, sources, readmes = [], {}, {}, set()
    for path in sorted(directories | set(files)):
        p = PurePosixPath(path)
        parent = str(p.parent) if str(p.parent) != '.' else None
        if path in directories:
            kind, title = 'directory', p.name
            bodies[path], sources[path] = '', path + '/README.md'
        elif p.suffix.lower() in ('.md', '.markdown', '.txt'):
            text = decode_body(files[path], encoding)
            if p.suffix.lower() == '.txt':
                import html
                text = html.escape(re.sub(r'([\\`*_{}\[\]()#+.!|~\-])', r'\\\1', text), quote=False).replace('\n', '  \n')
            if p.name.lower() == 'readme.md' and parent:
                if parent in readmes:
                    raise HTTPException(400, 'Multiple directory README files')
                readmes.add(parent)
                bodies[parent], sources[parent] = text, path
                continue
            kind, title = 'document', p.stem
            bodies[path], sources[path] = text, path
        else:
            kind, title = 'attachment', p.name
        entries.append(dict(path=path, title=title, kind=kind, parent_path=parent))
    if not bodies:
        raise HTTPException(400, 'ZIP must contain a Markdown document or directory')
    return entries, files, bodies, sources


def preview_archive(data, encoding='auto'):
    entries, files, bodies, sources = parse_archive(data, encoding)
    known = set(bodies) | set(sources.values()) | set(files)
    warnings = []
    for path, body in bodies.items():
        source = sources[path]
        def resolve(raw):
            try:
                url = urlsplit(raw)
            except ValueError:
                return raw
            if url.scheme or url.netloc or not url.path or url.path.startswith('/'):
                return raw
            target = posixpath.normpath(posixpath.join(posixpath.dirname(source), unquote(url.path)))
            if not any(p in known for p in (target, target + '.md', target + '.markdown', target + '.txt')):
                warnings.append(f'{source}: unresolved relative link {raw}')
            return raw
        rewrite_markdown(body, resolve)
    return {'entries': entries, 'warnings': list(dict.fromkeys(warnings)), 'counts': {
        'documents': sum(e['kind'] != 'attachment' for e in entries),
        'attachments': sum(e['kind'] == 'attachment' for e in entries)}}


from app.services.markdown_links import rewrite_markdown


def commit_archive(db, user, workspace_id, parent_id, import_id, data, encoding='auto'):
    from app.routers import attachment as storage
    entries, files, bodies, sources = parse_archive(data, encoding)
    if not bodies:
        raise HTTPException(400, 'ZIP must contain a Markdown document or directory')
    digest = hashlib.sha256(data).hexdigest()
    receipt_key = hashlib.sha256(f'notes-zip:{user.id}:{import_id}'.encode()).hexdigest()
    scope = [str(workspace_id), str(parent_id) if parent_id else None, digest, encoding]
    created_files = []
    try:
        # PostgreSQL transaction locks cover cross-process retries and sibling naming.
        for lock in (receipt_key, hashlib.sha256(str(workspace_id).encode()).hexdigest()):
            db.execute(text('SELECT pg_advisory_xact_lock(:key)'),
                       {'key': int.from_bytes(bytes.fromhex(lock[:16]), 'big', signed=True)})
        receipt = db.get(AppConfig, receipt_key)
        if receipt:
            saved = json.loads(receipt.value)
            if saved['scope'] != scope:
                raise HTTPException(409, 'import_id already used with different parameters')
            db.rollback()
            return {**saved['result'], 'reused': True}
        docs, links, attachments, warnings = {}, set(), {}, []
        occupied = {(d.parent_id, d.title) for d in db.query(Document).filter(
            Document.workspace_id == workspace_id, Document.deleted_at.is_(None)).all()}
        for entry in sorted(entries, key=lambda e: (e['path'].count('/'), e['path'])):
            if entry['kind'] == 'attachment':
                continue
            path = entry['path']
            parent = docs[entry['parent_path']].id if entry['parent_path'] else parent_id
            title, n = entry['title'], 2
            while (parent, title) in occupied:
                title = f"{entry['title']} ({n})"
                n += 1
            occupied.add((parent, title))
            doc = Document(id=uuid4(), workspace_id=workspace_id, parent_id=parent,
                title=title, file_path=path, content='', content_hash=hashlib.sha256(b'').hexdigest(),
                visibility='private', status='published', is_folder=False)
            db.add(doc)
            docs[path] = doc
            db.flush()
        aliases = dict(docs)
        for path, source in sources.items():
            aliases[source] = docs[path]
        attachment_paths = {e['path'] for e in entries if e['kind'] == 'attachment'}

        def attach(path, owner):
            key = (path, owner.id)
            if key not in attachments:
                payload = files[path]
                att = Attachment(id=uuid4(), doc_id=owner.id, filename=path,
                    mime=mimetypes.guess_type(path)[0] or 'application/octet-stream', size=len(payload))
                disk = storage.STORAGE / str(att.id)
                with disk.open('xb') as handle:
                    created_files.append(disk)
                    handle.write(payload)
                db.add(att)
                attachments[key] = att
            return '/attachments/' + str(attachments[key].id)

        for path, doc in docs.items():
            source = sources[path]
            def resolve(raw):
                try:
                    url = urlsplit(raw)
                except ValueError:
                    return raw
                if url.scheme or url.netloc or not url.path or url.path.startswith('/'):
                    return raw
                relative = unquote(url.path)
                target = posixpath.normpath(posixpath.join(posixpath.dirname(source), relative))
                suffix = ('#' + url.fragment) if url.fragment else ''
                found = next((aliases[p] for p in (target, target + '.md', target + '.markdown', target + '.txt') if p in aliases), None)
                if found is not None:
                    if found.id != doc.id:
                        links.add((doc.id, found.id))
                    return '/notes?doc=' + str(found.id) + suffix
                if target in attachment_paths:
                    return attach(target, doc) + suffix
                warnings.append(f'{source}: unresolved relative link {raw}')
                return raw
            doc.content = rewrite_markdown(bodies[path], resolve)
        # Unreferenced files stay discoverable and survive existing reference cleanup.
        for path in sorted(attachment_paths):
            if not any(p == path for p, _ in attachments):
                owner = docs.get(posixpath.dirname(path)) or next(iter(docs.values()))
                url = attach(path, owner)
                owner.content += f'\n\n[Attachment: {PurePosixPath(path).name.replace(chr(93), chr(92)+chr(93))}](<{url}>)\n'
        for doc in docs.values():
            doc.content_hash = hashlib.sha256(doc.content.encode()).hexdigest()
            doc.word_count = len(doc.content.split())
        for source, target in links:
            db.add(DocumentLink(source_id=source, target_id=target, link_type='ref'))
        result = {'documents': [{'id': str(d.id), 'title': d.title, 'path': p,
            'parent_id': str(d.parent_id) if d.parent_id else None} for p, d in docs.items()],
            'attachments': len(attachment_paths), 'warnings': list(dict.fromkeys(warnings)), 'reused': False}
        db.add(AppConfig(key=receipt_key, value=json.dumps({'scope': scope, 'result': result})))
        db.commit()
        return result
    except Exception:
        db.rollback()
        for path in created_files:
            path.unlink(missing_ok=True)
        raise
