// @vitest-environment node
import { describe, it, expect } from 'vitest';
import {
  extractFieldsFromTemplate,
  computeCompleteness,
  hydrateTemplate,
  planCategories,
} from './prompt-templates';
import { templateCatalog, loadTemplateContent } from './template-catalog';

describe('extractFieldsFromTemplate', () => {
  it('extracts fields from a simple template', () => {
    const tpl = `# Project: {{name}}

## Goal
{{ }}

## Audience (optional)
{{e.g. developers, marketers}}`;

    const { fields, groups } = extractFieldsFromTemplate(tpl);

    expect(fields.length).toBe(3);
    expect(fields[0].hint).toBe('name');
    expect(fields[0].required).toBe(true);
    expect(fields[1].hint).toBe('');
    expect(fields[1].group).toBe('goal');
    expect(fields[2].required).toBe(false); // marked optional
    expect(groups.length).toBeGreaterThanOrEqual(2);
  });

  it('assigns groups based on ## headings', () => {
    const tpl = `## Section A
{{field a}}

## Section B
{{field b}}`;

    const { fields, groups } = extractFieldsFromTemplate(tpl);
    expect(groups.map(g => g.label)).toContain('Section A');
    expect(groups.map(g => g.label)).toContain('Section B');
    expect(fields[0].group).not.toBe(fields[1].group);
  });

  it('handles templates with no placeholders', () => {
    const { fields, groups } = extractFieldsFromTemplate('Just plain text');
    expect(fields).toHaveLength(0);
    expect(groups).toHaveLength(1); // default 'basics'
  });
});

describe('computeCompleteness', () => {
  const template = `# App: {{name}}

## Goal
{{ }}

## Users
{{e.g. customers}}`;

  it('reports 0% when nothing is filled', () => {
    const result = computeCompleteness(template, template);
    expect(result.total).toBe(3);
    expect(result.filled).toBe(0);
    expect(result.percent).toBe(0);
  });

  it('reports partial completion', () => {
    const filled = template.replace('{{name}}', 'MyApp');
    const result = computeCompleteness(template, filled);
    expect(result.filled).toBe(1);
    expect(result.percent).toBe(33);
  });

  it('reports 100% when all placeholders are replaced', () => {
    const filled = template
      .replace('{{name}}', 'MyApp')
      .replace('{{ }}', 'A task manager')
      .replace('{{e.g. customers}}', 'Remote teams');
    const result = computeCompleteness(template, filled);
    expect(result.filled).toBe(3);
    expect(result.percent).toBe(100);
  });

  it('tracks unfilled labels', () => {
    const filled = template.replace('{{name}}', 'MyApp');
    const result = computeCompleteness(template, filled);
    expect(result.unfilledLabels.length).toBeGreaterThan(0);
  });
});

describe('hydrateTemplate', () => {
  it('replaces placeholders by field index', () => {
    const tpl = '# {{name}}\n## Goal\n{{ }}';
    const result = hydrateTemplate(tpl, { 'field-0': 'MyApp', 'field-1': 'Build it' });
    expect(result).toContain('MyApp');
    expect(result).toContain('Build it');
    expect(result).not.toContain('{{');
  });

  it('preserves unfilled placeholders', () => {
    const tpl = '# {{name}}\n## Goal\n{{ }}';
    const result = hydrateTemplate(tpl, { 'field-0': 'MyApp' });
    expect(result).toContain('MyApp');
    expect(result).toContain('{{ }}');
  });
});

describe('Documents category', () => {
  it('templateCatalog includes a Documents category', () => {
    const cat = templateCatalog.find(c => c.id === 'documents');
    expect(cat).toBeDefined();
    expect(cat?.name).toBe('Documents');
    expect(cat?.icon).toBe('description');
  });

  it('planCategories includes documents with exactly 4 templates', () => {
    const cat = planCategories.find(c => c.id === 'documents');
    expect(cat).toBeDefined();
    expect(cat?.templates).toHaveLength(4);
    const ids = cat?.templates.map(t => t.id);
    expect(ids).toContain('document-draft');
    expect(ids).toContain('rewrite-document');
    expect(ids).toContain('source-based-report');
    expect(ids).toContain('meeting-notes');
  });

  it('loadTemplateContent("meeting-notes") returns content with action items', async () => {
    const result = await loadTemplateContent('meeting-notes');
    expect(result).not.toBeNull();
    expect(result?.promptTemplate).toContain('action items');
  });

  it('loadTemplateContent("source-based-report") returns content with provenance', async () => {
    const result = await loadTemplateContent('source-based-report');
    expect(result).not.toBeNull();
    expect(result?.promptTemplate).toContain('provenance');
  });
});
