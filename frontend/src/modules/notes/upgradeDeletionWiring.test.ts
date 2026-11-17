import {it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
const read=(p:string)=>readFileSync(new URL(p,import.meta.url),'utf8');
it('all deletion entry points converge on the Notes modal, not native confirm or admin UI',()=>{
 const page=read('./NotesPage.vue'),editor=read('./DocEditor.vue'),trash=read('./TrashPanel.vue'),settings=read('../settings/SettingsPage.vue');
 expect(page).toContain('<DeleteNoteDialog');expect(editor).not.toMatch(/\bconfirm\s*\(/);expect(editor).toContain('store.requestDelete(doc.value)');
 expect(trash).toContain('store.requestPurge(doc)');expect(trash).toContain('store.requestEmptyTrash');expect(trash).not.toContain('emptyConfirm');
 expect(page).toContain('<NotesSettings');expect(settings).toContain('/notes?settings=open');expect(settings).not.toContain('<NotesSettings');expect(settings).not.toContain('key:"notes"');expect(settings).not.toContain("import NotesSettings");expect(read('./DocList.vue')).toContain("emit('settings')");expect(read('./DocList.vue')).not.toContain('section=notes');
});
