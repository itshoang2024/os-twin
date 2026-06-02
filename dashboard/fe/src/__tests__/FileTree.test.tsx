import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import FileTree from '../components/plan/files/FileTree';
import { useFileTree, useFileList } from '../hooks/use-files';
import { vi, describe, it, expect, beforeEach, type Mock } from 'vitest';

vi.mock('../hooks/use-files', () => ({
  useFileTree: vi.fn(),
  useFileList: vi.fn(),
}));

describe('FileTree Component', () => {
  const mockOnSelectFile = vi.fn();
  const planId = 'plan-001';

  beforeEach(() => {
    vi.clearAllMocks();
    (useFileList as Mock).mockReturnValue({
      entries: [],
      isLoading: false,
      isError: undefined,
    });
  });

  it('renders loading state', () => {
    (useFileTree as Mock).mockReturnValue({
      tree: undefined,
      isLoading: true,
      isError: undefined,
    });

    render(<FileTree planId={planId} onSelectFile={mockOnSelectFile} selectedPath={null} />);
    expect(screen.getByText('Loading tree...')).toBeInTheDocument();
  });

  it('renders error state', () => {
    (useFileTree as Mock).mockReturnValue({
      tree: undefined,
      isLoading: false,
      isError: new Error('Failed'),
    });

    render(<FileTree planId={planId} onSelectFile={mockOnSelectFile} selectedPath={null} />);
    expect(screen.getByText('Error loading tree')).toBeInTheDocument();
  });

  it('renders file entries', () => {
    (useFileTree as Mock).mockReturnValue({
      tree: [
        { name: 'README.md', type: 'file', path: 'README.md' },
        { name: 'package.json', type: 'file', path: 'package.json' },
      ],
      isLoading: false,
      isError: undefined,
    });

    render(<FileTree planId={planId} onSelectFile={mockOnSelectFile} selectedPath={null} />);
    expect(screen.getByText('README.md')).toBeInTheDocument();
    expect(screen.getByText('package.json')).toBeInTheDocument();
  });

  it('renders extension-specific file icons', () => {
    (useFileTree as Mock).mockReturnValue({
      tree: [
        { name: 'README.md', type: 'file', path: 'README.md', extension: '.md' },
        { name: 'package.json', type: 'file', path: 'package.json', extension: '.json' },
        { name: 'logo.png', type: 'file', path: 'logo.png', extension: '.png' },
      ],
      isLoading: false,
      isError: undefined,
    });

    render(<FileTree planId={planId} onSelectFile={mockOnSelectFile} selectedPath={null} />);

    expect(screen.getByTitle('Markdown')).toHaveTextContent('article');
    expect(screen.getByTitle('Package manifest')).toHaveTextContent('deployed_code');
    expect(screen.getByTitle('Image')).toHaveTextContent('image');
  });

  it('renders directory entries', () => {
    (useFileTree as Mock).mockReturnValue({
      tree: [
        {
          name: 'src',
          type: 'directory',
          path: 'src',
          children: [
            { name: 'index.ts', type: 'file', path: 'src/index.ts' },
          ],
        },
      ],
      isLoading: false,
      isError: undefined,
    });

    render(<FileTree planId={planId} onSelectFile={mockOnSelectFile} selectedPath={null} />);
    expect(screen.getByText('src')).toBeInTheDocument();
  });

  it('calls onSelectFile when a file is clicked', () => {
    (useFileTree as Mock).mockReturnValue({
      tree: [
        { name: 'README.md', type: 'file', path: 'README.md' },
      ],
      isLoading: false,
      isError: undefined,
    });

    render(<FileTree planId={planId} onSelectFile={mockOnSelectFile} selectedPath={null} />);
    fireEvent.click(screen.getByText('README.md'));
    expect(mockOnSelectFile).toHaveBeenCalledWith('README.md');
  });

  it('expands a directory on click', () => {
    (useFileTree as Mock).mockReturnValue({
      tree: [
        {
          name: 'src',
          type: 'directory',
          path: 'src',
          children: [
            { name: 'main.ts', type: 'file', path: 'src/main.ts' },
          ],
        },
      ],
      isLoading: false,
      isError: undefined,
    });

    render(<FileTree planId={planId} onSelectFile={mockOnSelectFile} selectedPath={null} />);

    // The root directory '.' is expanded by default, but 'src' is not
    // Click on 'src' to expand it
    fireEvent.click(screen.getByText('src'));

    // After expanding, child should be visible
    expect(screen.getByText('main.ts')).toBeInTheDocument();
  });

  it('renders "Project Files" header', () => {
    (useFileTree as Mock).mockReturnValue({
      tree: [],
      isLoading: false,
      isError: undefined,
    });

    render(<FileTree planId={planId} onSelectFile={mockOnSelectFile} selectedPath={null} />);
    expect(screen.getByText('Project Files')).toBeInTheDocument();
  });
});
