import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import readExcelFile from 'read-excel-file/browser';
import ExcelViewer from '../components/plan/files/viewers/ExcelViewer';

vi.mock('read-excel-file/browser', () => ({
  default: vi.fn(),
}));

describe('ExcelViewer', () => {
  const readExcelFileMock = vi.mocked(readExcelFile);

  beforeEach(() => {
    readExcelFileMock.mockReset();
  });

  it('previews CSV data without loading the xlsx parser path', async () => {
    render(<ExcelViewer data={'Name,Cost\nOps,12'} encoding="utf-8" extension="csv" />);

    expect(await screen.findByText('Name')).toBeInTheDocument();
    expect(screen.getByText('Ops')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(readExcelFileMock).not.toHaveBeenCalled();
  });

  it('previews XLSX data through read-excel-file', async () => {
    readExcelFileMock.mockResolvedValue([
      {
        sheet: 'Budget',
        data: [
          ['Name', 'Cost'],
          ['Ops', 12],
        ],
      },
    ]);

    render(<ExcelViewer data={Buffer.from('fake-xlsx').toString('base64')} encoding="base64" extension="xlsx" />);

    expect(await screen.findByText('Name')).toBeInTheDocument();
    expect(screen.getByText('Ops')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(readExcelFileMock).toHaveBeenCalledTimes(1);
    expect(readExcelFileMock.mock.calls[0][0]).toBeInstanceOf(ArrayBuffer);
  });

  it('rejects legacy XLS previews instead of using the vulnerable SheetJS package', async () => {
    render(<ExcelViewer data="unused" encoding="utf-8" extension="xls" />);

    expect(await screen.findByText('Failed to parse spreadsheet')).toBeInTheDocument();
    expect(screen.getByText(/Legacy \.xls previews are disabled/)).toBeInTheDocument();
    expect(readExcelFileMock).not.toHaveBeenCalled();
  });
});
