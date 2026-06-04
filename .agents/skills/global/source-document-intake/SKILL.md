---
name: source-document-intake
description: "Use when reading, extracting, summarizing, or citing source documents such as PDFs, DOCX, Office files, spreadsheets, plain text, Markdown, HTML, images, or scanned documents. Provides extraction priority, provenance output, and citation discipline for any source-heavy analysis task."
tags: [documents, pdf, docx, ocr, provenance, source-verification, intake, spreadsheets]
trust_level: community
category: Research
enabled: true
applicable_roles: [audit, qa, manager, staff-manager, reporter, knowledge-curator, researcher, security-engineer]
---

# Source Document Intake

Use this skill whenever an analysis task depends on user-provided files, contracts, PDFs, DOCX, spreadsheets, exhibits, filings, policies, research papers, or any source document that must be read before it can be cited, quoted, or relied upon.

**Do not use this skill for producing or editing output documents** (polished reports, Word deliverables, formatted filings). For those, use the reporter/docx or equivalent output skills.

## Trigger Conditions

Apply this skill when the task involves:
- Reading, extracting, or summarizing a file the user has provided or that exists on disk.
- Quoting, paraphrasing, or citing content from a source document.
- Evidence or exhibit review, contract analysis, legal or compliance review, research synthesis.
- Any workflow where incomplete or missing source access would change the conclusion.

## Extraction Priority

### Text-based PDFs
1. Prefer `pdftotext -layout <file> -` when available — preserves column layout and is fast.
2. Fall back to direct per-file extraction via the project MarkItDown parser (e.g., `MarkitdownReader.read()` or `MarkItDown().convert(path)`) if `pdftotext` is unavailable. Note: `knowledge_import_folder` is a bulk namespace-indexing job and is not a substitute for per-source extraction.
3. For table-dense PDFs where layout matters, use a table-aware path only if it is explicitly available.
4. If the PDF is image-only or mixed-scan, mark it **OCR-needed** (see Images section below).

### DOCX / Office XML (`.docx`, `.pptx`)
1. Prefer the project MarkItDown parser for standard content extraction.
2. Use raw Office XML package inspection only when the task specifically requires tracked changes, comments, metadata, or structure-sensitive review that MarkItDown flattens; for example `word/document.xml` for DOCX or `ppt/slides/slide*.xml` for PPTX.
3. Never unpack just to read prose — that is slower and adds failure modes.

### Legacy `.doc` / `.ppt` / `.xls`
- These formats require conversion tooling (e.g., LibreOffice `soffice --convert-to docx`).
- If conversion tooling is unavailable, mark the file **conversion-needed** and do not attempt to read binary content directly.

### Spreadsheets (`.xlsx`, `.xls`, `.csv`)
- Use the project MarkItDown parser or structured CSV/text extraction.
- **Preserve workbook, sheet, table, row, and column context.** Do not silently flatten multi-sheet workbooks into a single stream — state which sheet(s) were read and which were not.
- Report sheet names, approximate row counts, and whether all sheets were accessed.

### Images and Scanned PDFs
- If no OCR or vision capability is explicitly available and approved, mark the file **OCR-needed** and do not attempt to summarize visual content.
- If vision/OCR is available through the project's configured MarkItDown vision/OCR client (set via project LLM configuration), note that it was used and report confidence limitations.
- Never describe or quote image content that was not actually processed.

### Plain Text, Markdown, HTML, JSON, YAML, CSV
- Read directly with UTF-8 encoding. Use structured extraction for HTML (strip tags) and JSON/YAML (key-path access).
- **Windows / Vietnamese text rule:** use UTF-8-safe commands and environment settings. Do not assume ASCII or latin-1; flag encoding errors rather than silently dropping non-ASCII characters.

## Required Provenance Output

For every source document opened, record:

| Field | Value |
|---|---|
| **File** | path or name |
| **Extraction method** | e.g., `pdftotext`, `MarkItDown`, `raw XML`, `structured CSV`, `OCR/vision` |
| **Read coverage** | `complete` / `partial` / `sampled` / `excerpt-only` / `OCR-needed` / `conversion-needed` / `failed` |
| **Page / section / sheet refs** | where available (e.g., "pp. 3–7", "Sheet: Revenue Q1", "§ 4.2") |
| **Limitations** | unreadable pages, password-protected sections, encoding errors, truncation |

For high-stakes analysis (legal, compliance, evidence review), add:

> **Source sufficiency:** `sufficient` | `limited` | `blocked`
> - `sufficient` — all material sections were extracted and are available to quote.
> - `limited` — some sections missing; conclusions may be incomplete.
> - `blocked` — key source(s) not opened; analysis cannot proceed without them.

## Core Citation Rule

**Never quote, cite, summarize, or rely on content from a document that was not actually opened and extracted in this session.**

If a document is named but not opened:
- Mark all assertions about it `[not opened — verify]`.
- Produce only an intake/source-request note for that file.
- Do not reconstruct content from memory, training data, or prior context.

## Safety Rule

Do not:
- Install dependencies, run global installers, or modify the environment without explicit user approval.
- Upload, copy, or transmit documents to external services, APIs, or web tools not already authorised in the workflow.
- Use logged-in browser profiles or authenticated automation to access documents without explicit user approval.
- Attempt to bypass password protection or DRM.
