import { localId } from './localId.ts';

export type ImportEncoding = 'auto' | 'utf-8' | 'gb18030';

export class ImportDecodeError extends Error {}

export function decodeImport(bytes: Uint8Array, name: string, encoding: ImportEncoding = 'auto') {
  let codec: string = encoding === 'auto' ? 'utf-8' : encoding;
  if (encoding === 'auto') {
    if (bytes[0] === 0xff && bytes[1] === 0xfe) codec = 'utf-16le';
    if (bytes[0] === 0xfe && bytes[1] === 0xff) codec = 'utf-16be';
  }
  let text: string;
  try {
    text = new TextDecoder(codec, { fatal: true }).decode(bytes).replace(/\r\n?/g, '\n');
  } catch {
    throw new ImportDecodeError('编码无法识别，请选择 UTF-8 或 GB18030 后重试');
  }
  if (text.includes('\0')) throw new Error('含 NUL 字符，疑似二进制文件，拒绝导入');
  if (/\.txt$/i.test(name)) {
    text = text.replace(/[\\`*_{}\[\]()#+.!|~\-]/g, '\\$&')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\n/g, '  \n');
  }
  return { title: name.replace(/\.(md|txt)$/i, '') || '未命名笔记', content: text };
}


export const MAX_IMPORT_FILES = 50;
export const MAX_IMPORT_FILE_BYTES = 5 * 1024 * 1024;
export const MAX_IMPORT_BATCH_BYTES = 20 * 1024 * 1024;
export interface ImportSource {
  name: string;
  size: number;
  webkitRelativePath?: string;
  isDirectory?: boolean;
  arrayBuffer(): Promise<ArrayBuffer>;
}
export interface ImportRow {
  id: string;
  file: ImportSource;
  encoding: ImportEncoding;
  status: 'pending' | 'reading' | 'ready' | 'encoding-error' | 'rejected' | 'importing' | 'success' | 'failed';
  title: string;
  content?: string;
  error: string;
  warning: string;
  documentId?: string;
  payload?: ImportPayload;
}
export interface ImportTarget { workspaceId: string; parentId: string | null }
export interface ImportPayload {
  workspace_id: string;
  parent_id: string | null;
  title: string;
  content: string;
  file_path: string;
  status: 'published';
  visibility: 'private';
}

// Snapshot destination and payload before the first request; retry only failed rows.
export async function runImportBatch(
  rows: ImportRow[], target: ImportTarget, existingTitles: string[],
  create: (payload: ImportPayload) => Promise<{ id: string }>,
): Promise<void> {
  const destination = { ...target };
  const used = new Set([...existingTitles, ...rows.flatMap(row => row.payload ? [row.payload.title] : [])]);
  const pending = rows.filter(row => row.status === 'ready' || row.status === 'failed');
  for (const row of pending) {
    if (row.payload) continue;
    const base = row.title;
    let title = base;
    for (let n = 2; used.has(title); n++) title = `${base} (${n})`;
    used.add(title);
    const slug = encodeURIComponent(title).replace(/[!'()*]/g, char => `%${char.charCodeAt(0).toString(16).toUpperCase()}`);
    row.payload = { workspace_id: destination.workspaceId, parent_id: destination.parentId,
      title, content: row.content ?? '', file_path: `/imports/${row.id}/${slug}.md`,
      status: 'published', visibility: 'private' };
    row.title = title;
  }
  for (const row of pending) {
    row.status = 'importing';
    row.error = '';
    try {
      const result = await create({ ...row.payload! });
      row.documentId = result.id;
      row.status = 'success';
    } catch (error) {
      row.status = 'failed';
      row.error = error instanceof Error ? error.message : '导入失败';
    }
  }
}
export const isImportFilename = (name: string) => /\.(md|txt)$/i.test(name);

export function queueImports(files: ImportSource[]): ImportRow[] {
  let total = 0;
  return files.map((file, index) => {
    let error = '';
    if (file.isDirectory || file.webkitRelativePath?.includes('/')) error = '暂不支持目录，请单独选择文件';
    else if (!isImportFilename(file.name)) error = '仅支持 .md / .txt，不会作为附件上传';
    else if (index >= MAX_IMPORT_FILES) error = `超出每批 ${MAX_IMPORT_FILES} 个文件限制`;
    else if (file.size > MAX_IMPORT_FILE_BYTES) error = '文件超过 5 MiB 限制';
    else if (total + file.size > MAX_IMPORT_BATCH_BYTES) error = '超出每批 20 MiB 限制';
    else total += file.size;
    return { id: localId(), file, encoding: 'auto', status: error ? 'rejected' : 'pending',
      title: file.name.replace(/\.(md|txt)$/i, '') || '未命名笔记', error, warning: '' };
  });
}


function hasRelativeImages(markdown: string): boolean {
  const urls = [
    ...Array.from(markdown.matchAll(/!\[[^\]]*\]\(\s*<?([^\s)>]+)/g), m => m[1]!),
    ...Array.from(markdown.matchAll(/<img\b[^>]*\bsrc=["']([^"']+)/gi), m => m[1]!),
  ];
  const refs = new Map(Array.from(markdown.matchAll(/^\s*\[([^\]]+)\]:\s*<?([^\s>]+)/gm), m => [m[1]!.toLowerCase(), m[2]!]));
  for (const match of markdown.matchAll(/!\[([^\]]*)\](?:\[([^\]]*)\])?(?!\()/g)) {
    const url = refs.get((match[2] || match[1]!).toLowerCase());
    if (url) urls.push(url);
  }
  return urls.some(url => !/^(?:[a-z][a-z\d+.-]*:|\/|#)/i.test(url));
}

export async function prepareImport(row: ImportRow): Promise<void> {
  if (row.status === 'rejected' || row.status === 'success' || row.status === 'importing') return;
  row.status = 'reading';
  row.error = '';
  try {
    const result = decodeImport(new Uint8Array(await row.file.arrayBuffer()), row.file.name, row.encoding);
    row.content = result.content;
    row.title = result.title;
    row.warning = /\.md$/i.test(row.file.name) && hasRelativeImages(result.content)
      ? '检测到相对路径图片：仅导入正文，图片资源不会自动导入，请随后手动补充附件。' : '';
    row.status = 'ready';
  } catch (error) {
    row.status = error instanceof ImportDecodeError ? 'encoding-error' : 'rejected';
    row.error = error instanceof Error ? error.message : '文件读取失败';
  }
}
