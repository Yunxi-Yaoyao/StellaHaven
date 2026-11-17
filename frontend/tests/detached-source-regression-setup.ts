// Existing project fixtures predate detached-source identities. Their synthetic
// workspaces contain none; this adapter adds that explicit new HTTP contract.
// No existing project/source response or assertion is changed.
import {vi} from 'vitest';
vi.mock('../src/api/detachedSources',()=>({listDetachedSources:vi.fn(async()=>[])}));
