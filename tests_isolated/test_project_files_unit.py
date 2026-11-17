"""No app/config/database imports. Real service functions, in-memory ORM adapter."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from uuid import UUID, uuid4
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code, self.detail = status_code, detail
class Column:
    def __eq__(self, other): return self
class Document:
    workspace_id = Column()
class AppConfig: pass
class Attachment: pass
class DB:
    def __init__(self, docs, configs, attachments=None):
        self.docs, self.configs, self.attachments = docs, configs, attachments or {}
        self.commits = 0
    def query(self, model): return self
    def filter(self, *args): return self
    def all(self): return list(self.docs.values())
    def get(self, model, ident):
        return (self.docs if model is Document else self.configs if model is AppConfig else self.attachments).get(ident)
    def commit(self): self.commits += 1
    def flush(self): pass

def load(db, owner, root, meta):
    path = ROOT / 'app/services/web_projects.py'
    tree = ast.parse(path.read_text())
    names = {'manifest', 'project_ancestor', 'guard_project_move', 'set_entry'}
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    for n in functions: n.decorator_list = []
    ns = dict(json=json, UUID=UUID, uid=lambda x: UUID(str(x)), Document=Document, AppConfig=AppConfig,
              Attachment=Attachment, HTTPException=HTTPException, PREFIX='web-project:',
              PurePosixPath=__import__('pathlib').PurePosixPath,
              lock_workspace=lambda *args: None,
              owned=lambda *args: (db.docs[root], json.loads(db.configs['web-project:'+str(root)].value)))
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), ns)
    return ns

class ProjectFiles(unittest.TestCase):
    def setUp(self):
        self.ws, self.owner, self.root, self.directory, self.file, self.other, self.outside = [uuid4() for _ in range(7)]
        def doc(id, parent, title, folder=False):
            return NS(id=id, parent_id=parent, title=title, is_folder=folder, workspace_id=self.ws,
                      deleted_at=None, updated_at=datetime(2026, 1, 1), content='汉字')
        self.docs = {d.id:d for d in [doc(self.root,None,'project',True),doc(self.directory,self.root,'assets',True),
                     doc(self.file,self.directory,'index.html'),doc(self.other,None,'other',True),doc(self.outside,None,'note')]}
        self.meta = {'owner_id':str(self.owner),'entry_file_id':str(self.file),
                     'files':{str(self.file):{'kind':'text','mime':'text/html'}}}
        self.configs = {'web-project:'+str(self.root):NS(value=json.dumps(self.meta)),
                        'web-project:'+str(self.other):NS(value=json.dumps({'owner_id':str(self.owner),'files':{},'entry_file_id':None}))}
        self.db = DB(self.docs, self.configs)
        self.ns = load(self.db,self.owner,self.root,self.meta)
    def test_legacy_directory_is_a_separate_manifest_member(self):
        result = self.ns['manifest'](self.db,self.owner,self.root)
        self.assertEqual(result.get('directories'), [{'id':str(self.directory),'path':'assets','kind':'directory'}])
        self.assertEqual([f['id'] for f in result['files']], [str(self.file)])
    def test_nested_project_directories_belong_only_to_their_own_manifest(self):
        self.docs[self.other].parent_id=self.root
        nested=uuid4();self.docs[nested]=NS(id=nested,parent_id=self.other,title='private',is_folder=True,workspace_id=self.ws,deleted_at=None)
        result=self.ns['manifest'](self.db,self.owner,self.root)
        self.assertEqual([d['id'] for d in result['directories']],[str(self.directory)])
    def test_size_is_current_utf8_or_attachment_bytes(self):
        result = self.ns['manifest'](self.db,self.owner,self.root)
        self.assertEqual(result['files'][0].get('size'), 6)
        aid=uuid4();self.meta['files'][str(self.file)]={'kind':'binary','mime':'application/octet-stream','attachment_id':str(aid)}
        self.configs['web-project:'+str(self.root)].value=json.dumps(self.meta)
        self.db.attachments[aid]=NS(doc_id=self.file,size=1234)
        result=self.ns['manifest'](self.db,self.owner,self.root)
        self.assertEqual(result['files'][0].get('size'),1234)
    def test_cross_boundary_rejected_without_mutation(self):
        guard=self.ns.get('guard_project_move');self.assertTrue(callable(guard),'transactional project move guard missing')
        # Text export is covered positively in test_detached_source_unit.py.
        for source,target in [(self.file,self.other),(self.directory,self.outside),(self.outside,self.root),(self.root,self.other)]:
            before=self.docs[source].parent_id
            with self.assertRaises(HTTPException) as error: guard(self.db,self.docs[source],target)
            self.assertEqual(error.exception.status_code,409)
            self.assertEqual(self.docs[source].parent_id,before)
        guard(self.db,self.docs[self.file],self.root)
        guard(self.db,self.docs[self.root],self.outside)
    def test_entry_change_checks_live_html_member_and_expected_entry(self):
        change=self.ns.get('set_entry');self.assertTrue(callable(change),'entry change service missing')
        with self.assertRaises(HTTPException): change(self.db,self.owner,self.root,self.outside,str(self.file))
        with self.assertRaises(HTTPException): change(self.db,self.owner,self.root,self.file,None)
        result=change(self.db,self.owner,self.root,self.file,str(self.file))
        self.assertEqual(result['entry'],'assets/index.html')
        self.assertEqual(self.db.commits,1)
    def test_trashed_directory_and_descendants_not_in_manifest(self):
        self.docs[self.directory].deleted_at=datetime(2026,1,1)
        result=self.ns['manifest'](self.db,self.owner,self.root)
        self.assertEqual(result.get('directories'),[])
        self.assertEqual(result['files'],[])

if __name__ == '__main__': unittest.main()
