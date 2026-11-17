// Finite semantic color contract shared by persistence and the palette editor.
export const paletteDefaults = {
 'bg-base':'#111216','bg-panel':'#191A20','bg-raised':'#252730','bg-sidebar':'#121317',
 'text-hi':'#ECECF3','text-lo':'#B3B4C2','text-faint':'#A1A2B0',
 accent:'#C6B5FA','accent-dim':'#504463',pink:'#EFB3C6',warm:'#EFB3C6',
 'selected-bg':'#302A43','selected-border':'#504463','button-top':'#77619F','button-bottom':'#51416F','button-border':'#9781BB',
 success:'#9AC8AD',warning:'#E5C18C',danger:'#EF939D',
 'control-border':'#50525E','control-bg':'#191A20','control-hover':'#292B33',
 'metric-cpu':'#BAC4FA','metric-memory':'#D0B9FA','metric-disk':'#F1B8CA',
 'metric-cpu-start':'#747EBB','metric-memory-start':'#8870BB','metric-disk-start':'#AC708C',
} as const;
export type PaletteToken=keyof typeof paletteDefaults;
export type Palette=Record<PaletteToken,string>;
export type BaseAppearance='A'|'B';
export type Appearance=BaseAppearance|'custom';
export interface CustomAppearance {version:1;base:BaseAppearance;overrides:Partial<Palette>}
export const tokenNames=Object.freeze(Object.keys(paletteDefaults) as PaletteToken[]);
export const presetPalettes:Record<BaseAppearance,Palette>={A:{...paletteDefaults},B:{...paletteDefaults,
 accent:'#B9C1FF','accent-dim':'#414E70',pink:'#F1B4AB',warm:'#F1B4AB','selected-bg':'#282E46','selected-border':'#414E70',
 'button-top':'#5C6FA8','button-bottom':'#39496F','button-border':'#8092CA',
 'metric-cpu':'#B8C5FF','metric-memory':'#D5B8EE','metric-disk':'#E9BBD4',
 'metric-cpu-start':'#6B7DC6','metric-memory-start':'#9371B8','metric-disk-start':'#AE7C9E',
}};
const plain=(v:unknown):v is Record<string,unknown>=>!!v && typeof v==='object' && !Array.isArray(v) && [Object.prototype,null].includes(Object.getPrototypeOf(v));
export function validateCustomAppearance(v:unknown):CustomAppearance {
 if(!plain(v) || Object.keys(v).sort().join(',')!=='base,overrides,version' || v.version!==1 || typeof v.base!=='string' || !['A','B'].includes(v.base) || !plain(v.overrides))throw Error('自定义配色格式无效');
 const overrides:Partial<Palette>={};
 for(const [key,value] of Object.entries(v.overrides)){
  if(!tokenNames.includes(key as PaletteToken) || typeof value!=='string' || !/^#[0-9A-Fa-f]{6}$/.test(value))throw Error('自定义配色含未允许的颜色或字段');
  overrides[key as PaletteToken]=value.toUpperCase();
 }
 return {version:1,base:v.base as BaseAppearance,overrides:Object.fromEntries(tokenNames.filter(k=>overrides[k]!==undefined).map(k=>[k,overrides[k]]))};
}
export function resolvePalette(appearance:Appearance,custom:CustomAppearance|null):Palette {
 return appearance==='custom' && custom?{...presetPalettes[custom.base],...custom.overrides}:{...presetPalettes[appearance==='B'?'B':'A']};
}
export function contrastRatio(a:string,b:string):number {
 const luminance=(hex:string)=>{const rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return rgb[0]!*.2126+rgb[1]!*.7152+rgb[2]!*.0722;};
 const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);
}
