import assert from 'node:assert/strict';
// Only the fresh context owned by this script. No enumeration/revocation API.
export async function captureOwnSession(context, base) {
  const response=await context.request.get(base+'/auth/sessions?current_only=true');
  if(response.status()===401)return null;
  assert.equal(response.status(),200);
  const rows=await response.json();assert.equal(rows.length,1);assert.equal(rows[0].current,true);
  return rows[0].id;
}
export async function logoutOwnSession(context, base, sid) {
  const actual=await captureOwnSession(context,base);
  if(!actual){assert.equal((await context.request.get(base+'/auth/me')).status(),401);return {sid,already_unauthenticated:true,me:401};}
  if(sid)assert.equal(actual,sid,'Context identity changed; do not logout an unknown session');
  const response=await context.request.post(base+'/auth/logout',{headers:{Origin:base}});
  assert.equal(response.status(),200);
  const me=await context.request.get(base+'/auth/me');assert.equal(me.status(),401);
  return {sid:actual,status:response.status(),me:me.status()};
}
