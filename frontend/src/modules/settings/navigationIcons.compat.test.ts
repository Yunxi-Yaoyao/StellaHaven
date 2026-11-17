import { expect, it } from 'vitest';
import { resolveNavigation } from '../../stores/navigation';

it('preserves an unknown persisted override for explicit handling rather than silently substituting globe or a default', () => {
  const rows = resolveNavigation({ entries: [{ id: 'home', icon: 'future-icon-v2' }] }, []);
  expect(rows[0]!.icon).toBe('future-icon-v2');
});
