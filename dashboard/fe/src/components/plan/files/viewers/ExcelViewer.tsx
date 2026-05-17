'use client';

import { useState, useEffect } from 'react';
import readExcelFile, { type Sheet as ParsedXlsxSheet, type SheetData as ParsedSheetData } from 'read-excel-file/browser';
import { base64ToUint8Array } from './utils';

interface SheetData {
  name: string;
  headers: string[];
  rows: string[][];
  truncated_rows?: boolean;
  truncated_cols?: boolean;
  total_rows?: number;
}

interface ExcelViewerProps {
  data: string;
  encoding: 'utf-8' | 'base64';
  extension: string;
}

// P2-16: Limits to prevent browser DoS from huge spreadsheets
const MAX_ROWS = 1000;
const MAX_COLS = 50;

type SpreadsheetCell = ParsedSheetData[number][number];

function cellToString(cell: SpreadsheetCell): string {
  if (cell === null || cell === undefined) return '';
  if (cell instanceof Date) return cell.toISOString();
  return String(cell);
}

function rowsToSheet(name: string, rows: ParsedSheetData): SheetData {
  const trimmed = rows.slice(0, MAX_ROWS).map((row) =>
    row.slice(0, MAX_COLS).map(cellToString)
  );
  const headers = trimmed.length > 0 ? trimmed[0] : [];
  const dataRows = trimmed.slice(1);
  const truncated_rows = rows.length > MAX_ROWS;
  const truncated_cols = rows.some((row) => row.length > MAX_COLS);

  return {
    name,
    headers,
    rows: dataRows,
    truncated_rows,
    truncated_cols,
    total_rows: Math.max(0, rows.length - 1),
  };
}

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const bytes = base64ToUint8Array(base64);
  return uint8ArrayToArrayBuffer(bytes);
}

function uint8ArrayToArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const buffer = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(buffer).set(bytes);
  return buffer;
}

function parseDelimitedRows(text: string, delimiter: ',' | '\t'): string[][] {
  if (!text) return [];

  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let inQuotes = false;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    const next = text[i + 1];

    if (inQuotes) {
      if (char === '"' && next === '"') {
        cell += '"';
        i++;
      } else if (char === '"') {
        inQuotes = false;
      } else {
        cell += char;
      }
      continue;
    }

    if (char === '"') {
      inQuotes = true;
    } else if (char === delimiter) {
      row.push(cell);
      cell = '';
    } else if (char === '\n' || char === '\r') {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
      if (char === '\r' && next === '\n') i++;
    } else {
      cell += char;
    }
  }

  row.push(cell);
  rows.push(row);
  return rows;
}

async function parseSpreadsheet(data: string, encoding: 'utf-8' | 'base64', extension: string): Promise<SheetData[]> {
  if (extension === 'csv' || extension === 'tsv') {
    const text = encoding === 'base64'
      ? new TextDecoder().decode(base64ToUint8Array(data))
      : data;
    return [rowsToSheet(extension.toUpperCase(), parseDelimitedRows(text, extension === 'tsv' ? '\t' : ','))];
  }

  if (extension === 'xls') {
    throw new Error('Legacy .xls previews are disabled because the previous parser had unpatched vulnerabilities. Convert the file to .xlsx, .csv, or .tsv to preview it.');
  }

  const input = encoding === 'base64'
    ? base64ToArrayBuffer(data)
    : uint8ArrayToArrayBuffer(new TextEncoder().encode(data));
  const sheets: ParsedXlsxSheet[] = await readExcelFile(input);
  return sheets.map((sheet) => rowsToSheet(sheet.sheet, sheet.data));
}

export default function ExcelViewer({ data, encoding, extension }: ExcelViewerProps) {
  const [sheets, setSheets] = useState<SheetData[]>([]);
  const [activeSheet, setActiveSheet] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setSheets([]);
    setActiveSheet(0);

    parseSpreadsheet(data, encoding, extension)
      .then((parsed) => {
        if (!cancelled) setSheets(parsed);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to parse spreadsheet');
      });

    return () => {
      cancelled = true;
    };
  }, [data, encoding, extension]);

  const sheet = sheets[activeSheet];

  if (error) {
    return (
      <div className="p-8 text-center text-danger">
        <span className="material-symbols-outlined text-3xl mb-2 block">error</span>
        <p className="text-sm font-bold">Failed to parse spreadsheet</p>
        <p className="text-xs mt-1 text-text-muted">{error}</p>
      </div>
    );
  }

  if (sheets.length === 0) {
    return (
      <div className="flex items-center justify-center py-12">
        <span className="material-symbols-outlined text-primary animate-spin">progress_activity</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {sheets.length > 1 && (
        <div className="flex items-center gap-1 px-4 py-1.5 border-b border-border bg-surface/50 shrink-0 overflow-x-auto">
          {sheets.map((s, i) => (
            <button
              key={s.name}
              onClick={() => setActiveSheet(i)}
              className={`px-2.5 py-1 rounded-md text-[11px] font-bold transition-colors whitespace-nowrap ${
                i === activeSheet
                  ? 'bg-primary text-white'
                  : 'text-text-faint hover:text-text-muted hover:bg-surface-hover'
              }`}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}
      <div className="flex-1 overflow-auto custom-scrollbar">
        {sheet && (
          <table className="w-full border-collapse text-[12px]">
            <thead className="sticky top-0 z-10">
              <tr>
                <th className="px-2 py-1.5 border border-border bg-surface text-text-faint font-mono text-[10px] text-center w-8">
                  #
                </th>
                {sheet.headers.map((h, i) => (
                  <th
                    key={i}
                    className="px-3 py-1.5 border border-border bg-surface text-left text-[11px] font-bold text-text-muted whitespace-nowrap"
                  >
                    {h || `Col ${i + 1}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sheet.rows.map((row, ri) => (
                <tr key={ri} className="hover:bg-surface-hover/30">
                  <td className="px-2 py-1 border border-border bg-surface/50 text-text-faint/40 font-mono text-[10px] text-center">
                    {ri + 1}
                  </td>
                  {sheet.headers.map((_, ci) => (
                    <td
                      key={ci}
                      className="px-3 py-1 border border-border text-text-main whitespace-nowrap max-w-[300px] truncate"
                    >
                      {row[ci] ?? ''}
                    </td>
                  ))}
                </tr>
              ))}
              {sheet.rows.length === 0 && (
                <tr>
                  <td
                    colSpan={sheet.headers.length + 1}
                    className="px-4 py-8 text-center text-text-faint text-xs"
                  >
                    No data rows
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
      {sheet && (
        <div className="px-4 py-1.5 border-t border-border bg-surface/50 text-[10px] text-text-faint shrink-0">
          {sheet.rows.length} row{sheet.rows.length !== 1 ? 's' : ''} · {sheet.headers.length} column{sheet.headers.length !== 1 ? 's' : ''}
          {(sheet.truncated_rows || sheet.truncated_cols) && (
            <span className="ml-2 px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-500">
              TRUNCATED{sheet.truncated_rows ? ` (${sheet.total_rows} total rows, showing ${MAX_ROWS})` : ''}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
