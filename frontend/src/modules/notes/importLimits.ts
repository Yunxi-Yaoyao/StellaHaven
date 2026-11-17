// Mirrors app/services/{notes_zip,html_note_conversion,web_projects}.py.
// importLimits.test.ts binds these descriptions to the backend budgets without importing app/config.
export const ZIP_IMPORT_LIMITS = {
  uploadMiB: 32, totalMiB: 128, fileMiB: 25, entries: 2000,
  depth: 32, ratio: 200, pathBytes: 1024, nameBytes: 255,
} as const;
export const SOURCE_IMPORT_LIMITS = { uploadMiB: 25, decodedMiB: 5 } as const;
const z = ZIP_IMPORT_LIMITS, s = SOURCE_IMPORT_LIMITS;
export const archiveLimitsText = `ZIP 展开合计 ≤ ${z.totalMiB} MiB，单文件 ≤ ${z.fileMiB} MiB；最多 ${z.entries} 个条目（含目录及隐含目录），路径深度 ≤ ${z.depth} 层，单文件展开比 ≤ ${z.ratio} 倍；UTF-8 路径 ≤ ${z.pathBytes} 字节、单段名称 ≤ ${z.nameBytes} 字节。`;
export const zipLimitsText = `ZIP 上传 ≤ ${z.uploadMiB} MiB。${archiveLimitsText}`;
export const htmlLimitsText = `HTML / ZIP 上传 ≤ ${s.uploadMiB} MiB；每个 HTML 源码解码后 UTF-8 ≤ ${s.decodedMiB} MiB。${archiveLimitsText} 转换结果归档 ≤ ${z.uploadMiB} MiB（含保留的原文件 ZIP），并须满足上述展开预算。`;
export const projectLimitsText = `HTML / ZIP 上传 ≤ ${s.uploadMiB} MiB；每个文本源码解码后 UTF-8 ≤ ${s.decodedMiB} MiB。${archiveLimitsText}`;
