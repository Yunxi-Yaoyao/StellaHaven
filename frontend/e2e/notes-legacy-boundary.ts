import type {Page} from '@playwright/test';
// Applied LAST, ahead of each historical fixture: broad old handlers may only
// see these enumerated contracts. Unknown API and outside traffic fail the test.
export async function installLegacyBoundary(page:Page){
 const origin='http://127.0.0.1:15186';
 const documents='doc-a|source|first|second|existing|parent|child|child-a|child-b|grandchild|new-child|flat|new|created-\\d+|new-\\d+';
 const permitted=[
  ['GET',/^\/auth\/(me|security|sessions|avatars|email-service|sessions\/history)$/],
  ['POST',/^\/auth\/(refresh|activity|logout|login)$/],
  ['GET',/^\/workspaces\/(ws-a)?$/],
  ['GET',/^\/(tags|doc-tags|attachments|document-links)\/$/],
  ['POST',/^\/doc-tags\/$/],['DELETE',/^\/doc-tags\/$/],
  ['GET',/^\/documents\/(recent|trash)?$/],['POST',/^\/documents\/$/],
  ['GET',new RegExp(`^/documents/(${documents})(/backlinks)?$`)],
  ['PUT',/^\/documents\/doc-a$/],
  ['POST',/^\/documents\/import\/(finalize|zip|zip\/preview)$/],
  ['POST',/^\/attachments\/doc-a$/],
  ['GET',/^\/attachments\/11111111-1111-1111-1111-111111111111$/],
 ] as const;
 await page.route('**/*',async route=>{
  const r=route.request(),u=new URL(r.url()),p=u.pathname,m=r.method();
  if(m==='GET'&&['https://ipinfo.io/json','https://api.ip.sb/geoip'].includes(u.href))return route.fulfill({json:{ip:'192.0.2.1',region:'Fixture',country:'ZZ'}});
  if(u.origin!==origin){await route.abort('blockedbyclient');throw new Error('Denied outside fixture: '+r.url());}
  if(m==='GET'){
   if(p==='/navigation')return route.fulfill({json:{entries:[{id:'notes',visible:true}],legacy_routes:{}}});
   if(p==='/external-modules')return route.fulfill({json:[]});
   if(p==='/auth/status')return route.fulfill({json:{initialized:true}});
   if(p==='/notifications/unread-count')return route.fulfill({json:{count:0}});
   if(['/config/public-host','/config/site-background','/config/home'].includes(p))return route.fulfill({json:{value:''}});
   if(['/','/notes','/settings','/favicon.svg','/avatar.png'].includes(p)||/^\/static\/[a-zA-Z0-9_./-]+$/.test(p))return route.continue();
  }
  if(permitted.some(([method,re])=>method===m&&re.test(p)))return route.fallback();
  await route.abort('blockedbyclient');throw new Error('Unknown fixture endpoint: '+m+' '+p);
 });
}
