import { defineStore } from 'pinia';
import { ref, watch } from 'vue';
import { auth } from '../modules/home/auth';
import { getNotesPreferences, patchNotesPreferences, type NotesPreferences, type NotesPreferenceFields } from '../api/notes';
import { ApiError } from '../api/client';

export const useNotesPreferencesStore = defineStore('notes-preferences', () => {
  const owner = ref('');
  const saved = ref<NotesPreferences | null>(null);
  const draft = ref<NotesPreferenceFields>({ delete_action: 'trash', ask_before_delete: true });
  const status = ref<'idle'|'loading'|'saving'|'saved'|'error'|'conflict'|'verify'>('idle');
  const error = ref('');
  const busy = ref(false);
  let epoch = 0;
  let pending: NotesPreferenceFields | null = null;
  let flight: Promise<boolean> | null = null;
  let saving: Promise<boolean> | null = null;
  function bindOwner(id: string, invalidate = false) {
    if (owner.value === id && !invalidate) return;
    ++epoch; owner.value = id; saved.value = null; pending = null; flight = null; saving = null;
    draft.value = { delete_action: 'trash', ask_before_delete: true };
    status.value = 'idle'; error.value = ''; busy.value = false;
  }
  watch(() => [auth.me?.id, auth.suspended, auth.sessionClosing, auth.sessionGeneration, auth.requestEpoch], () => {
    bindOwner(auth.suspended || auth.sessionClosing ? '' : auth.me?.id ?? '', true);
  }, {flush:'sync'});
  function load(): Promise<boolean> {
    // New dialogs/settings join the whole write + verification transaction.
    return saving ?? read();
  }
  async function read(): Promise<boolean> {
    if (!owner.value || (busy.value && status.value === 'saving')) return false;
    if (flight) return flight;
    const token = epoch;
    busy.value = true; status.value = pending ? 'verify' : 'loading'; error.value = '';
    flight = (async () => {
      try {
        const result = await getNotesPreferences();
        if (token !== epoch) return false;
        if (!result || !Number.isSafeInteger(result.revision) || result.revision < 0 || !['trash','permanent'].includes(result.delete_action) || typeof result.ask_before_delete !== 'boolean') throw new Error('Invalid notes preferences');
        saved.value = result;
        if (pending && Object.entries(pending).some(([key, value]) => JSON.stringify(result[key as keyof NotesPreferenceFields]) !== JSON.stringify(value))) {
          status.value = 'conflict'; error.value = '服务器设置与本次选择不同。已保留选择，请核对后重新应用，或使用服务器设置。';
          return false;
        }
        const {revision: _revision, ...fields} = result;
        draft.value = fields;
        pending = null; status.value = 'saved'; return true;
      } catch {
        if (token === epoch) { status.value = pending ? 'verify' : 'error'; error.value = pending ? '尚未确认偏好是否保存，请重新读取；不会重复删除笔记。' : '笔记偏好读取失败，请重试。未使用默认值覆盖服务器。'; }
        return false;
      } finally { if (token === epoch) { busy.value = false; flight = null; } }
    })();
    return flight;
  }
  function save(fields: Partial<NotesPreferenceFields>): Promise<boolean> {
    if (saving) return Promise.resolve(false);
    const token = epoch;
    const result = saveFields(fields);
    saving = result;
    void result.finally(() => { if (token === epoch) saving = null; });
    return result;
  }
  async function saveFields(fields: Partial<NotesPreferenceFields>): Promise<boolean> {
    const token = epoch;
    // A background refresh must not discard an explicit choice made in a dialog.
    // Merge only after it settles so unrelated server fields/revision stay current.
    if (flight) await flight;
    if (token !== epoch || !owner.value || !saved.value || busy.value || status.value === 'verify') return false;
    draft.value = { ...draft.value, ...fields };
    pending = { ...draft.value };
    busy.value = true; status.value = 'saving'; error.value = '';
    try {
      await patchNotesPreferences({ expected_revision: saved.value.revision, ...pending });
    } catch (e) {
      if (token !== epoch) return false;
      if (e instanceof ApiError && e.status === 409) {
        busy.value = false;
        return read();
      }
      // An uncertain PATCH is reconciled with GET, never blindly resent.
      status.value = 'verify'; error.value = '保存结果尚未确认，请重新读取。'; busy.value = false;
      return false;
    }
    if (token !== epoch) return false;
    busy.value = false;
    return read();
  }
  function useServer() {
    if (!saved.value || busy.value || status.value !== 'conflict') return;
    pending = null;
    const {revision: _revision, ...fields} = saved.value;
    draft.value = fields;
    status.value = 'saved'; error.value = '';
  }
  return {owner,saved,draft,status,error,busy,bindOwner,load,save,useServer};
});
