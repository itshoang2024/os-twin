export interface FileIconMeta {
  icon: string;
  colorClass: string;
  label: string;
}

type FileIconOptions = {
  fileType?: string;
  isDirectory?: boolean;
  isExpanded?: boolean;
};

const DEFAULT_FILE_ICON: FileIconMeta = {
  icon: 'insert_drive_file',
  colorClass: 'text-blue-400',
  label: 'File',
};

const DIRECTORY_ICON: FileIconMeta = {
  icon: 'folder',
  colorClass: 'text-amber-500',
  label: 'Folder',
};

const OPEN_DIRECTORY_ICON: FileIconMeta = {
  icon: 'folder_open',
  colorClass: 'text-amber-500',
  label: 'Open folder',
};

const FALLBACK_TYPE_ICONS: Record<string, FileIconMeta> = {
  image: { icon: 'image', colorClass: 'text-emerald-500', label: 'Image' },
  markdown: { icon: 'article', colorClass: 'text-violet-500', label: 'Markdown' },
  code: { icon: 'code', colorClass: 'text-sky-500', label: 'Code' },
  pdf: { icon: 'picture_as_pdf', colorClass: 'text-red-500', label: 'PDF' },
  docx: { icon: 'description', colorClass: 'text-blue-600', label: 'Document' },
  excel: { icon: 'table_chart', colorClass: 'text-emerald-600', label: 'Spreadsheet' },
  binary: { icon: 'data_object', colorClass: 'text-slate-500', label: 'Binary' },
};

const FILENAME_ICON_MAP: Record<string, FileIconMeta> = {
  dockerfile: { icon: 'terminal', colorClass: 'text-cyan-500', label: 'Dockerfile' },
  makefile: { icon: 'terminal', colorClass: 'text-cyan-500', label: 'Makefile' },
  jenkinsfile: { icon: 'account_tree', colorClass: 'text-orange-500', label: 'Pipeline' },
  package: { icon: 'deployed_code', colorClass: 'text-indigo-500', label: 'Package manifest' },
  'package.json': { icon: 'deployed_code', colorClass: 'text-indigo-500', label: 'Package manifest' },
  'package-lock.json': { icon: 'lock', colorClass: 'text-slate-500', label: 'Lockfile' },
  'pnpm-lock.yaml': { icon: 'lock', colorClass: 'text-slate-500', label: 'Lockfile' },
  'yarn.lock': { icon: 'lock', colorClass: 'text-slate-500', label: 'Lockfile' },
  'poetry.lock': { icon: 'lock', colorClass: 'text-slate-500', label: 'Lockfile' },
  'pipfile.lock': { icon: 'lock', colorClass: 'text-slate-500', label: 'Lockfile' },
  'requirements.txt': { icon: 'deployed_code', colorClass: 'text-emerald-600', label: 'Python requirements' },
  pyproject: { icon: 'settings', colorClass: 'text-slate-500', label: 'Project config' },
  'pyproject.toml': { icon: 'settings', colorClass: 'text-slate-500', label: 'Project config' },
  '.gitignore': { icon: 'hide_source', colorClass: 'text-slate-500', label: 'Git ignore' },
  '.dockerignore': { icon: 'hide_source', colorClass: 'text-slate-500', label: 'Docker ignore' },
  '.editorconfig': { icon: 'tune', colorClass: 'text-slate-500', label: 'Editor config' },
  'tsconfig.json': { icon: 'settings', colorClass: 'text-blue-500', label: 'TypeScript config' },
};

