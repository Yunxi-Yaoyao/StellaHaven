// Startup-only contracts from app/services/notes_preferences.py, notes_templates.py,
// routers/web_projects.py and routers/detached_sources.py. No generic API fallback.
// These legacy geometry/session scenarios model an already initialized template
// directory whose contents were removed; no template usage or project/source files.
export function createNotesStartupFixture(workspace) {
  const defaults = {revision:0,delete_action:'trash',ask_before_delete:true,font_size:16,line_height:1.8,read_width:800,code_line_numbers:false,code_wrap:true,directory_sort:'updated',hidden_folders:[]};
  const catalog = {root_id:'44444444-4444-4444-8444-444444444444',items:[],recent_ids:[]};
  return {
    respond(method, target, authenticated = true) {
      const url = new URL(target, 'http://fixture.invalid');
      const path = url.pathname;
      let json;
      if (method === 'GET' && path === '/notes-preferences' && !url.search) json = defaults;
      else if (method === 'POST' && path === `/notes-tools/templates/${workspace}/initialize` && !url.search) json = catalog;
      else if (method === 'GET' && path === `/notes-tools/templates/${workspace}` && !url.search) json = catalog;
      else if (method === 'GET' && path === `/web-projects/workspace/${workspace}/identities` && !url.search) json = [];
      else if (method === 'GET' && path === `/web-projects/workspace/${workspace}` && !url.search) json = [];
      else if (method === 'GET' && path === '/detached-sources' && url.searchParams.size === 1 && url.searchParams.get('workspace_id') === workspace) json = [];
      else return null;
      return authenticated ? {status:200,json:structuredClone(json)} : {status:401,json:{detail:'fixture unauthenticated'}};
    },
  };
}
