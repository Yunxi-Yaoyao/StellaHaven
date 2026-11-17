"""Bounded, inert HTML -> Markdown conversion using the existing ZIP importer.

Never executes scripts, fetches URLs or rewrites originals. Exact source bytes
are retained as a ZIP attachment. Rendering/layout/interactive losses are explicit.
"""
import hashlib
import html
import io
import posixpath
import re
import zipfile
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit
from fastapi import HTTPException

VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
DROP={'script','style','iframe','object','embed','canvas','video','audio','form','button','input','select','textarea','svg'}

def escape(text):
    return html.escape(re.sub(r'([\\`*_{}\[\]<>|])',r'\\\1',text),quote=False)

def safe_url(raw):
    raw=(raw or '').strip()
    if not raw or any(ord(c)<32 for c in raw) or '\\' in raw:return None
    decoded=html.unescape(unquote(raw)).strip()
    try:
        u=urlsplit(decoded)
    except ValueError:
        return None
    if u.scheme and u.scheme.lower() not in {'https','http','mailto'}:return None
    if u.username or u.password or decoded.startswith('//'):return None
    return raw.replace('>','%3E').replace('<','%3C').replace(' ','%20')

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root=['root',{},[]];self.stack=[self.root];self.count=0;self.losses=set();self.title=''
    def handle_starttag(self,tag,attrs):
        self.count+=1
        if self.count>20000 or len(self.stack)>128:raise HTTPException(413,'HTML结构超过处理限制')
        attrs=dict(attrs)
        if any(k.startswith('on') for k in attrs):self.losses.add('event-handler')
        if 'style' in attrs or 'class' in attrs:self.losses.add('layout')
        n=[tag,attrs,[]];self.stack[-1][2].append(n)
        if tag not in VOID:self.stack.append(n)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        for index in range(len(self.stack)-1,0,-1):
            if self.stack[index][0]==tag:
                del self.stack[index:];break
    def handle_data(self,data):self.stack[-1][2].append(data)
    def plain(self,n):return n if isinstance(n,str) else ''.join(self.plain(c) for c in n[2])
    def render(self,n):
        if isinstance(n,str):return escape(re.sub(r'\s+',' ',n))
        tag,attrs,children=n
        if tag in DROP or tag=='base':self.losses.add(tag);return ''
        if tag=='title':self.title=self.plain(n).strip()[:160];return ''
        if tag in {'meta','link'}:
            if tag=='link':self.losses.add('external-layout')
            return ''
        if tag=='pre':
            code=self.plain(n);runs=[len(x) for x in re.findall(r'`+',code)];fence='`'*max(3,max(runs,default=0)+1)
            return '\n\n'+fence+'\n'+code+('' if code.endswith('\n') else '\n')+fence+'\n\n'
        if tag=='code':
            code=self.plain(n);fence='`'*max(1,max([len(x) for x in re.findall(r'`+',code)],default=0)+1)
            return fence+' '+code+' '+fence
        if tag in {'ol','ul'}:
            start=1
            if tag=='ol':
                raw=(attrs.get('start') or '1').strip()
                item_count=sum(not isinstance(c,str) and c[0]=='li' for c in children)
                # CommonMark decimal markers are nonnegative, at most nine digits.
                if re.fullmatch(r'\+?[0-9]{1,9}',raw):start=int(raw)
                else:self.losses.add('list-numbering')
                if start+max(0,item_count-1)>999999999:
                    start=1;self.losses.add('list-numbering')
                if ('reversed' in attrs or attrs.get('type','1')!='1'
                        or any(not isinstance(c,str) and c[0]=='li' and 'value' in c[1] for c in children)):
                    self.losses.add('list-numbering')
            items=[]
            for child in children:
                if isinstance(child,str) and not child.strip():continue
                if not isinstance(child,str) and child[0]=='li':
                    marker=f'{start}. ' if tag=='ol' else '- '
                    content=''.join(self.render(c) for c in child[2]).strip()
                    lines=content.split('\n')
                    items.append(marker+lines[0]+''.join(
                        '\n'+(' '*len(marker)+line if line else '') for line in lines[1:]))
                    start+=1
                else:
                    items.append(self.render(child).strip())
            return '\n\n'+'\n'.join(items)+'\n\n'
        content=''.join(self.render(c) for c in children)
        if re.fullmatch(r'h[1-6]',tag):return '\n\n'+'#'*int(tag[1])+' '+content.strip()+'\n\n'
        if tag in {'p','div','section','article','header','footer','dl'}:return '\n\n'+content.strip()+'\n\n'
        if tag=='li':return '\n- '+content.strip()+'\n'
        if tag in {'strong','b'}:return '**'+content+'**'
        if tag in {'em','i'}:return '*'+content+'*'
        if tag in {'s','del'}:return '~~'+content+'~~'
        if tag=='br':return '  \n'
        if tag=='hr':return '\n\n---\n\n'
        if tag=='blockquote':return '\n\n'+ '\n'.join('> '+line for line in content.strip().splitlines())+'\n\n'
        if tag=='a':
            url=safe_url(attrs.get('href'))
            if url:return '['+content.strip()+'](<'+url+'>)'
            self.losses.add('unsafe-or-empty-link');return content
        if tag=='img':
            url=safe_url(attrs.get('src'))
            if 'srcset' in attrs:self.losses.add('responsive-image')
            if url and not url.startswith('mailto:'):return '!['+escape(attrs.get('alt') or '')+'](<'+url+'>)'
            self.losses.add('unsupported-image');return ''
        if tag in {'td','th'}:
            if any(key in attrs and (attrs[key] or '').strip()!='1' for key in ('rowspan','colspan')):
                self.losses.add('merged-table-cells')
            return content.strip().replace('\n',' ')+' | '
        if tag=='tr':return '| '+content.strip()+'\n'
        if tag=='table':
            lines=[x.strip() for x in content.splitlines() if x.strip()]
            if lines:
                count=lines[0].count('|')-1
                lines.insert(1,'| '+' | '.join(['---']*max(1,count))+' |')
            self.losses.add('table-layout');return '\n\n'+'\n'.join(lines)+'\n\n'
        if tag not in {'root','html','head','body','span','thead','tbody','tfoot'}:self.losses.add(tag)
        return content

