import {expect,it} from 'vitest';
import {themeParts} from './appearanceParts';
import * as parts from './appearanceParts';
import {presetPalettes,tokenNames} from '../../stores/appearancePalette';
it('makes every supported semantic color reachable without debug token fields',()=>{
 expect([...new Set(themeParts.flatMap(p=>p.properties.map(v=>v.token)))].sort()).toEqual([...tokenNames].sort());
});
it('warns on the worst gradient endpoint and the actual navigation text, not a guessed page color',()=>{
 const contrast=(parts as any).partContrast;
 expect(contrast,'semantic contrast calculation').toBeTypeOf('function');
 expect(contrast('primary',{...presetPalettes.A,'button-bottom':presetPalettes.A['text-hi']})).toBe(1);
 expect(contrast('nav',{...presetPalettes.A,accent:presetPalettes.A['selected-bg']})).toBe(1);
 expect(contrast('input',{...presetPalettes.A,'control-bg':presetPalettes.A['text-hi']})).toBe(1);
});
