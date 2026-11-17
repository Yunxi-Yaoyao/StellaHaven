import { beforeEach, expect, it, vi } from 'vitest';
beforeEach(() => { localStorage.clear(); vi.resetModules(); });
it('validates every finite token, rejects types and keeps base/reset/undo transactional',async()=>{
 const s=await import('./appearance');const contract=await import('./appearancePalette');
 for(const token of contract.tokenNames)expect(contract.validateCustomAppearance({version:1,base:'B',overrides:{[token]:'#abcdef'}}).overrides[token]).toBe('#ABCDEF');
 for(const base of ['C',false,{toString:()=> 'A'}])expect(()=>contract.validateCustomAppearance({version:1,base,overrides:{}})).toThrow();
 expect(()=>contract.validateCustomAppearance({version:1,base:'A',overrides:{'--accent':'#FFFFFF'}})).toThrow();
 s.setAppearance('B');s.beginAppearanceEdit();s.setPaletteColor('accent','#ABCDEF',true);expect(s.appearancePreference.value.appearance).toBe('custom');expect(JSON.parse(localStorage.getItem('stella_custom_appearance')!).overrides.accent).toBe('#ABCDEF');s.cancelAppearanceEdit();expect(s.resolvedPalette.value.accent).toBe('#ABCDEF');
 s.beginAppearanceEdit();s.resetPaletteToken('accent',true);expect(s.appearancePreference.value.customAppearance?.overrides.accent).toBeUndefined();s.cancelAppearanceEdit();s.undoAppearance();expect(s.resolvedPalette.value.accent).toBe('#ABCDEF');
 s.resetPaletteToken('accent');expect(s.resolvedPalette.value.accent).toBe(s.palettes.B.accent);s.undoAppearance();expect(s.resolvedPalette.value.accent).toBe('#ABCDEF');s.restorePaletteBase();expect(s.appearance.value).toBe('B');s.undoAppearance();expect(s.resolvedPalette.value.accent).toBe('#ABCDEF');
 expect(contract.contrastRatio('#FFFFFF','#000000')).toBe(21);
});
it('finishes multi-token edits without a false unsaved preview caused by token insertion order',async()=>{
 const s=await import('./appearance');s.setAppearance('A');s.setPaletteColor('metric-cpu','#ABCDEF');s.beginAppearanceEdit();s.setPaletteColor('bg-raised','#303142',true);s.finishAppearanceEdit();expect(s.hasAppearancePreview.value).toBe(false);
});
it('first real change bases custom on B and retains it through presets and reload with chart hex',async()=>{
 const s:any=await import('./appearance');s.setAppearance('B');
 expect(s.setPaletteColor,'custom palette edit API').toBeTypeOf('function');
 s.setPaletteColor('accent',s.palettes.B.accent);expect(s.appearance.value).toBe('B');
 s.setPaletteColor('accent','#ABCDEF');expect(s.appearance.value).toBe('custom');
 expect(s.customAppearance.value).toEqual({version:1,base:'B',overrides:{accent:'#ABCDEF'}});
 expect(document.documentElement.style.getPropertyValue('--accent')).toBe('#ABCDEF');
 expect(s.metricColors.value.cpu).toBe(s.palettes.B.cpu);
 s.setAppearance('A');s.setAppearance('custom');expect(s.resolvedPalette.value.accent).toBe('#ABCDEF');
 vi.resetModules();const loaded:any=await import('./appearance');expect(loaded.appearance.value).toBe('custom');expect(loaded.customAppearance.value.base).toBe('B');
});
it('defaults to A, switches immediately and remembers B independently of home composition', async () => {
  localStorage.setItem('stella_home_theme', 'classic');
  const { appearance, setAppearance, metricColors } = await import('./appearance');
  expect(appearance.value).toBe('A');
  setAppearance('B');
  expect(document.documentElement.dataset.appearance).toBe('B');
  expect(localStorage.getItem('stella_appearance')).toBe('B');
  expect(localStorage.getItem('stella_home_theme')).toBe('classic');
  expect(metricColors.value.cpu).toBe('#B8C5FF');
  vi.resetModules();
  expect((await import('./appearance')).appearance.value).toBe('B');
});
it('rejects unknown stored palettes and exposes storage failures without reverting the visible choice', async () => {
  localStorage.setItem('stella_appearance', 'teal');
  const store = await import('./appearance');
  expect(store.appearance.value).toBe('A');
  const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota'); });
  store.setAppearance('B');
  expect(store.appearance.value).toBe('B');
  expect(store.appearanceError.value).toContain('未保存');
  spy.mockRestore(); store.setAppearance('B');
  expect(store.appearanceError.value).toBe('');
});
it('falls back from coastline without deleting custom background or crop', async () => {
  localStorage.setItem('stella_home_theme', 'coastline');
  localStorage.setItem('stella_home_bg', '/owned-custom.webp');
  localStorage.setItem('stella_home_bgcrop', JSON.stringify({cx:.4,cy:.5,w:.8,h:.9}));
  const { homeSettings } = await import('../modules/home/settings');
  expect(homeSettings.theme).toBe('daybreak');
  expect(homeSettings.bgImage).toBe('/owned-custom.webp');
  expect(homeSettings.bgCrop.w).toBe(.8);
});