def convert_html(source):
    if len(source.encode('utf-8'))>5*1024*1024:raise HTTPException(413,'HTML超过5 MiB限制')
    p=Parser();p.feed(source);p.close();body=p.render(p.root)
    # Preserve preformatted blocks; blank-line normalization outside fences is not
    # attempted globally since it could modify code samples.
    return {'title':p.title,'markdown':body.strip()+'\n','losses':sorted(p.losses)}

def pack(files):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_STORED) as z:
        for name,data in sorted(files.items()):
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.external_attr=0o100600<<16
            z.writestr(info,data)
    return out.getvalue()

def conversion_archive(data, filename, encoding='auto'):
    from app.services.notes_zip import parse_archive, decode_body, MAX_FILE
    name=PurePosixPath(filename).name
    if len(data)>MAX_FILE:raise HTTPException(413,'保留原文件的HTML转换最多25 MiB')
    if name.lower().endswith('.zip'):
        _,files,_,_=parse_archive(data,encoding,require_notes=False);original=data
    elif name.lower().endswith(('.html','.htm')):
        if not name or any(c in name for c in ['\\',':','\x00']):raise HTTPException(400,'非法文件名')
        files={name:data};original=pack(files)
    else:raise HTTPException(415,'请选择HTML文件或包含HTML的ZIP')
    html_files=[p for p in files if PurePosixPath(p).suffix.lower() in {'.html','.htm'}]
    if not html_files:raise HTTPException(400,'未找到HTML文件')
    mapping={p:str(PurePosixPath(p).with_suffix('.md')) for p in html_files}
    if len(set(mapping.values()))!=len(mapping) or any(v in files for v in mapping.values()):raise HTTPException(409,'转换后的笔记名称与原文件冲突')
    converted={p:b for p,b in files.items() if p not in mapping and PurePosixPath(p).suffix.lower() not in {'.css','.js','.mjs'}}
    reports=[]
    warnings=['网页样式与脚本不转换；原始文件保留为ZIP附件。']
    from app.services.markdown_links import rewrite_markdown
    for p in html_files:
        r=convert_html(decode_body(files[p],encoding))
        if r['title']:
            warnings.append(f'{p}: 网页标题“{r["title"]}”仅作参考；导入标题仍按文件名/目录规则生成，重名时追加后缀。')
        if 'list-numbering' in r['losses']:
            warnings.append(f'{p}: 部分列表编号无法用Markdown准确表达，转换后编号可能改变，建议选择“保留原版网页”。')
        if 'merged-table-cells' in r['losses']:
            warnings.append(f'{p}: 检测到合并单元格（rowspan/colspan）；转换后数据归属可能改变，建议选择“保留原版网页”。')
        def resolve(raw):
            u=urlsplit(raw)
            if u.scheme or u.netloc or not u.path:return raw
            target=posixpath.normpath(posixpath.join(posixpath.dirname(p),unquote(u.path)))
            if target.startswith('../') or target=='..':raise HTTPException(400,'HTML相对引用超出归档范围')
            if target in mapping:
                return quote(posixpath.relpath(mapping[target],posixpath.dirname(p) or '.'),safe='/')+('#'+u.fragment if u.fragment else '')
            return raw
        if len(r['markdown'])>12000:
            warnings.append(f'{p}: 预览已显示前12000字符，未展示完整内容；完整内容请在导入后查看。')
        converted[mapping[p]]=rewrite_markdown(r['markdown'],resolve).encode()
        reports.append({'source':p,'target':mapping[p],'title':r['title'],'losses':r['losses'],'markdown':r['markdown'][:12000]})
    original_path='stella-original-'+hashlib.sha256(data).hexdigest()[:16]+'.zip'
    if original_path in files:raise HTTPException(409,'原文件存档名称冲突')
    converted[original_path]=original
    transformed=pack(converted)
    # Reuse unchanged import validation, attachment routing and transactional receipt.
    parse_archive(transformed,'utf-8')
    return transformed,{'documents':reports,'converted_count':len(reports),'original_path':original_path,'source_sha256':hashlib.sha256(data).hexdigest(),'warnings':warnings}
