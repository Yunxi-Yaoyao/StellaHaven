import { afterEach, expect, it } from 'vitest';
import { createApp, h, nextTick, ref } from 'vue';
import IconPicker from './IconPicker.vue';

const cleanups: (() => void)[] = [];
afterEach(() => cleanups.splice(0).forEach(clean => clean()));
function mount(value = 'home') {
  const selected = ref(value), changes: string[] = [];
  const host = document.createElement('div'); document.body.append(host);
  const app = createApp({ render: () => h(IconPicker, { modelValue: selected.value, name: '我的知识库', 'onUpdate:modelValue': (value: string) => { changes.push(value); selected.value = value; } }) });
  app.mount(host); cleanups.push(() => { app.unmount(); host.remove(); });
  return { host, selected, changes };
}
async function click(el: Element | null) { expect(el).not.toBeNull(); (el as HTMLElement).click(); await nextTick(); await nextTick(); }
async function search(host: HTMLElement, text: string) {
  const input = host.querySelector<HTMLInputElement>('input[type=search]'); expect(input).not.toBeNull();
  input!.value = text; input!.dispatchEvent(new Event('input', { bubbles: true })); await nextTick();
}
const radios = (host: HTMLElement) => [...host.querySelectorAll<HTMLElement>('[role=radio]')];
it.each(['file-text', 'hard-drive', 'future-icon-v2'])('opening, filtering and cancelling never rewrites stored %s', async value => {
  const { host, selected, changes } = mount(value);
  if (value === 'future-icon-v2') expect(host.textContent).toContain('未知图标：future-icon-v2（保留原值）');
  await click(host.querySelector('button')); await search(host, 'database');
  host.querySelector('input')!.dispatchEvent(new KeyboardEvent('keydown', { key:'Escape', bubbles:true })); await nextTick();
  expect(selected.value).toBe(value); expect(changes).toEqual([]);
  await click(host.querySelector('button'));
  expect(host.querySelector<HTMLInputElement>('input')!.value).toBe('database');
});
it('searches Chinese, English and synonyms within a semantic category and shows an actionable empty state', async () => {
  const { host, changes } = mount();
  await click(host.querySelector('button'));
  expect(document.activeElement).toBe(host.querySelector('input[type=search]'));
  for (const word of ['数据库', ' DATABASE ', 'postgres']) {
    await search(host, word);
    expect(radios(host).map(el => el.getAttribute('aria-label'))).toEqual(['数据库']);
  }
  await search(host, '');
  await click([...host.querySelectorAll('button')].find(el => el.textContent?.includes('媒体创作'))!);
  expect(radios(host).some(el => el.getAttribute('aria-label') === '图片')).toBe(true);
  expect(radios(host).some(el => el.getAttribute('aria-label') === '数据库')).toBe(false);
  await search(host, 'nothing-matches');
  expect(radios(host)).toHaveLength(0);
  expect(host.textContent).toContain('没有找到图标');
  await click([...host.querySelectorAll('button')].find(el => el.textContent === '清除筛选')!);
  expect(radios(host).length).toBeGreaterThanOrEqual(80);
  expect(changes).toEqual([]);
});
it('uses the rendered column count, keeps one tab stop, and selects only on activation', async () => {
  const { host, changes } = mount(); await click(host.querySelector('button'));
  const buttons = radios(host);
  // A narrow three-column grid, not the old hardcoded four-column assumption.
  buttons.forEach((button, index) => Object.defineProperty(button, 'offsetTop', { value: Math.floor(index / 3) * 72 }));
  buttons[0]!.focus();
  buttons[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })); await nextTick();
  expect(document.activeElement).toBe(buttons[3]);
  expect(buttons.filter(button => button.tabIndex === 0)).toEqual([buttons[3]]);
  expect(changes).toEqual([]);
  buttons[3]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true })); await nextTick();
  expect(document.activeElement).toBe(buttons.at(-1));
  buttons.at(-1)!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true })); await nextTick();
  expect(document.activeElement).toBe(buttons[0]);
  await click(buttons[3]!);
  expect(changes).toHaveLength(1);
  expect(host.querySelector('[role=region]')).toBeNull();
  expect(document.activeElement).toBe(host.querySelector('button'));
  expect(host.querySelector('.sidebar-preview svg')?.innerHTML).toBe(host.querySelector('.picker-trigger svg')?.innerHTML);
});
it('Escape closes from search and category controls without leaking to the parent; IME Escape is ignored', async () => {
  const { host, changes } = mount('hard-drive'); await click(host.querySelector('button'));
  const input = host.querySelector('input')!;
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', isComposing: true, bubbles: true })); await nextTick();
  expect(host.querySelector('[role=region]')).not.toBeNull();
  let bubbled = 0; host.addEventListener('keydown', () => bubbled++);
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await nextTick(); await nextTick();
  expect(host.querySelector('[role=region]')).toBeNull(); expect(bubbled).toBe(0);
  expect(document.activeElement).toBe(host.querySelector('button')); expect(changes).toEqual([]);
  await click(host.querySelector('button'));
  host.querySelector('.categories button')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await nextTick();
  expect(host.querySelector('[role=region]')).toBeNull();
});
