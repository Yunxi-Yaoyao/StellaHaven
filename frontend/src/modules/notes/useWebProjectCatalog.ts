import {computed, onScopeDispose, ref, watch, type Ref} from 'vue';
import {listProjectIdentities,getProject,type ProjectIdentity} from '../../api/webProjects';
import {listDetachedSources,type DetachedSource} from '../../api/detachedSources';
import type {FileProject} from '../../api/projectFiles';
import {auth} from '../home/auth';

/** Unknown is not an ordinary note: dispatch only after an authoritative read. */
export function useWebProjectCatalog(store: {workspaceId:string; userId:string}, active: Ref<boolean>) {
  const projects = ref<ProjectIdentity[]>([]);
  const manifests = ref<Record<string,FileProject>>({});
  const projectError = ref('');
  let projectSequence = 0;
  const detached = ref<DetachedSource[]>([]);
  const status = ref<'idle'|'loading'|'ready'|'error'>('idle');
  const error = ref('');
  const permitted = computed(() => active.value && !!auth.me?.id && store.userId === auth.me.id && !!store.workspaceId && !auth.suspended && !auth.sessionClosing);
  const scope = computed(() => JSON.stringify([auth.me?.id, auth.sessionGeneration, auth.requestEpoch, store.userId, store.workspaceId, permitted.value]));
  let sequence = 0, scopeGeneration = 0, disposed = false;
  let pending: Promise<boolean> | null = null;
  function capture() {
    const ownerScope = scope.value, generation = scopeGeneration;
    return () => !disposed && permitted.value && generation === scopeGeneration && ownerScope === scope.value;
  }
  function invalidate() {
    ++scopeGeneration;
    ++sequence;
    pending = null;
    projects.value = []; manifests.value = {}; projectError.value = ''; ++projectSequence;
    detached.value = [];
    status.value = 'idle';
    error.value = '';
  }
  async function load(force = false): Promise<boolean> {
    if (!permitted.value || disposed) return false;
    if (!force && pending) return pending;
    if (!force && status.value === 'ready') return true;
    const seq = ++sequence, current = capture(), workspace = store.workspaceId;
    status.value = 'loading'; error.value = '';
    const flight = (async () => {
      try {
        // Read project membership first, then detached identity: a committed
        // one-way detach cannot be absent from both snapshots in this order.
        const result = await listProjectIdentities(workspace);
        if (!current()) return false;
        // A same-scope refresh supersedes the data, not the caller's intent.
        // Join only a newer flight; identity changes remain a hard fence.
        if (seq !== sequence) return pending ?? status.value === 'ready';
        const sources = await listDetachedSources(workspace);
        if (!current()) return false;
        // A same-scope refresh supersedes the data, not the caller's intent.
        // Join only a newer flight; identity changes remain a hard fence.
        if (seq !== sequence) return pending ?? status.value === 'ready';
        if (!Array.isArray(result) || result.some(project => project.workspace_id !== workspace || typeof project.id !== 'string' || !Array.isArray(project.members) || !project.members.includes(project.id) || project.members.some(id=>typeof id!=='string'))) throw Error('目录响应不完整');
        const ids=result.flatMap(project=>project.members);
        if(new Set(ids).size!==ids.length) throw Error('项目身份冲突');
        if (!Array.isArray(sources) || sources.some(source => source.workspace_id !== workspace || source.kind !== 'detached-source')) throw Error('源码目录响应不完整');
        // Two requests can straddle a move. Ambiguous membership must not render Markdown.
        if (sources.some(source => result.some(project => project.members.includes(source.id)))) throw Error('源码目录已变化，请重试');
        projects.value = result;
        detached.value = sources;
        status.value = 'ready';
        return true;
      } catch {
        if (seq === sequence && current()) {
          status.value = 'error';
          error.value = '网页项目目录加载失败，为避免误编辑源码，暂未打开笔记。请重试。';
        }
        return false;
      } finally { if (seq === sequence) pending = null; }
    })();
    pending = flight;
    return flight;
  }
  watch(scope, invalidate, {flush:'sync'});
  onScopeDispose(() => { disposed = true; invalidate(); });
  function projectFor(id: string | null) {
    const identity=identityFor(id);
    return identity ? manifests.value[identity.id] ?? null : null;
  }
  function identityFor(id:string|null) {return projects.value.find(project=>id!==null&&project.members.includes(id))??null;}
  async function loadProject(id:string):Promise<FileProject|null> {
    const identity=identityFor(id), current=capture(), seq=++projectSequence, catalogSequence=sequence;
    projectError.value='';
    if(!identity || status.value!=='ready' || !current())return null;
    try {
      const project=await getProject(identity.id);
      if(!current() || seq!==projectSequence || catalogSequence!==sequence)return null;
      if(project.id!==identity.id || project.workspace_id!==store.workspaceId || !Array.isArray(project.files) || !(project.id===id || project.files.some(file=>file.id===id) || project.directories?.some(directory=>directory.id===id)))throw Error('项目成员已变化，请刷新目录');
      manifests.value[project.id]=project;return project;
    } catch(e) {
      if(current()&&seq===projectSequence)projectError.value='此网页项目无法打开：'+(e instanceof Error?e.message:'读取失败，请重试');
      return null;
    }
  }
  function assetFor(id:string|null){const identity=identityFor(id);return identity?.assets?.find(asset=>asset.file===id&&asset.root===identity.id)??null;}
  function detachedFor(id:string|null) {return detached.value.find(source=>source.id===id)??null;}
  return {status, error, projectError, permitted, capture, load, loadProject, identityFor, projectFor, assetFor, detachedFor};
}
