import {describe,expect,it} from 'vitest';
import {createLive2dHitMask} from './live2dHitMask';
function pixels(rows:number[][]){const w=rows[0]!.length,h=rows.length,p=new Uint8Array(w*h*4);rows.forEach((r,y)=>r.forEach((a,x)=>p[((h-1-y)*w+x)*4+3]=a));return p;}
describe('framebuffer native hit mask',()=>{
 it('retains transparent holes, uses the existing alpha threshold, and flips GL y',()=>{
  const m=createLive2dHitMask(pixels([[255,0,255],[0,60,61]]),3,2,1);
  expect(m.contains(0,0)).toBe(true);expect(m.contains(1,0)).toBe(false);expect(m.contains(2,0)).toBe(true);
  expect(m.contains(0,1)).toBe(false);expect(m.contains(1,1)).toBe(false);expect(m.contains(2,1)).toBe(true);
  expect(m.path).toBe("path('M0 0h1v1h-1ZM2 0h1v1h-1ZM2 1h1v1h-1Z')");
  expect(m.box).toEqual({x:0,y:0,w:3,h:2});
 });
 it('maps DPR pixels to CSS units without expanding the transparent canvas bounds',()=>{
  const m=createLive2dHitMask(pixels([[255,0],[0,255]]),2,2,2);
  expect(m.contains(.1,.1)).toBe(true);expect(m.contains(.6,.1)).toBe(false);
  expect(m.contains(-.1,0)).toBe(false);expect(m.contains(1,1)).toBe(false);
  expect(m.path).toContain('M0.5 0.5h0.5v0.5h-0.5Z');
 });
 it('has no native hit area for an empty rendered frame',()=>{
  const m=createLive2dHitMask(new Uint8Array(16),2,2,1);
  expect(m.path).toBe('inset(100%)');expect(m.contains(0,0)).toBe(false);
 });
});
