// @vitest-environment jsdom
import {afterEach, expect, it, vi} from 'vitest';
import {createApp, h, nextTick, reactive} from 'vue';
import ImportReadPreview from './ImportReadPreview.vue';

let app: ReturnType<typeof createApp> | undefined;
afterEach(() => {app?.unmount(); app=undefined; document.body.innerHTML='';});
async function mount(markdown: string) {
  const root=document.createElement('div'); document.body.append(root);
  app=createApp(ImportReadPreview,{markdown}); app.mount(root); await nextTick();
  return root.querySelector<HTMLElement>('.preview-body')!;
}

it('renders checked and unchecked Markdown tasks as disabled checkboxes, never image placeholders', async () => {
  const body=await mount('- [x] 已完成\n- [ ] 待完成\n  - [X] 嵌套已完成');
  const boxes=[...body.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
  expect(boxes).toHaveLength(3);
  expect(boxes.map(box=>box.checked)).toEqual([true,false,true]);
  expect(boxes.every(box=>box.disabled)).toBe(true);
  expect(body.querySelector('.preview-media-missing')).toBeNull();
  expect(body.textContent).toContain('已完成');
  expect(body.textContent).toContain('待完成');
  for (const box of boxes) {
    const checked=box.checked; box.click();
    expect(box.checked).toBe(checked);
    expect(box.disabled).toBe(true);
  }
});

it('reconstructs HTML checkboxes with only type, disabled and genuine boolean checked state', async () => {
  const body=await mount(`<input type="checkbox" checked="false" id="attacker" name="payload" value="secret"
    autofocus tabindex="0" contenteditable="true" form="remote" formaction="https://outside.invalid/submit"
    src="https://outside.invalid/input.png" srcset="https://outside.invalid/x 1x" background="https://outside.invalid/bg"
    data-private-src="/api/attachments/private" style="background:url(https://outside.invalid/css)"
    onclick="window.__previewInputEvent()" onchange="window.__previewInputEvent()" onfocus="window.__previewInputEvent()">
    <input type="CHECKBOX"><input type=" checkbox "><label for="attacker">只读标签</label>`);
  const boxes=[...body.querySelectorAll<HTMLInputElement>('input')];
  expect(boxes.map(box=>box.checked)).toEqual([true,false,false]);
  expect(boxes.map(box=>box.getAttributeNames().sort())).toEqual([
    ['checked','disabled','type'],['disabled','type'],['disabled','type'],
  ]);
  expect(boxes.every(box=>box.type==='checkbox' && box.disabled)).toBe(true);
  const events=vi.fn(); Object.assign(window,{__previewInputEvent:events});
  try {
    for (const box of boxes) {
      box.click(); box.focus();
      for (const type of ['click','change','focus','keydown'])box.dispatchEvent(new Event(type,{bubbles:true}));
    }
    (body.querySelector('label') as HTMLLabelElement).click();
    expect(boxes.map(box=>box.checked)).toEqual([true,false,false]);
    expect(boxes.includes(document.activeElement as HTMLInputElement)).toBe(false);
    expect(events).not.toHaveBeenCalled();
  } finally {Reflect.deleteProperty(window,'__previewInputEvent');}
});

it('removes every non-checkbox source input instead of activating arbitrary form controls', async () => {
  const types=['text','password','file','image','submit','button','reset','radio','hidden','range','number','email','search','date','color','unknown'];
  const body=await mount('正文前\n\n'+types.map(type=>`<input type="${type}" value="unsafe" src="https://outside.invalid/input.png" autofocus onclick="alert(1)">`).join('')+'<input>\n\n正文后');
  expect(body.querySelector('input')).toBeNull();
  expect(body.querySelector('.preview-media-missing')).toBeNull();
  expect(body.textContent).toContain('正文前'); expect(body.textContent).toContain('正文后');
});

it('retains media, private-media and active-content denial alongside task checkboxes', async () => {
  const body=await mount(`- [x] 安全任务

![外图](https://outside.invalid/image.png)
<img src="/api/attachments/private" data-private-src="https://outside.invalid/forged" onerror="alert(1)">
<picture><source srcset="https://outside.invalid/picture.png 1x"><img src="/api/attachments/fallback"></picture>
<video src="https://outside.invalid/v" poster="/api/attachments/poster"><source src="/api/attachments/video"><track src="https://outside.invalid/t"></video>
<audio src="/api/attachments/audio"></audio>
<svg><image href="https://outside.invalid/svg.png"/></svg>
<div background="https://outside.invalid/bg" contenteditable="true" tabindex="0">背景正文</div>
<script>alert(1)</script><iframe src="https://outside.invalid/frame"></iframe><object data="https://outside.invalid/object"></object><embed src="https://outside.invalid/embed">
<a href="https://outside.invalid/link" target="_blank" tabindex="0" onclick="alert(1)">外链文字</a><a href="javascript:alert(1)">危险协议</a>
<textarea>只读文字</textarea><select><option>选项文字</option></select><button onclick="alert(1)">按钮文字</button>`);
  expect(body.querySelectorAll('input')).toHaveLength(1);
  expect(body.querySelector<HTMLInputElement>('input')!.checked).toBe(true);
  expect(body.querySelector('img,video,audio,picture,source,track,svg,image,script,iframe,object,embed,form,textarea,select,button,[background],[contenteditable],[tabindex]')).toBeNull();
  expect(body.querySelector('a[href],a[target]')).toBeNull();
  for (const el of body.querySelectorAll('*')) {
    expect(el.getAttributeNames().filter(name=>/^on|^data-private-|^(src|srcset|poster|srcdoc|style)$/.test(name))).toEqual([]);
  }
  expect(body.querySelectorAll('.preview-media-missing').length).toBeGreaterThan(0);
  expect(body.textContent).toContain('图片未加载'); expect(body.textContent).toContain('外链文字');
});

it('keeps source view escaped and refreshes checked state when Markdown changes', async () => {
  const props=reactive({markdown:'- [x] 原任务\n\n<input type="file" onclick="alert(1)">'});
  const root=document.createElement('div'); document.body.append(root);
  app=createApp({render:()=>h(ImportReadPreview,{markdown:props.markdown})}); app.mount(root); await nextTick();
  const source=[...root.querySelectorAll('button')].find(b=>b.textContent==='源码')!;
  source.click(); await nextTick();
  expect(root.querySelector('.preview-body')).toBeNull();
  expect(root.querySelector('.preview-source')!.textContent).toBe(props.markdown);
  expect(root.querySelector('input')).toBeNull();
  props.markdown='- [ ] 新任务'; await nextTick();
  expect(root.querySelector('.preview-source')).toBeNull();
  const box=root.querySelector<HTMLInputElement>('.preview-body input')!;
  expect(box.disabled).toBe(true); expect(box.checked).toBe(false);
});
