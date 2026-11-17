// @vitest-environment jsdom
import {describe,it,expect,beforeEach} from 'vitest';
import {oidcLoginTarget,openLogin,consumeLoginTarget} from './loginPrompt';
describe('native OIDC login continuation',()=>{
 beforeEach(()=>consumeLoginTarget());
 it('preserves exact same-origin authorize query and consumes once',()=>{
  const query='?client_id=rp&state=a%26b&redirect_uri=https%3A%2F%2Frp.test%2Fcallback&code_challenge=x';
  const value=location.origin+'/oauth/authorize'+query;
  expect(oidcLoginTarget(value)).toBe('/oauth/authorize'+query);
  openLogin(value);expect(consumeLoginTarget()).toBe('/oauth/authorize'+query);expect(consumeLoginTarget()).toBeNull();
 });
 it.each(['https://evil.test/oauth/authorize','//evil.test/oauth/authorize','/oauth/authorize/extra','/oauth/token','/notes','/oauth/authorize#fragment','/oauth/authorize?x=1\\evil','https://user:password@localhost/oauth/authorize'])('rejects non-authorize/foreign/ambiguous continuation %s',value=>{
  expect(oidcLoginTarget(value)).toBeNull();openLogin(value);expect(consumeLoginTarget()).toBeNull();
 });
 it('ordinary modal login does not create a navigation',()=>{openLogin();expect(consumeLoginTarget()).toBeNull()});
});
