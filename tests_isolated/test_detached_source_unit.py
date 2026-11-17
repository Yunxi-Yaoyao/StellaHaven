"""Source AST + memory adapter only; never imports app config or opens a database."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from uuid import uuid4, UUID
from test_project_files_unit import DB, Document, Attachment, HTTPException

ROOT=Path(__file__).resolve().parents[1]
class AppConfig:
    def __init__(self, **kwargs): self.__dict__.update(kwargs)
class Memory(DB):
    def get(self, model, ident):
        return (self.docs if model is Document else self.configs if model is AppConfig else self.attachments).get(ident)
    def add(self, row): self.configs[row.key]=row

def functions(path, names, ns):
    nodes=[n for n in ast.parse((ROOT/path).read_text()).body if isinstance(n,ast.FunctionDef) and n.name in names]
    for n in nodes:n.decorator_list=[]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),ns)

class Detached(unittest.TestCase):
    def setUp(self):
        self.root,self.file,self.ws,self.owner,self.other=[uuid4() for _ in range(5)]
        self.doc=NS(id=self.file,parent_id=self.root,is_folder=False,workspace_id=self.ws,visibility='private',content='<script>const x="**raw**";</script>\r\n',deleted_at=None)
        root=NS(id=self.root,parent_id=None,is_folder=True,workspace_id=self.ws)
        self.meta={'owner_id':str(self.owner),'files':{str(self.file):{'kind':'text','mime':'text/html','original_path':'index.html'}},'entry_file_id':str(self.file)}
        self.db=Memory({self.root:root,self.file:self.doc},{'web-project:'+str(self.root):AppConfig(value=json.dumps(self.meta))})
        self.ns=dict(json=json,Document=Document,AppConfig=AppConfig,PREFIX='web-project:',DETACHED_PREFIX='web-project-source:',HTTPException=HTTPException,uid=lambda x:UUID(str(x)))
        functions('app/services/web_projects.py',{'project_ancestor','guard_project_move'},self.ns)
    def test_text_detach_persists_identity_and_revokes_old_membership(self):
        original=self.doc.content
        self.ns['guard_project_move'](self.db,self.doc,None)
        record=json.loads(self.db.configs['web-project-source:'+str(self.file)].value)
        self.assertEqual(record['owner_id'],str(self.owner));self.assertEqual(record['kind'],'text')
        self.assertEqual(record['mime'],'text/html')
        meta=json.loads(self.db.configs['web-project:'+str(self.root)].value)
        self.assertNotIn(str(self.file),meta['files']);self.assertIsNone(meta['entry_file_id'])
        self.assertEqual(self.doc.content,original);self.assertEqual(self.doc.visibility,'private')
    def test_failed_bulk_move_does_not_export_a_text_parent_with_children(self):
        child=uuid4();self.db.docs[child]=NS(id=child,parent_id=self.file)
        with self.assertRaises(HTTPException):self.ns['guard_project_move'](self.db,self.doc,None)
        self.assertNotIn('web-project-source:'+str(self.file),self.db.configs)
    def test_detached_can_move_between_ordinary_parents_but_not_back_into_project(self):
        self.ns['guard_project_move'](self.db,self.doc,None);self.doc.parent_id=None
        self.db.docs[self.other]=NS(id=self.other,parent_id=None,is_folder=True)
        self.ns['guard_project_move'](self.db,self.doc,self.other)
        with self.assertRaises(HTTPException):self.ns['guard_project_move'](self.db,self.doc,self.root)
    def test_detached_write_policy_keeps_raw_private_identity(self):
        functions('app/services/web_projects.py',{'guard_detached_update'},self.ns)
        guard=self.ns.get('guard_detached_update')
        self.assertTrue(callable(guard),'detached write policy missing')
        self.ns['guard_project_move'](self.db,self.doc,None)
        for fields,source_edit in [({'visibility':'public'},False),({'is_folder':True},False),({'content':'converted'},False)]:
            data=NS(**fields,model_fields_set=set(fields))
            with self.assertRaises(HTTPException):guard(self.db,self.doc,data,source_edit=source_edit)
        guard(self.db,self.doc,NS(content='raw',model_fields_set={'content'}),source_edit=True)
        guard(self.db,self.doc,NS(title='renamed',model_fields_set={'title'}))
    def test_owner_scoped_read_survives_rename_and_denies_trash(self):
        path=ROOT/'app/services/detached_sources.py'
        self.assertTrue(path.exists(),'detached source service missing')
        class Workspace:pass
        self.ns.update(Workspace=Workspace)
        functions('app/services/detached_sources.py',{'owned','projection'},self.ns)
        self.ns['guard_project_move'](self.db,self.doc,None)
        self.db.attachments[self.ws]=NS(user_id=self.owner)
        self.doc.title='renamed-without-extension';self.doc.updated_at=__import__('datetime').datetime(2026,1,1)
        doc,meta=self.ns['owned'](self.db,self.owner,self.file)
        result=self.ns['projection'](doc,meta,True)
        self.assertEqual(result['content'],self.doc.content);self.assertEqual(result['mime'],'text/html')
        with self.assertRaises(HTTPException):self.ns['owned'](self.db,uuid4(),self.file)
        self.doc.deleted_at=True
        with self.assertRaises(HTTPException):self.ns['owned'](self.db,self.owner,self.file)
    def test_implicit_reparenting_uses_the_same_identity_transfer(self):
        tree=ast.parse((ROOT/'app/services/document.py').read_text())
        for name in ('delete_document','restore_document','_delete_set'):
            function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertTrue(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='guard_project_move' for n in ast.walk(function)),name+' bypasses source identity transfer')
    def test_binary_rejected_without_changing_metadata(self):
        self.meta['files'][str(self.file)]['kind']='binary'
        row=self.db.configs['web-project:'+str(self.root)];row.value=json.dumps(self.meta);before=row.value
        with self.assertRaises(HTTPException):self.ns['guard_project_move'](self.db,self.doc,None)
        self.assertEqual(row.value,before);self.assertNotIn('web-project-source:'+str(self.file),self.db.configs)
    def test_cross_project_still_rejected(self):
        self.db.docs[self.other]=NS(id=self.other,parent_id=None,is_folder=True)
        self.db.configs['web-project:'+str(self.other)]=AppConfig(value='{}')
        with self.assertRaises(HTTPException):self.ns['guard_project_move'](self.db,self.doc,self.other)
        self.assertIn(str(self.file),json.loads(self.db.configs['web-project:'+str(self.root)].value)['files'])

if __name__=='__main__':unittest.main()
