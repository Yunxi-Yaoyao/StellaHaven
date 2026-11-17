import { afterEach, expect, it, vi } from 'vitest';
import { createApp, h } from 'vue';
import Icon from '../../shell/Icon.vue';
import { resolveNavigation, type Website } from '../../stores/navigation';
import { validateInjection } from '../../api/integrations';
import { api } from '../../api/client';
import fixture from '../../../tests/fixtures/publicWebsiteProjection.json';

vi.mock('../../api/client', () => ({ api: vi.fn(async () => ({valid: true, errors: []})) }));
const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).forEach(clean => clean()); vi.clearAllMocks(); });

it('consumes projected saved-template history without losing code, policy or display state', () => {
  const saved = fixture.saved as Website;
  const rows = resolveNavigation(fixture.navigation, [saved]);
  expect(rows.find(row => row.id === 'home')).toMatchObject({label: 'My Home', to: '/', builtin: true});
  expect(rows.find(row => row.id === saved.id)).toMatchObject({label: saved.name, icon: 'old-custom-icon', visible: false, to: '/apps/legacy-id', builtin: false});
  expect(saved.template_id).toBe('user_' + 'a'.repeat(32));
  expect(saved.keep_alive).toBe(true);
  expect(saved.background).toBe('home');
  expect(saved.connection?.has_token).toBe(true);
  expect(saved.request_policy?.protect_other_writes).toBe(true);
  for (const slot of ['draft', 'active', 'previous'] as const) {
    expect(saved.injection?.[slot]).toMatchObject({css: 'body{color:red}', csp_policy: 'controlled', version: 'old-v1'});
    expect(saved.injection?.[slot]?.js).toContain('secret is legitimate code');
  }
  expect(JSON.stringify(fixture)).not.toContain('synthetic-');
});

it('renders an unknown historical icon with the existing globe fallback without rewriting its ID', () => {
  function draw(name: string) {
    const host = document.createElement('div'); document.body.append(host);
    const app = createApp({render: () => h(Icon, {name})}); app.mount(host);
    cleanups.push(() => { app.unmount(); host.remove(); });
    return [...host.querySelectorAll('path')].map(path => path.getAttribute('d'));
  }
  expect(draw(fixture.saved.icon)).toEqual(draw('globe'));
  expect(fixture.saved.icon).toBe('old-custom-icon');
});

it('keeps incomplete projections typed and explicitly marked, rather than casting malformed JSON into the editor', () => {
  const malformed = fixture.malformed;
  expect(malformed.projection).toEqual({state: 'incomplete', invalid_fields: ['keep_alive', 'name']});
  expect(malformed.name).toBe('配置不完整');
  expect(malformed.keep_alive).toBe(false);
  expect(malformed.injection.active?.css).toBe(fixture.saved.injection.active?.css);
  expect(malformed.capabilities.injection).toBe(false);
});

it('resends only editable draft keys even when the public version retains provenance', async () => {
  await validateInjection(fixture.saved.id, fixture.saved.injection.active as NonNullable<Website['injection']>['active'] & {});
  const [, options] = vi.mocked(api).mock.calls[0]!;
  const body = JSON.parse(String(options?.body));
  expect(Object.keys(body).sort()).toEqual(['csp_policy', 'css', 'enabled', 'js', 'timing']);
  expect(body.js).toBe(fixture.saved.injection.active.js);
});
