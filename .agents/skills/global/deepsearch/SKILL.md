---
name: deepsearch
description: Deep search across the SearXNG Search API and local/downloaded files; fetch URLs, download reports or data files, grep evidence, and prepare artifacts for brain-ops Knowledge/Memory. Use when users ask to search, research, crawl, download files, find data, inspect local evidence, or gather sources for an agent team.
---

# Deepsearch

## Purpose

Deepsearch replaces the separate `searxng-search` and `searxng-research` skills with one evidence workflow:

- Query the SearXNG Search API at `/search` or `/` with GET or POST.
- Return compact `markdown`, `json`, `urls`, or raw SearXNG `json/csv/rss` responses.
- Fetch result URLs into a reproducible artifact folder.
- Save any file type by default, including PDFs, spreadsheets, images, archives, and HTML.
- Extract text sidecars for HTML and grep all text-like local artifacts.
- Hand off durable evidence to brain-ops Knowledge and operational findings to Memory.

Use Deepsearch when the task needs private/local metasearch, source discovery, downloaded reports, local evidence scans, or artifact preparation for a multi-agent team.

## Command

Run from the repository root:

```bash
python3 .agents/skills/global/deepsearch/scripts/deepsearch.py "query"
```

Default SearXNG base URL is `http://localhost:6633`. Override with `SEARXNG_BASE_URL` or `--base-url`.

## SearXNG Search API

Deepsearch maps directly onto the SearXNG Search API:

- Endpoints: `--endpoint /search` or `--endpoint /`.
- Methods: `--method GET` or `--method POST`.
- Required parameter: `query` maps to SearXNG `q`.
- API format: `--search-format json|csv|rss` maps to SearXNG `format`.
- Search controls: `--categories`, `--engines`, `--language`, `--page/--pageno`, `--time-range`, `--safe-search/--safesearch`.
- Optional UI/plugin controls: `--results-on-new-tab`, `--image-proxy`, `--autocomplete`, `--theme`, `--enabled-plugins`, `--disabled-plugins`, `--enabled-engines`, `--disabled-engines`.

Deepsearch fetch, grep, markdown, and URL output require `--search-format json` because they parse SearXNG result objects. Use `--output raw --search-format csv|rss` to return raw API output.

## Common Workflows

Quick web search:

```bash
python3 .agents/skills/global/deepsearch/scripts/deepsearch.py \
  "openai responses api structured outputs" \
  --limit 8 \
  --output markdown
```

POST to the root API endpoint:

```bash
python3 .agents/skills/global/deepsearch/scripts/deepsearch.py \
  "site:sec.gov annual report 2025 filetype:pdf" \
  --method POST \
  --endpoint / \
  --output urls
```

Return raw CSV from SearXNG when that format is enabled:

```bash
python3 .agents/skills/global/deepsearch/scripts/deepsearch.py \
  "searxng" \
  --search-format csv \
  --output raw
```

Download and grep evidence:

```bash
python3 .agents/skills/global/deepsearch/scripts/deepsearch.py \
  '2025 sustainability report revenue filetype:pdf OR filetype:xlsx' \
  --fetch \
  --out ./research/reports \
  --types all \
  --grep 'revenue|net income|annual report' \
  --output json
```

Search existing local artifacts or data folders:

```bash
python3 .agents/skills/global/deepsearch/scripts/deepsearch.py \
  "invoice 2025" \
  --local ./research/reports \
  --grep 'total|amount|paid' \
  --output json
```

## Parameters

- `query`: SearXNG query, or filename/path search terms when `--local` is set.
- `--output markdown|json|urls|raw`: choose a human summary, structured payload, URLs/paths, or raw SearXNG response.
- `--fetch`: download web results and write an artifact manifest.
- `--out DIR`: output directory. For web searches this implies `--fetch`.
- `--types all|pdf,csv,xlsx,html,.zip,...`: save all files by default, or narrow by type, extension, or MIME fragment.
- `--grep REGEX`: grep fetched or local text-like files. With an output directory, writes `grep-results.json`.
- `--local DIR`: search an existing local artifact/data directory instead of SearXNG.
- `--base-url`: override `SEARXNG_BASE_URL`.

## Artifact Contract

When `--fetch` is used, Deepsearch writes:

- `search-results.json`: raw SearXNG JSON for the query.
- `manifest.json`: source URL, final URL, title, engine, content type, saved path, extracted text path, and errors for each result.
- Downloaded files: saved with result index and title-derived filenames.
- `*.txt`: extracted text sidecars for HTML pages.
- `grep-results.json`: evidence matches when `--grep` is used.

The manifest is the source-of-source record. Cite source URLs from it rather than only citing local paths.

## Brain-Ops Handoff

Deepsearch is the evidence intake layer for `brain-ops`:

1. Fetch evidence into a stable directory with `--fetch --out <dir>`.
2. Inspect `manifest.json` and `grep-results.json`.
3. Import durable source artifacts into Knowledge.
4. Save the interpretation, caveats, decisions, and next actions to Memory.

```bash
npx mcporter call knowledge.import_folder \
  namespace:'external-evidence' \
  folder_path:'/absolute/path/to/research/reports'

npx mcporter call memory.save \
  content:'Deepsearch gathered evidence for <topic>. Query used: <query>. Artifacts live at <absolute path>. Manifest lists original source URLs. Key finding: <finding>. Open caveat: <uncertainty or missing source>.' \
  name:'Deepsearch evidence - <topic>' \
  path:'research/evidence' \
  tags:'deepsearch,research,evidence'
```

Use Knowledge for durable source files. Use Memory for agent-team context, decisions, gotchas, and coordination notes.

## Research Discipline

- Prefer official investor relations, regulator, exchange, court, government, and standards-body pages for financial, legal, and regulatory research.
- Verify high-stakes or time-sensitive facts against primary sources when possible.
- Treat downloaded files as evidence, not truth; inspect the manifest before making claims.
- Keep artifact directories until the final answer or handoff is complete.
- If SearXNG returns HTTP 403, enable the requested format in `search.formats` in the SearXNG `settings.yml`.
- Deepsearch extracts HTML text with the standard library. PDFs, spreadsheets, images, and archives are downloaded for later parsing by Knowledge import or specialized tools.
