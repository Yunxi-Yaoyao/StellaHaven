"""Pure converter regressions: no application bootstrap, sockets, ORM or DB."""
import ast
import importlib.abc
import io
from pathlib import Path
import socket
import sys
import types
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='session', autouse=True)
def pure_converter():
    """Load the real converter and only unchanged, pure ZIP parser functions."""
    active = {'value': True}

    class NoBootstrap(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if active['value'] and (fullname.startswith('app.') or fullname == 'sqlalchemy'
                                    or fullname.startswith('sqlalchemy.')):
                raise RuntimeError('application/ORM import denied: ' + fullname)

    def audit(event, args):
        if active['value'] and event.startswith('socket.'):
            raise RuntimeError('network denied: ' + event)

    sys.addaudithook(audit)
    finder = NoBootstrap()
    sys.meta_path.insert(0, finder)
    saved = {}

    def install(name, module):
        saved[name] = sys.modules.get(name)
        sys.modules[name] = module

    def load(name, relative, pure_zip=False):
        path = ROOT / relative
        tree = ast.parse(path.read_text())
        if pure_zip:
            tree.body = [node for node in tree.body if (
                isinstance(node, ast.Import)
                or isinstance(node, ast.ImportFrom) and not (
                    node.module == 'sqlalchemy' or (node.module or '').startswith('app.'))
                or isinstance(node, ast.Assign) and all(
                    isinstance(t, ast.Name) and t.id.startswith('MAX_') for t in node.targets)
                or isinstance(node, ast.FunctionDef) and node.name in {'decode_body', 'parse_archive'}
            )]
        module = types.ModuleType(name)
        install(name, module)
        exec(compile(tree, str(path), 'exec'), module.__dict__)
        return module

    try:
        for name in ('app', 'app.services'):
            module = types.ModuleType(name)
            module.__path__ = []
            install(name, module)
        load('app.services.markdown_links', 'app/services/markdown_links.py')
        load('app.services.notes_zip', 'app/services/notes_zip.py', pure_zip=True)
        converter = load('app.services.html_note_conversion', 'app/services/html_note_conversion.py')
        yield converter
    finally:
        active['value'] = False
        sys.meta_path.remove(finder)
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_ordered_start_and_mixed_nested_lists(pure_converter):
    result = pure_converter.convert_html(
        '<ol start="3"><li>检查<ol start="7"><li>子一</li><li>子二'
        '<ul><li>细节</li></ul></li></ol></li><li>阅读</li></ol>')
    assert result['markdown'] == (
        '3. 检查\n\n   7. 子一\n   8. 子二\n\n      - 细节\n4. 阅读\n')
    assert result['losses'] == []


def test_multi_paragraph_item_preserves_preformatted_whitespace(pure_converter):
    code = '  first  \n\tsecond\n\n  \n'
    result = pure_converter.convert_html(
        '<ul><li><p>首段</p><p>次段 <strong>强调</strong></p>'
        '<pre><code>' + code + '</code></pre><p>末段</p></li><li>后项</li></ul>')
    markdown = result['markdown']
    assert markdown.startswith('- 首段\n\n')
    assert '\n\n  次段 **强调**\n\n' in markdown
    assert '  ```\n    first  \n  \tsecond\n\n    \n  ```' in markdown
    assert markdown.endswith('  末段\n- 后项\n')


@pytest.mark.parametrize('span', ['rowspan="2"', 'colspan="2"', 'rowspan="0"'])
def test_merged_cells_warn_about_changed_data_ownership(pure_converter, span):
    source = ('<table><tr><th>组别</th><th>数值</th></tr>'
              '<tr><td ' + span + '>同组</td><td>一</td></tr>'
              '<tr><td>二</td></tr></table>')
    result = pure_converter.convert_html(source)
    assert 'merged-table-cells' in result['losses']
    _, report = pure_converter.conversion_archive(source.encode(), 'merged.html')
    warning = '\n'.join(report['warnings'])
    assert 'merged.html' in warning
    assert '数据归属可能改变' in warning
    assert '保留原版网页' in warning


def test_plain_table_has_no_merged_cell_warning(pure_converter):
    source = '<table><tr><th>A</th></tr><tr><td rowspan="1" colspan="1">B</td></tr></table>'
    result = pure_converter.convert_html(source)
    assert result['markdown'] == '| A |\n| --- |\n| B |\n'
    assert result['losses'] == ['table-layout']
    _, report = pure_converter.conversion_archive(source.encode(), 'plain.html')
    assert not any('数据归属' in w for w in report['warnings'])


def test_truncated_preview_is_explicit_without_truncating_import(pure_converter):
    source = '<p>' + '前' * 12020 + '结束</p>'
    archive, report = pure_converter.conversion_archive(source.encode(), 'long.html')
    assert len(report['documents'][0]['markdown']) == 12000
    warning = '\n'.join(report['warnings'])
    assert 'long.html' in warning and '已显示前12000字符' in warning
    assert '完整内容' in warning and '导入后' in warning
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert z.read('long.md').decode() == pure_converter.convert_html(source)['markdown']
        assert '结束' in z.read('long.md').decode()
    _, short = pure_converter.conversion_archive(b'<p>short</p>', 'short.html')
    assert not any('已显示前' in w for w in short['warnings'])


def test_title_metadata_does_not_claim_to_rename_imported_note(pure_converter):
    source = '<title>网页标题</title><h1>正文标题</h1>'
    archive, report = pure_converter.conversion_archive(source.encode(), 'index.html')
    document = report['documents'][0]
    assert document['title'] == '网页标题'
    assert document['target'] == 'index.md'
    assert any('网页标题' in w and '按文件名' in w and 'index' in w for w in report['warnings'])
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert z.read('index.md').decode() == '# 正文标题\n'


@pytest.mark.parametrize('source', [
    '<ol start="-3"><li>A</li></ol>',
    '<ol start="1000000000"><li>A</li></ol>',
    '<ol start="999999999"><li>A</li><li>B</li></ol>',
    '<ol start="1_2"><li>A</li></ol>',
    '<ol reversed><li>A</li></ol>',
    '<ol><li value="8">A</li></ol>',
    '<ol type="a"><li>A</li></ol>',
])
def test_unrepresentable_numbering_warns_instead_of_silently_claiming_fidelity(pure_converter, source):
    result = pure_converter.convert_html(source)
    assert result['markdown'].startswith('1. A\n')
    assert 'list-numbering' in result['losses']
    _, report = pure_converter.conversion_archive(source.encode(), 'numbering.html')
    assert any('编号' in w and '保留原版网页' in w for w in report['warnings'])


@pytest.mark.parametrize('start,expected', [('0', 0), ('+003', 3), ('9', 9)])
def test_decimal_list_continuation_uses_marker_width(pure_converter, start, expected):
    result = pure_converter.convert_html(
        '<ul><li>外层<ol start="' + start + '"><li>A</li>'
        '<li><p>B</p><p>C</p></li></ol></li><li>末项</li></ul>')
    assert f'  {expected}. A\n  {expected + 1}. B' in result['markdown']
    assert '\n' + ' ' * (2 + len(str(expected + 1)) + 2) + 'C' in result['markdown']
    assert result['markdown'].endswith('- 末项\n')
    assert result['losses'] == []


def test_code_fence_never_strips_blank_lines_or_closes_on_source_backticks(pure_converter):
    code = '\n  ```literal  \n\tsecond\n\n   \n'
    result = pure_converter.convert_html('<pre><code>' + code + '</code></pre>')
    assert result['markdown'] == '````\n' + code + '````\n'


@pytest.mark.parametrize('url', [
    'javascript:alert(1)', '%6aavascript:alert(1)', 'java&#x73;cript:alert(1)',
    'data:text/html,attack', 'file:///etc/passwd', '//evil.invalid/x',
    'https://user:pass@evil.invalid/x', 'https://good.invalid\\@evil.invalid/',
    'java\nscript:alert(1)', 'ftp://evil.invalid/x',
])
def test_unsafe_url_rejection_is_unchanged(pure_converter, url):
    assert pure_converter.safe_url(url) is None


@pytest.mark.parametrize('url', ['https://example.invalid/a', 'http://example.invalid/',
                                 'mailto:user@example.invalid', '../images/a.png', '#section'])
def test_existing_safe_urls_still_work(pure_converter, url):
    assert pure_converter.safe_url(url) == url


@pytest.mark.parametrize('encoding', ['utf-8-sig', 'gb18030', 'utf-16'])
def test_inert_conversion_preserves_exact_original_html_bytes(pure_converter, encoding):
    source = ('<title>合成原档</title>\r\n<ol start="3"><li onclick="EVENT_SECRET()" style="color:red">内容'
              '<script>SCRIPT_SECRET()</script><style>STYLE_SECRET</style>'
              '<iframe>IFRAME_SECRET</iframe><form>FORM_SECRET</form>'
              '<a href="javascript:URL_SECRET()">链接</a><img src="data:text/html,IMAGE_SECRET">'
              '<pre>  code  \r\n\tline\r\n</pre></li></ol>')
    original = source.encode(encoding)
    archive, report = pure_converter.conversion_archive(original, 'original.html')
    assert set(report) == {'documents', 'converted_count', 'original_path', 'source_sha256', 'warnings'}
    assert set(report['documents'][0]) == {'source', 'target', 'title', 'losses', 'markdown'}
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        markdown = z.read('original.md').decode()
        preserved = z.read(report['original_path'])
    assert markdown.startswith('3. 内容')
    assert all(secret not in markdown for secret in ['SCRIPT_SECRET', 'STYLE_SECRET', 'IFRAME_SECRET',
                                                      'FORM_SECRET', 'URL_SECRET', 'IMAGE_SECRET', 'EVENT_SECRET'])
    assert not any(tag in markdown for tag in ['<script', '<iframe', '<form', 'onclick=', 'style='])
    assert set(report['documents'][0]['losses']) >= {'script', 'style', 'iframe', 'form', 'event-handler', 'layout'}
    with zipfile.ZipFile(io.BytesIO(preserved)) as z:
        assert z.namelist() == ['original.html']
        assert z.read('original.html') == original
    assert 'SCRIPT_SECRET' in source  # It was present in the preserved source, not removed beforehand.
    assert pure_converter.conversion_archive(original, 'original.html')[0] == archive


def test_zip_original_and_non_html_assets_are_byte_exact(pure_converter):
    files = {'web/index.html': b'<ol start="3"><li>A</li></ol>',
             'web/next.html': b'<p>B</p>', 'web/images/a.png': b'\x89PNG\x00fixture',
             'web/main.css': b'body{color:red}', 'web/main.js': b'ORIGINAL_SCRIPT_ONLY()'}
    original = pure_converter.pack(files)
    archive, report = pure_converter.conversion_archive(original, 'web.zip')
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert z.read(report['original_path']) == original
        assert z.read('web/images/a.png') == files['web/images/a.png']
        assert 'web/main.css' not in z.namelist() and 'web/main.js' not in z.namelist()
        assert z.read('web/index.md') == b'3. A\n'
    assert pure_converter.conversion_archive(original, 'web.zip')[0] == archive


@pytest.mark.parametrize('name', ['../escape.html', '/absolute.html', 'C:/drive.html', 'a\\bad.html'])
def test_unsafe_archive_paths_are_still_rejected(pure_converter, name):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        pure_converter.conversion_archive(pure_converter.pack({name: b'<p>bad</p>'}), 'bad.zip')
    assert exc.value.status_code == 400


def test_conflicts_and_relative_escape_are_still_rejected(pure_converter):
    from fastapi import HTTPException
    archive = pure_converter.pack({'index.html': b'<p>bad</p>', 'index.md': b'original markdown'})
    with pytest.raises(HTTPException) as exc:
        pure_converter.conversion_archive(archive, 'collision.zip')
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        pure_converter.conversion_archive(b'<a href="../outside.html">bad</a>', 'index.html')
    assert exc.value.status_code == 400


@pytest.mark.parametrize('source', ['x' * (5 * 1024 * 1024 + 1), '<br>' * 20001, '<div>' * 130],
                         ids=['size-budget', 'node-budget', 'depth-budget'])
def test_size_node_and_depth_budgets_are_still_rejected(pure_converter, source):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        pure_converter.convert_html(source)
    assert exc.value.status_code == 413


def test_guard_rejects_bootstrap_network_and_orm(pure_converter):
    import importlib
    for module in ['app.config', 'app.database', 'app.main', 'app.models.document', 'sqlalchemy']:
        with pytest.raises(RuntimeError, match='import denied'):
            importlib.import_module(module)
    with pytest.raises(RuntimeError, match='network denied'):
        socket.socket()
    with pytest.raises(RuntimeError, match='network denied'):
        socket.getaddrinfo('example.invalid', 443)
    assert not set(sys.modules).intersection({'app.config', 'app.database', 'app.main', 'sqlalchemy'})
