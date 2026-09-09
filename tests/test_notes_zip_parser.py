import pytest
from fastapi import HTTPException
from app.services.notes_zip import parse_archive, preview_archive, rewrite_markdown
from tests.test_notes_zip import archive


@pytest.mark.parametrize('codec', ['utf-16', 'utf-16-be'])
def test_text_bom_literal(codec):
    raw = '# 中文\r\n[x](a.md) <script>&'
    data = raw.encode(codec)
    if codec == 'utf-16-be': data = b'\xfe\xff' + data
    entries, _, bodies, _ = parse_archive(archive([('plain.txt', data)]))
    assert entries[0]['kind'] == 'document'
    assert bodies['plain.txt'] == '\\# 中文  \n\\[x\\]\\(a\\.md\\) &lt;script&gt;&amp;'


@pytest.mark.parametrize('path', ['a/' * 40 + 'x.md', 'x' * 260 + '.md', 'a' * 200 + '/' + 'b' * 200 + '/' + 'c' * 200 + '/' + 'd' * 200 + '/' + 'e' * 230 + '/x.md'])
def test_path_bounds(path):
    with pytest.raises(HTTPException) as exc:
        parse_archive(archive([(path, 'x')]))
    assert exc.value.status_code == 413


def test_scanner_balanced_spaces_and_code():
    body = '[x](chapter (one).md) [y](<a b.md>) [z](chapter\\(two\\).md)\n`code\n[x](hidden.md)`\n`` literal ` [x](hidden.md) ``\n\\[escaped](hidden.md)'
    seen = []
    def resolve(path):
        seen.append(path)
        return '/resolved'
    output = rewrite_markdown(body, resolve)
    assert seen == ['chapter (one).md', 'a b.md', 'chapter(two).md']
    assert '[x](/resolved) [y](</resolved>) [z](/resolved)' in output
    assert '`code\n[x](hidden.md)`' in output
    assert '`` literal ` [x](hidden.md) ``' in output


def test_preview_missing_links():
    result = preview_archive(archive([('a.md', '[x](missing.md) [ok](b.md)'), ('b.md', 'b')]))
    assert result['warnings'] == ['a.md: unresolved relative link missing.md']
