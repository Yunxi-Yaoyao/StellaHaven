"""HTML conversion: parser only, no execution/network, exact original retained."""
import io,zipfile
import pytest
from fastapi import HTTPException

def test_content_conversion_keeps_structure_and_relative_images():
 from app.services.html_note_conversion import convert_html
 result=convert_html('<html><head><title>学习</title><style>body{color:red}</style></head><body><h1>标题</h1><p>正文 <strong>强调</strong></p><ul><li>一</li><li>二</li></ul><img src="../images/a.png" alt="图"><script>steal()</script></body></html>')
 assert result['title']=='学习'
 assert '# 标题' in result['markdown'] and '**强调**' in result['markdown']
 assert '- 一' in result['markdown'] and '- 二' in result['markdown']
 assert '![图](<../images/a.png>)' in result['markdown']
 assert 'steal' not in result['markdown'] and 'color:red' not in result['markdown']
 assert set(result['losses'])>={'script','style'}

def test_conversion_never_retains_executable_urls_or_html():
 from app.services.html_note_conversion import convert_html
 result=convert_html('<p onclick="x()">&lt;img src=x onerror=evil&gt;</p><a href="javascript:evil()">bad</a><img src="data:text/html;base64,AAAA"><iframe src="https://evil.invalid"></iframe>')
 assert '<img' not in result['markdown'] and 'javascript:' not in result['markdown'] and 'data:' not in result['markdown']
 assert 'bad' in result['markdown'] and 'iframe' in result['losses']

def test_archive_conversion_is_deterministic_and_retains_original():
 from app.services.html_note_conversion import conversion_archive
 raw=io.BytesIO()
 with zipfile.ZipFile(raw,'w') as z:
  z.writestr('chapters/index.html','<h1>标题</h1><img src="../images/p.png">')
  z.writestr('images/p.png',b'\x89PNG\r\n\x1a\nfixture')
 data=raw.getvalue();converted,report=conversion_archive(data,'lesson.zip')
 assert conversion_archive(data,'lesson.zip')[0]==converted
 with zipfile.ZipFile(io.BytesIO(converted)) as z:
  assert 'chapters/index.md' in z.namelist()
  assert '../images/p.png' in z.read('chapters/index.md').decode()
  assert z.read(report['original_path'])==data
 assert report['converted_count']==1

def test_archive_path_and_output_collision_fail_closed():
 from app.services.html_note_conversion import conversion_archive
 for names in [('index.html','index.md'),('../index.html',)]:
  raw=io.BytesIO()
  with zipfile.ZipFile(raw,'w') as z:
   for n in names:z.writestr(n,'<p>x</p>')
  with pytest.raises(HTTPException):conversion_archive(raw.getvalue(),'lesson.zip')
