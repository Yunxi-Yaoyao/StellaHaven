import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';
import { ZIP_IMPORT_LIMITS as zip, SOURCE_IMPORT_LIMITS as source } from './importLimits';

// Read only literal definitions, never import Python app/config or any environment.
const backend = (name: string) => readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../../../app/services', `${name}.py`), 'utf8');
it('displayed ZIP budgets stay bound to the server literal limits', () => {
  const code = backend('notes_zip');
  for (const [name, value] of Object.entries({MAX_COMPRESSED: zip.uploadMiB * 1024 * 1024,
    MAX_TOTAL: zip.totalMiB * 1024 * 1024, MAX_FILE: zip.fileMiB * 1024 * 1024,
    MAX_ENTRIES: zip.entries, MAX_DEPTH: zip.depth, MAX_PATH_BYTES: zip.pathBytes, MAX_NAME_BYTES: zip.nameBytes})) {
    const expression = code.match(new RegExp(`^${name} = ([0-9 *]+)$`, 'm'))?.[1];
    expect(expression, name).toBeDefined();
    expect(expression!.split('*').reduce((total, factor) => total * Number(factor.trim()), 1), name).toBe(value);
  }
  expect(code).toContain(`info.file_size > max(1, info.compress_size) * ${zip.ratio}`);
});
it('HTML and project descriptions distinguish decoded source from upload budget', () => {
  expect(source.uploadMiB).toBe(zip.fileMiB);
  expect(backend('html_note_conversion')).toContain("if len(data)>MAX_FILE:");
  expect(backend('html_note_conversion')).toContain(`if len(source.encode('utf-8'))>${source.decodedMiB}*1024*1024:`);
  expect(backend('web_projects')).toContain('if len(data)>MAX_FILE:');
  expect(backend('web_projects')).toContain(`if any(len(v.encode())>${source.decodedMiB}*1024*1024 for v in decoded.values()):`);
});
