import {it,expect} from 'vitest';
import {defaults} from './controller';
import {keepNavDraft,readNavDraft,forgetNavDraft} from './drafts';

it('retains only one owner-bound memory draft, copies reads and never exposes another owner',()=>{
 const data=defaults();data.preferences.title='private';
 keepNavDraft('A',{editor:data,baseline:defaults(),revision:1,mode:'settings',tab:'display',groupId:'',cardId:'',cardGroupId:'',uncertain:true});
 expect(readNavDraft('B')).toBeNull();
 const draft=readNavDraft('A')!;expect(draft.editor.preferences.title).toBe('private');
 draft.editor.preferences.title='changed';expect(readNavDraft('A')!.editor.preferences.title).toBe('private');
 forgetNavDraft('B');expect(readNavDraft('A')).not.toBeNull();
 forgetNavDraft('A');expect(readNavDraft('A')).toBeNull();
});
