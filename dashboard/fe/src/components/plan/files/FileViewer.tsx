'use client';

import { useFileContent } from '@/hooks/use-files';
import CodeViewer from './viewers/CodeViewer';
import MarkdownViewer from './viewers/MarkdownViewer';
import PdfViewer from './viewers/PdfViewer';
import DocxViewer from './viewers/DocxViewer';
import ExcelViewer from './viewers/ExcelViewer';

interface FileViewerProps {
  planId: string;
  path: string | null;
}

type FileType = 'image' | 'markdown' | 'code' | 'pdf' | 'docx' | 'excel' | 'binary';

const CODE_EXTENSIONS = new Set([
  'js', 'jsx', 'ts', 'tsx', 'py', 'rb', 'go', 'rs', 'java', 'c', 'cpp', 'h', 'cs',
  'php', 'swift', 'kt', 'scala', 'sh', 'bash', 'zsh', 'fish', 'ps1',
  'json', 'yml', 'yaml', 'toml', 'ini', 'cfg', 'conf', 'env',
  'css', 'scss', 'sass', 'less', 'html', 'htm', 'xml', 'svg',
  'sql', 'graphql', 'proto', 'tf', 'dockerfile',
  'gitignore', 'editorconfig', 'eslintrc', 'prettierrc',
  'lua', 'r', 'm', 'mm', 'pl', 'ex', 'exs', 'erl', 'hs', 'ml', 'fs',
  'vim', 'el', 'clj', 'v', 'sv', 'vhd',
]);

const CODE_FILENAMES = new Set([
  'Makefile', 'Dockerfile', 'Vagrantfile', 'Gemfile', 'Rakefile',
  'Jenkinsfile', '.gitignore', '.env', '.editorconfig', '.eslintrc',
  '.prettierrc', '.babelrc', '.npmrc', '.nvmrc',
]);

function getFileType(path: string, mimeType: string, encoding: string): FileType {
  const ext = path.split('.').pop()?.toLowerCase() || '';
  const filename = path.split('/').pop() || '';

  if (mimeType.startsWith('image/')) return 'image';
  if (mimeType === 'application/pdf') return 'pdf';

  if (
    mimeType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
    ext === 'docx'
  ) return 'docx';

  if (
    mimeType === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' ||
    mimeType === 'application/vnd.ms-excel' ||
    ext === 'xlsx' || ext === 'xls' || ext === 'csv' || ext === 'tsv'
  ) return 'excel';

  if (encoding === 'utf-8') {
    if (ext === 'md' || ext === 'markdown') return 'markdown';
    if (CODE_EXTENSIONS.has(ext) || CODE_FILENAMES.has(filename)) return 'code';
    if (mimeType.startsWith('text/')) return 'code';
  }

  if (encoding === 'base64') {
    if (ext === 'pdf') return 'pdf';
    if (ext === 'docx' || ext === 'doc') return 'docx';
    if (ext === 'xlsx' || ext === 'xls' || ext === 'csv' || ext === 'tsv') return 'excel';
    return 'binary';
  }

  return 'code';
}

function getFileIcon(fileType: FileType): string {
  switch (fileType) {
    case 'image': return 'image';
    case 'markdown': return 'article';
    case 'pdf': return 'picture_as_pdf';
    case 'docx': return 'description';
    case 'excel': return 'table';
    case 'code': return 'code';
    case 'binary': return 'binary';
  }
}

function getFileLabel(fileType: FileType): string {
  switch (fileType) {
    case 'image': return 'Image';
    case 'markdown': return 'Markdown';
    case 'pdf': return 'PDF';
    case 'docx': return 'DOCX';
    case 'excel': return 'Spreadsheet';
    case 'code': return 'Code';
    case 'binary': return 'Binary';
  }
}

