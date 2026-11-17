export type Layout='icon'|'info';
export interface Style {layout?:Layout|null;textColor?:string|null;hideTitle?:boolean|null;hideDescription?:boolean|null}
export interface NavIcon {itemType:1|2|3;src:string;text:string;backgroundColor:string|null}
export interface Card {id:string;title:string;url:string;lanUrl:string;description:string;icon:NavIcon|null;openMethod:1|2;module_id:string|null}
export interface Group {id:string;title:string;description:string;icon:string;style:Style|null;items:Card[]}
export interface Engine {id:string;title:string;url:string;icon:string}
export interface Preferences {layout:Layout;textColor:string|null;hideTitle:boolean;hideDescription:boolean;title:string;titleImage:string;showTitle:boolean;clock:boolean;seconds:boolean;clockColor:string|null;search:boolean;searchIcons:boolean;searchBackground:string|null;searchBorder:string|null;searchText:string|null;engines:Engine[];defaultEngine:string|null;newWindowOpen:boolean;background:'none'|'home'|'custom';backgroundUrl:string;blur:number;mask:number;width:number;widthUnit:'px'|'%';marginX:number;marginTop:number;marginBottom:number;gap:number;padding:number;networkButton:boolean}
export interface Data {groups:Group[];preferences:Preferences}
export interface Snapshot {revision:number;data:Data}
export interface Asset {id:string;url:string;name:string;mime:string;size:number;category:string;width:number|null;height:number|null;sha256:string}
export const copy=<T>(v:T):T=>JSON.parse(JSON.stringify(v));
export function newCard():Card {return {id:crypto.randomUUID(),title:'',url:'',lanUrl:'',description:'',icon:{itemType:1,src:'',text:'',backgroundColor:null},openMethod:2,module_id:null};}
export function newGroup():Group {return {id:crypto.randomUUID(),title:'',description:'',icon:'',style:null,items:[]};}
export function defaultPreferences():Preferences {return {layout:'icon',textColor:null,hideTitle:false,hideDescription:false,title:'导航',titleImage:'',showTitle:false,clock:false,seconds:false,clockColor:null,search:true,searchIcons:true,searchBackground:null,searchBorder:null,searchText:null,engines:[],defaultEngine:null,newWindowOpen:true,background:'none',backgroundUrl:'',blur:0,mask:.35,width:1400,widthUnit:'px',marginX:0,marginTop:0,marginBottom:0,gap:16,padding:24,networkButton:true};}
// Port of the approved yaya-nav groupStyle resolver: false is an override.
export function effectiveStyle(style:Style|null|undefined,p:Preferences) {return {layout:style?.layout??p.layout,textColor:style?.textColor??p.textColor,hideTitle:style?.hideTitle??p.hideTitle,hideDescription:style?.hideDescription??p.hideDescription};}
export function destination(c:Card,network:'wan'|'lan') {return c.module_id?`/apps/${c.module_id}`:network==='lan'?(c.lanUrl||c.url):(c.url||c.lanUrl);}
export function rebaseData(base:Data,draft:Data,latest:Data):Data {
 const equal=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b);
 function merge(b:any,d:any,l:any):any {
  if(equal(b,d))return copy(l);
  if(Array.isArray(b)&&Array.isArray(d)&&Array.isArray(l)){
   const bm=new Map(b.map(x=>[x.id,x])),dm=new Map(d.map(x=>[x.id,x])),lm=new Map(l.map(x=>[x.id,x]));
   for(const item of d){if(bm.has(item.id)&&!lm.has(item.id)&&!equal(bm.get(item.id),item))throw new Error('服务端已删除正在编辑的对象，请取消并重新读取。');}
   const localOrder=d.filter(x=>bm.has(x.id)).map(x=>x.id),oldOrder=b.filter(x=>dm.has(x.id)).map(x=>x.id);
   const reordered=!equal(localOrder,oldOrder);
   const ids=reordered?[...d.map(x=>x.id),...l.filter(x=>!dm.has(x.id)&&!bm.has(x.id)).map(x=>x.id)]:[...l.filter(x=>!bm.has(x.id)||dm.has(x.id)).map(x=>x.id),...d.filter(x=>!bm.has(x.id)&&!lm.has(x.id)).map(x=>x.id)];
   return ids.filter(id=>lm.has(id)||!bm.has(id)).map(id=>dm.has(id)?bm.has(id)?merge(bm.get(id),dm.get(id),lm.get(id)):copy(dm.get(id)):copy(lm.get(id)));
  }
  if(b&&d&&l&&typeof b==='object'&&typeof d==='object'&&typeof l==='object'){
   const result=copy(l);for(const key of Object.keys(d)){if(!equal(b[key],d[key]))result[key]=merge(b[key],d[key],l[key]);}return result;
  }
  return copy(d);
 }
 return merge(base,draft,latest);
}
export function videoUrl(url:string){try{return /\.(mp4|webm|ogv)$/i.test(new URL(url,location.origin).pathname);}catch{return false;}}
