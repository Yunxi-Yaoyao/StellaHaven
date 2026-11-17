import { afterEach, expect, it } from 'vitest';
import { createApp, h } from 'vue';
import Icon from '../../shell/Icon.vue';
import { navigationIcons, legacyNavigationIcons } from '../../stores/navigation';
import baselinePaths from './navigationIcons.baseline.json';
import { iconCatalog, iconCategories, navigationIcon } from '../../icons/navigationIcons';

const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).forEach(clean => clean()); });
function draw(name: string) {
  const host = document.createElement('div'); document.body.append(host);
  const app = createApp({ render: () => h(Icon, { name }) }); app.mount(host);
  cleanups.push(() => { app.unmount(); host.remove(); });
  return host.querySelector('svg')!;
}
it('offers at least 80 distinct useful line icons, all actually rendered', () => {
  expect(navigationIcons.length).toBeGreaterThanOrEqual(80);
  expect(new Set(navigationIcons).size).toBe(navigationIcons.length);
  const shapes = navigationIcons.map(name => {
    const svg = draw(name);
    expect(svg.getAttribute('fill')).toBe('none');
    expect(svg.children.length, name).toBeGreaterThan(0);
    return svg.innerHTML;
  });
  expect(new Set(shapes).size).toBe(navigationIcons.length);
  for (const alias of legacyNavigationIcons) expect(draw(alias).children.length, alias).toBeGreaterThan(0);
});
it('preserves all 30 pre-expansion SVG path definitions and both legacy aliases exactly', () => {
  for (const [key, paths] of Object.entries(baselinePaths)) {
    expect([...draw(key).querySelectorAll('path')].map(path => path.getAttribute('d')), key).toEqual(paths.split('|'));
  }
  for (const [alias, key] of [['file-text', 'note'], ['hard-drive', 'drive']] as const) {
    expect(draw(alias).innerHTML).toBe(draw(key).innerHTML);
    expect(navigationIcon(alias)?.key).toBe(key);
  }
});
it('uses only finite SVG shapes/attributes and labels every catalog entry in a real category', () => {
  const tags: Record<string, string[]> = { path:['d'], circle:['cx','cy','r'], rect:['x','y','width','height','rx','ry'], line:['x1','y1','x2','y2'], polyline:['points'], polygon:['points'], ellipse:['cx','cy','rx','ry'] };
  for (const icon of iconCatalog) {
    expect(iconCategories[icon.category], icon.key).toBeTruthy();
    expect(icon.label).toMatch(/[\u4e00-\u9fff]/); expect(icon.keywords).not.toBe('');
    for (const [tag, attrs] of icon.nodes) {
      expect(tags[tag], icon.key).toBeTruthy();
      for (const [attr, value] of Object.entries(attrs)) {
        expect([...(tags[tag] ?? []), 'fill'], icon.key).toContain(attr);
        if (attr === 'fill') expect(['none', 'currentColor']).toContain(value);
        else expect(value, icon.key).toMatch(/^[MmZzLlHhVvCcSsQqTtAaEe0-9.,\s+\-]+$/);
      }
    }
  }
});
