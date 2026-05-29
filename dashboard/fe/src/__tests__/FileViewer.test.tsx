import React from 'react';
import { render, screen } from '@testing-library/react';
import FileViewer from '../components/plan/files/FileViewer';
import { useFileContent } from '../hooks/use-files';
import { vi, describe, it, expect, beforeEach, type Mock } from 'vitest';

vi.mock('../hooks/use-files', () => ({
  useFileContent: vi.fn(),
}));

const makeContent = (overrides: Record<string, unknown> = {}) => ({
  path: 'src/main.ts',
  content: 'console.log("hello world");',
  encoding: 'utf-8',
  size: 27,
  mime_type: 'text/typescript',
  truncated: false,
  download_url: '/api/plans/plan-001/files/download?path=src/main.ts',
  ...overrides,
});

describe('FileViewer Component', () => {
  const planId = 'plan-001';

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders empty state when no path is selected', () => {
    (useFileContent as Mock).mockReturnValue({
      content: undefined,
      isLoading: false,
      isError: undefined,
    });

    render(<FileViewer planId={planId} path={null} />);
    expect(screen.getByText('Select a file to view its content')).toBeInTheDocument();
  });

  it('renders loading state', () => {
    (useFileContent as Mock).mockReturnValue({
      content: undefined,
      isLoading: true,
      isError: undefined,
    });

    render(<FileViewer planId={planId} path="src/main.ts" />);
    const container = document.querySelector('.animate-pulse');
    expect(container).toBeTruthy();
  });

  it('renders error state when fetch fails', () => {
    (useFileContent as Mock).mockReturnValue({
      content: undefined,
      isLoading: false,
      isError: new Error('Not found'),
    });

    render(<FileViewer planId={planId} path="src/missing.ts" />);
    expect(screen.getByText('Failed to load file')).toBeInTheDocument();
    expect(screen.getByText('src/missing.ts')).toBeInTheDocument();
  });

  it('renders error state when content is null', () => {
    (useFileContent as Mock).mockReturnValue({
      content: null,
      isLoading: false,
      isError: undefined,
    });

    render(<FileViewer planId={planId} path="src/empty.ts" />);
    expect(screen.getByText('Failed to load file')).toBeInTheDocument();
  });

  it('renders text file content', () => {
    (useFileContent as Mock).mockReturnValue({
      content: makeContent(),
      isLoading: false,
      isError: undefined,
    });

    render(<FileViewer planId={planId} path="src/main.ts" />);
    expect(screen.getByText('main.ts')).toBeInTheDocument();
    expect(screen.getByTitle('TypeScript')).toHaveTextContent('code');
    expect(document.querySelector('.hljs')).toBeTruthy();
  });

  it('renders file size information', () => {
    (useFileContent as Mock).mockReturnValue({
      content: makeContent({ content: 'hello', size: 5, mime_type: 'text/plain' }),
      isLoading: false,
      isError: undefined,
    });

    render(<FileViewer planId={planId} path="src/main.ts" />);
    expect(screen.getByText('5 B')).toBeInTheDocument();
  });

  it('renders truncated indicator when file is truncated', () => {
    (useFileContent as Mock).mockReturnValue({
      content: makeContent({
        path: 'src/big.ts',
        content: 'partial content...',
        size: 1000000,
        mime_type: 'text/typescript',
        truncated: true,
      }),
      isLoading: false,
      isError: undefined,
    });

    render(<FileViewer planId={planId} path="src/big.ts" />);
    expect(screen.getByText('TRUNCATED')).toBeInTheDocument();
  });

  it('renders binary file message for base64 non-image content', () => {
    (useFileContent as Mock).mockReturnValue({
      content: makeContent({
        path: 'data.bin',
        content: 'AQID',
        encoding: 'base64',
        size: 3,
        mime_type: 'application/octet-stream',
      }),
      isLoading: false,
      isError: undefined,
    });

    render(<FileViewer planId={planId} path="data.bin" />);
    expect(screen.getByText('Binary File')).toBeInTheDocument();
    expect(screen.getByText('This file cannot be displayed as text.')).toBeInTheDocument();
    expect(screen.getByText('Download File')).toBeInTheDocument();
  });

  it('renders image for image mime types', () => {
    (useFileContent as Mock).mockReturnValue({
      content: makeContent({
        path: 'logo.png',
        content: 'iVBORw0KGgoAAAANSUhEUg==',
        encoding: 'base64',
        size: 100,
        mime_type: 'image/png',
      }),
      isLoading: false,
      isError: undefined,
    });

    render(<FileViewer planId={planId} path="logo.png" />);
    const img = screen.getByAltText('logo.png');
    expect(img).toBeInTheDocument();
    expect(img.getAttribute('src')).toContain('data:image/png;base64,');
  });

  it('renders large file fallback when content is null and truncated', () => {
    (useFileContent as Mock).mockReturnValue({
      content: makeContent({
        path: 'big.pdf',
        content: null,
        encoding: 'base64',
        size: 5 * 1024 * 1024,
        mime_type: 'application/pdf',
        truncated: true,
      }),
      isLoading: false,
      isError: undefined,
    });

    render(<FileViewer planId={planId} path="big.pdf" />);
    expect(screen.getByTitle('PDF')).toHaveTextContent('picture_as_pdf');
    expect(screen.getByText('File too large to preview')).toBeInTheDocument();
    expect(screen.getByText(/exceeds the 2 MB preview limit/)).toBeInTheDocument();
    expect(screen.getByText('Download File').closest('a')?.getAttribute('href')).toContain('/download');
  });

  it('renders TOO LARGE badge for truncated null-content files', () => {
    (useFileContent as Mock).mockReturnValue({
      content: makeContent({
        path: 'huge.bin',
        content: null,
        encoding: 'base64',
        size: 10 * 1024 * 1024,
        mime_type: 'application/octet-stream',
        truncated: true,
      }),
      isLoading: false,
      isError: undefined,
    });

    render(<FileViewer planId={planId} path="huge.bin" />);
    expect(screen.getByText('TOO LARGE')).toBeInTheDocument();
  });

  it('binary fallback download link uses download_url from API', () => {
    (useFileContent as Mock).mockReturnValue({
      content: makeContent({
        path: 'data.bin',
        content: 'AQID',
        encoding: 'base64',
        size: 3,
        mime_type: 'application/octet-stream',
        download_url: '/api/plans/plan-001/files/download?path=data.bin',
      }),
      isLoading: false,
      isError: undefined,
    });

    render(<FileViewer planId={planId} path="data.bin" />);
    const link = screen.getByText('Download File').closest('a');
    expect(link).toBeTruthy();
    expect(link?.getAttribute('href')).toBe('/api/plans/plan-001/files/download?path=data.bin');
    expect(link?.hasAttribute('download')).toBe(true);
  });
});
