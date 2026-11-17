import {contrastRatio,type Palette,type PaletteToken} from '../../stores/appearancePalette';
export function partContrast(id:string,p:Palette):number {
 const pairs:Partial<Record<string,[PaletteToken,PaletteToken][]>>={
  page:[['text-hi','bg-base'],['text-lo','bg-base'],['text-faint','bg-base']],
  nav:[['accent','selected-bg'],['text-lo','bg-sidebar']],panel:[['text-hi','bg-panel'],['text-lo','bg-panel']],
  input:[['text-hi','control-bg'],['text-lo','bg-raised'],['danger','control-bg']],
  primary:[['text-hi','button-top'],['text-hi','button-bottom']],secondary:[['text-hi','control-bg'],['text-hi','control-hover']],
  danger:[['danger','bg-base']],content:[['text-hi','selected-bg'],['text-lo','selected-bg'],['warm','bg-base'],['pink','bg-base']],
  notice:[['success','bg-base'],['warning','bg-base']],overlay:[['text-hi','bg-raised']],
 };
 return Math.min(...(pairs[id]??[['text-hi','bg-base']]).map(([foreground,background])=>contrastRatio(p[foreground],p[background])));
}
export interface ThemePart {id:string;name:string;scope:string;properties:{label:string;token:PaletteToken}[]}
const prop=(label:string,token:PaletteToken)=>({label,token});
export const themeParts:ThemePart[]=[
 {id:'page',name:'页面底色',scope:'Stella 页面底色，不包含主页背景图片或外置网站。',properties:[prop('背景','bg-base'),prop('文字','text-hi'),prop('次要文字','text-lo'),prop('弱文字','text-faint')]},
 {id:'nav',name:'二级导航',scope:'所有选中导航与列表行；侧栏底色单独调整。',properties:[prop('选中背景','selected-bg'),prop('选中边框','selected-border'),prop('侧栏底色','bg-sidebar'),prop('悬停','control-hover'),prop('强调文字','accent')]},
 {id:'panel',name:'面板与卡片',scope:'Stella 表单、卡片和菜单的表面层次。',properties:[prop('面板背景','bg-panel'),prop('浮层背景','bg-raised'),prop('边框','control-border')]},
 {id:'input',name:'输入与只读字段',scope:'所有表单的控件背景、文字、边框与悬停。',properties:[prop('背景','control-bg'),prop('文字','text-hi'),prop('边框','control-border'),prop('悬停','control-hover'),prop('焦点','accent')]},
 {id:'primary',name:'主按钮',scope:'所有 Stella 主按钮的渐变背景与边框；次按钮不使用这组背景。',properties:[prop('背景上沿','button-top'),prop('背景下沿','button-bottom'),prop('边框','button-border'),prop('文字','text-hi')]},
 {id:'secondary',name:'次按钮与图标',scope:'共用中性控件的背景、边框、文字与悬停。',properties:[prop('背景','control-bg'),prop('文字','text-hi'),prop('边框','control-border'),prop('悬停','control-hover')]},
 {id:'danger',name:'危险与错误',scope:'删除动作、错误文字与错误边框；始终附有文字说明。',properties:[prop('危险色','danger')]},
 {id:'switch',name:'开关与强调',scope:'焦点、开启状态、链接与强调文字共用强调色。',properties:[prop('强调色','accent'),prop('弱强调','accent-dim')]},
 {id:'content',name:'列表、表格与标签',scope:'列表与表格文字、选中行以及暖色标签。',properties:[prop('正文','text-hi'),prop('说明','text-lo'),prop('选中背景','selected-bg'),prop('暖色','warm'),prop('粉色','pink')]},
 {id:'notice',name:'状态提示',scope:'成功与警告提示；颜色之外保留状态文字。',properties:[prop('成功','success'),prop('警告','warning')]},
 {id:'overlay',name:'菜单、帮助与弹层',scope:'Stella 浮层背景、正文和边框。',properties:[prop('背景','bg-raised'),prop('文字','text-hi'),prop('边框','control-border')]},
 ...(['cpu','memory','disk'] as const).map((kind,i)=>({id:kind,name:['CPU 图表','内存图表','磁盘图表'][i]!,scope:'服务器图表、指标色块与同类数据系列；图表读取实际颜色重绘。',properties:[prop('曲线',`metric-${kind}`),prop('起点',`metric-${kind}-start`)]})),
];
