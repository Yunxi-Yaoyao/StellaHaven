import {describe,it,expect} from 'vitest';
import {websiteSaveKey} from './websiteSaveKey';
describe('website idempotency key',()=>{
 it('supports HTTP LAN browsers without randomUUID and never uses weak Math.random',()=>{
  const cryptoLike={getRandomValues:(v:Uint8Array<ArrayBuffer>)=>{v.fill(17);return v;}};
  expect(websiteSaveKey(cryptoLike)).toBe('11111111111111111111111111111111');
 });
 it('accepts a secure randomUUID if present',()=>{
  const cryptoLike={randomUUID:()=> '5f960d18-8f5d-4ee1-b862-3fe3fa195bb8',getRandomValues:(v:Uint8Array<ArrayBuffer>)=>v};
  expect(websiteSaveKey(cryptoLike)).toBe('5f960d18-8f5d-4ee1-b862-3fe3fa195bb8');
 });
});
