import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { api } from './client';
import * as client from './client';
import {refreshAccess} from '../modules/home/auth';
vi.mock('../modules/home/auth', () => ({ auth:{me:{id:'fixture'},sessionGeneration:0,sessionClosing:false,suspended:false},refreshAccess: vi.fn(async () => false) }));
const denied = () => new Response(JSON.stringify({detail:{code:'admin_elevation_required'}}), {status:403});
beforeEach(() => vi.stubGlobal('fetch', vi.fn()));
afterEach(() => vi.unstubAllGlobals());
it('lets the browser choose multipart boundaries and preserves Headers entries', async () => {
  const body = new FormData(); body.append('file', new Blob(['fixture']), 'probe.zip');
  const headers = new Headers({'X-Fixture':'kept','Content-Type':'application/json'});
  vi.mocked(fetch).mockResolvedValue(new Response('{"ok":true}'));
  await api('/documents/import/zip/preview', {method:'POST',body,headers});
  const options=vi.mocked(fetch).mock.calls[0]![1]!;
  const sent=new Headers(options.headers);
  expect(options.body).toBe(body);
  expect(sent.get('Content-Type')).toBeNull();
  expect(sent.get('X-Fixture')).toBe('kept');
});
it('adds JSON content type only for a string body without an explicit type', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response('{"ok":true}'));
  await api('/fixture',{method:'POST',body:'{}',headers:[['X-Fixture','kept']]});
  const sent=new Headers(vi.mocked(fetch).mock.calls[0]![1]!.headers);
  expect(sent.get('Content-Type')).toBe('application/json');
  expect(sent.get('X-Fixture')).toBe('kept');
});

it('requires an explicit elevation handler and retries the blocked request only once', async () => {
  const register = (client as any).setElevationHandler;
  expect(register, 'global elevation handler must exist').toBeTypeOf('function');
  const authorize = vi.fn(async () => true);
  register(authorize);
  vi.mocked(fetch).mockResolvedValueOnce(denied()).mockResolvedValueOnce(new Response('{"ok":true}'));
  expect(await api('/danger', {method:'DELETE'})).toEqual({ok:true});
  expect(authorize).toHaveBeenCalledWith('admin_elevation_required', '/danger');
  expect(fetch).toHaveBeenCalledTimes(2);
});
it('does not automatically replay a rejected management password as an access refresh',async()=>{
 vi.mocked(refreshAccess).mockClear();vi.mocked(fetch).mockResolvedValue(new Response('{"detail":"密码错误"}',{status:401}));
 await expect(api('/auth/admin/unlock',{method:'POST',body:'{"password":"MOCK_INVALID"}'})).rejects.toMatchObject({status:401});
 expect(refreshAccess).not.toHaveBeenCalled();expect(fetch).toHaveBeenCalledTimes(1);
});
it('does not retry generic 403, canceled elevation, or a second authorization denial',async()=>{
 const authorize=vi.fn(async()=>true);client.setElevationHandler(authorize);
 vi.mocked(fetch).mockResolvedValue(new Response('{"detail":"forbidden"}',{status:403}));
 await expect(api('/generic')).rejects.toMatchObject({status:403});expect(authorize).not.toHaveBeenCalled();
 vi.mocked(fetch).mockClear().mockResolvedValue(denied());
 client.setElevationHandler(async()=>false);await expect(api('/cancel',{method:'DELETE'})).rejects.toMatchObject({status:403});expect(fetch).toHaveBeenCalledTimes(1);
 vi.mocked(fetch).mockClear().mockResolvedValue(denied());client.setElevationHandler(authorize);
 await expect(api('/twice',{method:'DELETE'})).rejects.toMatchObject({status:403});expect(fetch).toHaveBeenCalledTimes(2);expect(authorize).toHaveBeenCalledTimes(1);
});