const EXTENSION_ICON_MAP: Record<string, FileIconMeta> = {
  md: { icon: 'article', colorClass: 'text-violet-500', label: 'Markdown' },
  markdown: { icon: 'article', colorClass: 'text-violet-500', label: 'Markdown' },
  mdx: { icon: 'article', colorClass: 'text-violet-500', label: 'MDX' },
  txt: { icon: 'notes', colorClass: 'text-slate-500', label: 'Text' },
  pdf: { icon: 'picture_as_pdf', colorClass: 'text-red-500', label: 'PDF' },
  doc: { icon: 'description', colorClass: 'text-blue-600', label: 'Word document' },
  docx: { icon: 'description', colorClass: 'text-blue-600', label: 'Word document' },
  xls: { icon: 'table_chart', colorClass: 'text-emerald-600', label: 'Spreadsheet' },
  xlsx: { icon: 'table_chart', colorClass: 'text-emerald-600', label: 'Spreadsheet' },
  csv: { icon: 'table_chart', colorClass: 'text-emerald-600', label: 'CSV' },
  tsv: { icon: 'table_chart', colorClass: 'text-emerald-600', label: 'TSV' },
  png: { icon: 'image', colorClass: 'text-emerald-500', label: 'Image' },
  jpg: { icon: 'image', colorClass: 'text-emerald-500', label: 'Image' },
  jpeg: { icon: 'image', colorClass: 'text-emerald-500', label: 'Image' },
  gif: { icon: 'image', colorClass: 'text-emerald-500', label: 'Image' },
  webp: { icon: 'image', colorClass: 'text-emerald-500', label: 'Image' },
  svg: { icon: 'image', colorClass: 'text-emerald-500', label: 'SVG' },
  ico: { icon: 'image', colorClass: 'text-emerald-500', label: 'Icon image' },
  js: { icon: 'javascript', colorClass: 'text-yellow-500', label: 'JavaScript' },
  jsx: { icon: 'javascript', colorClass: 'text-yellow-500', label: 'React JSX' },
  ts: { icon: 'code', colorClass: 'text-blue-500', label: 'TypeScript' },
  tsx: { icon: 'code', colorClass: 'text-blue-500', label: 'React TSX' },
  mjs: { icon: 'javascript', colorClass: 'text-yellow-500', label: 'JavaScript module' },
  cjs: { icon: 'javascript', colorClass: 'text-yellow-500', label: 'CommonJS module' },
  py: { icon: 'code', colorClass: 'text-emerald-600', label: 'Python' },
  java: { icon: 'code', colorClass: 'text-orange-600', label: 'Java' },
  kt: { icon: 'code', colorClass: 'text-purple-500', label: 'Kotlin' },
  kts: { icon: 'code', colorClass: 'text-purple-500', label: 'Kotlin script' },
  go: { icon: 'code', colorClass: 'text-cyan-500', label: 'Go' },
  rs: { icon: 'code', colorClass: 'text-orange-500', label: 'Rust' },
  rb: { icon: 'code', colorClass: 'text-red-500', label: 'Ruby' },
  php: { icon: 'code', colorClass: 'text-indigo-500', label: 'PHP' },
  cs: { icon: 'code', colorClass: 'text-purple-600', label: 'C#' },
  c: { icon: 'code', colorClass: 'text-sky-600', label: 'C' },
  h: { icon: 'code', colorClass: 'text-sky-600', label: 'Header' },
  cpp: { icon: 'code', colorClass: 'text-sky-600', label: 'C++' },
  hpp: { icon: 'code', colorClass: 'text-sky-600', label: 'C++ header' },
  swift: { icon: 'code', colorClass: 'text-orange-500', label: 'Swift' },
  sh: { icon: 'terminal', colorClass: 'text-cyan-500', label: 'Shell script' },
  bash: { icon: 'terminal', colorClass: 'text-cyan-500', label: 'Shell script' },
  zsh: { icon: 'terminal', colorClass: 'text-cyan-500', label: 'Shell script' },
  fish: { icon: 'terminal', colorClass: 'text-cyan-500', label: 'Shell script' },
  ps1: { icon: 'terminal', colorClass: 'text-cyan-500', label: 'PowerShell' },
  json: { icon: 'data_object', colorClass: 'text-amber-500', label: 'JSON' },
  jsonl: { icon: 'data_object', colorClass: 'text-amber-500', label: 'JSON Lines' },
  yaml: { icon: 'settings', colorClass: 'text-slate-500', label: 'YAML' },
  yml: { icon: 'settings', colorClass: 'text-slate-500', label: 'YAML' },
  toml: { icon: 'settings', colorClass: 'text-slate-500', label: 'TOML' },
  ini: { icon: 'settings', colorClass: 'text-slate-500', label: 'INI config' },
  conf: { icon: 'settings', colorClass: 'text-slate-500', label: 'Config' },
  cfg: { icon: 'settings', colorClass: 'text-slate-500', label: 'Config' },
  env: { icon: 'key', colorClass: 'text-amber-600', label: 'Environment' },
  html: { icon: 'web', colorClass: 'text-orange-500', label: 'HTML' },
  htm: { icon: 'web', colorClass: 'text-orange-500', label: 'HTML' },
  css: { icon: 'palette', colorClass: 'text-sky-500', label: 'CSS' },
  scss: { icon: 'palette', colorClass: 'text-pink-500', label: 'SCSS' },
  sass: { icon: 'palette', colorClass: 'text-pink-500', label: 'Sass' },
  less: { icon: 'palette', colorClass: 'text-blue-500', label: 'Less' },
  sql: { icon: 'database', colorClass: 'text-indigo-500', label: 'SQL' },
  db: { icon: 'database', colorClass: 'text-indigo-500', label: 'Database' },
  sqlite: { icon: 'database', colorClass: 'text-indigo-500', label: 'SQLite database' },
  zip: { icon: 'folder_zip', colorClass: 'text-amber-600', label: 'Archive' },
  gz: { icon: 'folder_zip', colorClass: 'text-amber-600', label: 'Archive' },
  tar: { icon: 'folder_zip', colorClass: 'text-amber-600', label: 'Archive' },
  rar: { icon: 'folder_zip', colorClass: 'text-amber-600', label: 'Archive' },
  '7z': { icon: 'folder_zip', colorClass: 'text-amber-600', label: 'Archive' },
  mp4: { icon: 'movie', colorClass: 'text-fuchsia-500', label: 'Video' },
  mov: { icon: 'movie', colorClass: 'text-fuchsia-500', label: 'Video' },
  webm: { icon: 'movie', colorClass: 'text-fuchsia-500', label: 'Video' },
  mp3: { icon: 'audio_file', colorClass: 'text-purple-500', label: 'Audio' },
  wav: { icon: 'audio_file', colorClass: 'text-purple-500', label: 'Audio' },
  flac: { icon: 'audio_file', colorClass: 'text-purple-500', label: 'Audio' },
  woff: { icon: 'font_download', colorClass: 'text-slate-500', label: 'Font' },
  woff2: { icon: 'font_download', colorClass: 'text-slate-500', label: 'Font' },
  ttf: { icon: 'font_download', colorClass: 'text-slate-500', label: 'Font' },
};

function basename(fileNameOrPath: string): string {
  return fileNameOrPath.split('/').pop() || fileNameOrPath;
}

function extensionFor(fileNameOrPath: string): string {
  const name = basename(fileNameOrPath).toLowerCase();
  const index = name.lastIndexOf('.');

  if (index <= 0 || index === name.length - 1) {
    return '';
  }

  return name.slice(index + 1);
}

export function getFileIconMeta(fileNameOrPath: string, options: FileIconOptions = {}): FileIconMeta {
  if (options.isDirectory) {
    return options.isExpanded ? OPEN_DIRECTORY_ICON : DIRECTORY_ICON;
  }

  const name = basename(fileNameOrPath).toLowerCase();
  const nameWithoutExtension = name.replace(/\.[^.]+$/, '');
  const extension = extensionFor(fileNameOrPath);

  return (
    FILENAME_ICON_MAP[name] ||
    FILENAME_ICON_MAP[nameWithoutExtension] ||
    EXTENSION_ICON_MAP[extension] ||
    (options.fileType ? FALLBACK_TYPE_ICONS[options.fileType] : undefined) ||
    DEFAULT_FILE_ICON
  );
}