export default function FileViewer({ planId, path }: FileViewerProps) {
  const { content, isLoading, isError } = useFileContent(planId, path);

  if (!path) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-background/50 text-text-faint">
        <span className="material-symbols-outlined text-4xl mb-2">draft</span>
        <p className="text-xs font-medium">Select a file to view its content</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex-1 flex flex-col p-4 space-y-4 animate-pulse">
        <div className="h-6 w-1/3 bg-border/20 rounded" />
        <div className="h-full bg-border/10 rounded" />
      </div>
    );
  }

  if (isError || !content) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-danger p-8">
        <span className="material-symbols-outlined text-4xl mb-2">error</span>
        <p className="text-sm font-bold">Failed to load file</p>
        <p className="text-xs mt-1 text-text-muted">{path}</p>
      </div>
    );
  }

  if (content.truncated && content.content === null) {
    const fileType = getFileType(path, content.mime_type, content.encoding || 'utf-8');
    return (
      <div className="flex-1 flex flex-col overflow-hidden bg-surface/30">
        <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface shrink-0">
          <div className="flex items-center gap-2 overflow-hidden">
            <span className="material-symbols-outlined text-[18px] text-text-muted shrink-0">
              {getFileIcon(fileType)}
            </span>
            <span className="text-xs font-bold text-text-main truncate" title={path}>
              {path.split('/').pop()}
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-500 font-mono uppercase">
              TOO LARGE
            </span>
          </div>
          <div className="flex items-center gap-2 text-[10px] font-bold text-text-faint">
            <span>{formatSize(content.size)}</span>
          </div>
        </div>
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="p-6 rounded-2xl bg-surface border border-border flex flex-col items-center gap-3">
            <span className="material-symbols-outlined text-4xl text-text-faint">cloud_download</span>
            <div className="text-center">
              <p className="text-sm font-bold text-text-main">File too large to preview</p>
              <p className="text-xs text-text-muted mt-1">
                {formatSize(content.size)} exceeds the 2 MB preview limit
              </p>
            </div>
            <a
              href={content.download_url.startsWith('/api/') ? content.download_url : '#'}
              download
              className="px-4 py-2 bg-primary text-white text-xs font-bold rounded-lg shadow-sm hover:bg-primary-hover transition-colors"
            >
              Download File
            </a>
          </div>
        </div>
      </div>
    );
  }

  const fileType = getFileType(path, content.mime_type, content.encoding || 'utf-8');

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-surface/30">
      <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface shrink-0">
        <div className="flex items-center gap-2 overflow-hidden">
          <span className="material-symbols-outlined text-[18px] text-text-muted shrink-0">
            {getFileIcon(fileType)}
          </span>
          <span className="text-xs font-bold text-text-main truncate" title={path}>
            {path.split('/').pop()}
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-border/50 text-text-faint font-mono uppercase">
            {getFileLabel(fileType)}
          </span>
        </div>
        <div className="flex items-center gap-2 text-[10px] font-bold text-text-faint">
          <span>{formatSize(content.size)}</span>
          {content.truncated && (
            <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-500">TRUNCATED</span>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-auto custom-scrollbar">
        {fileType === 'image' ? (
          <div className="h-full flex items-center justify-center p-8">
            <img
              src={`data:${content.mime_type};base64,${content.content}`}
              alt={path}
              className="max-w-full max-h-full object-contain shadow-2xl rounded border border-border"
            />
          </div>
        ) : fileType === 'markdown' ? (
          <MarkdownViewer content={content.content as string} />
        ) : fileType === 'code' ? (
          <CodeViewer content={content.content as string} path={path} />
        ) : fileType === 'pdf' ? (
          <PdfViewer base64Data={content.content as string} />
        ) : fileType === 'docx' ? (
          <DocxViewer base64Data={content.content as string} />
        ) : fileType === 'excel' ? (
          <ExcelViewer
            data={content.content as string}
            encoding={(content.encoding as 'utf-8' | 'base64') || 'base64'}
            extension={path.split('.').pop()?.toLowerCase() || ''}
          />
        ) : (
          <BinaryFallback mimeType={content.mime_type} path={path} downloadUrl={content.download_url} />
        )}
      </div>
    </div>
  );
}

function BinaryFallback({ mimeType, path, downloadUrl }: { mimeType: string; path: string; downloadUrl: string }) {
  // Validate download_url is a same-origin relative path to prevent open redirect
  const safeUrl = downloadUrl.startsWith('/api/') ? downloadUrl : '#';
  return (
    <div className="p-8 flex flex-col items-center justify-center gap-4">
      <div className="p-6 rounded-2xl bg-surface border border-border flex flex-col items-center gap-3">
        <span className="material-symbols-outlined text-4xl text-text-faint">binary</span>
        <div className="text-center">
          <p className="text-sm font-bold text-text-main">Binary File</p>
          <p className="text-xs text-text-muted mt-1">This file cannot be displayed as text.</p>
        </div>
        <a
          href={safeUrl}
          download
          className="px-4 py-2 bg-primary text-white text-xs font-bold rounded-lg shadow-sm hover:bg-primary-hover transition-colors"
        >
          Download File
        </a>
      </div>
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}
