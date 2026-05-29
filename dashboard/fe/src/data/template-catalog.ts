/**
 * Lightweight template catalog -- only metadata, no prompt content.
 *
 * This module is imported on the home page at load time. It is tiny (~2KB)
 * and contains no template strings. The actual prompt content lives in
 * `prompt-templates.ts` and is loaded on-demand only when the user clicks
 * a specific template.
 */

export interface TemplateCatalogEntry {
  id: string;
  name: string;
  description: string;
  /** Number of {{ }} fields the user will fill in */
  fieldCount: number;
  /** Which plan concept sections this template covers */
  covers: string[];
}

export interface TemplateCategoryMeta {
  id: string;
  name: string;
  icon: string;
  description: string;
  templates: TemplateCatalogEntry[];
}

// ---------------------------------------------------------------------------
// Catalog data -- tiny, no prompt strings
// ---------------------------------------------------------------------------

export const templateCatalog: TemplateCategoryMeta[] = [
  {
    id: 'engineering', name: 'Engineering', icon: 'engineering',
    description: 'Software, sites, tools, integrations',
    templates: [
      { id: 'landing-page', name: 'Landing page or marketing site', description: 'Single page with hero, features, and call to action', fieldCount: 7, covers: ['goal', 'audience', 'scope'] },
      { id: 'web-app', name: 'Web app with login + database', description: 'Multi-user app with auth, persistence, and a dashboard', fieldCount: 8, covers: ['goal', 'audience', 'scope', 'tech', 'done-when'] },
      { id: 'admin-dashboard', name: 'Internal tool or admin dashboard', description: 'CRUD interface over your data, for you or your team', fieldCount: 8, covers: ['goal', 'scope', 'tech'] },
      { id: 'browser-extension', name: 'Browser extension or integration', description: 'Add behavior to web pages or connect two services', fieldCount: 6, covers: ['goal', 'scope', 'tech'] },
    ],
  },
  {
    id: 'marketing', name: 'Marketing', icon: 'campaign',
    description: 'Awareness, content, SEO, campaigns',
    templates: [
      { id: 'product-launch', name: 'Product launch (landing + email + waitlist)', description: 'End-to-end launch with the surfaces you need', fieldCount: 6, covers: ['goal', 'audience', 'scope', 'constraints'] },
      { id: 'blog-post', name: 'Long-form blog post for SEO', description: 'Researched article targeting a keyword', fieldCount: 7, covers: ['goal', 'audience', 'scope'] },
      { id: 'email-campaign', name: 'Email campaign or newsletter', description: 'One-off email or recurring sequence', fieldCount: 7, covers: ['goal', 'audience', 'scope'] },
      { id: 'seo-plan', name: 'SEO content plan', description: 'Multi-article keyword and topic strategy', fieldCount: 7, covers: ['goal', 'audience', 'scope', 'constraints'] },
    ],
  },
  {
    id: 'sales', name: 'Sales', icon: 'handshake',
    description: 'Outreach, lead lists, proposals, sales calls',
    templates: [
      { id: 'cold-outreach', name: 'Cold outreach sequence', description: 'Multi-touch email or LinkedIn campaign', fieldCount: 7, covers: ['goal', 'audience', 'scope'] },
      { id: 'lead-list', name: 'Lead list from a target ICP', description: 'Sourced and enriched prospect list', fieldCount: 8, covers: ['audience', 'scope', 'done-when'] },
      { id: 'sales-proposal', name: 'Sales proposal or quote document', description: 'Written proposal for a specific prospect', fieldCount: 8, covers: ['goal', 'audience', 'scope'] },
      { id: 'demo-prep', name: 'Demo script or call prep', description: 'Talk-track and prep notes for a sales call', fieldCount: 8, covers: ['goal', 'scope'] },
    ],
  },
  {
    id: 'support', name: 'Support', icon: 'support_agent',
    description: 'Chatbots, helpdesk, FAQ, response automation',
    templates: [
      { id: 'rag-chatbot', name: 'AI chatbot over our docs (RAG)', description: 'Chat assistant grounded in your own content', fieldCount: 6, covers: ['goal', 'audience', 'scope', 'tech'] },
      { id: 'chat-support-bot', name: 'Telegram / Discord / Slack support bot', description: 'Bot that handles questions in a chat platform', fieldCount: 7, covers: ['goal', 'scope', 'tech'] },
      { id: 'help-center', name: 'FAQ or help center site', description: 'Browsable searchable help content', fieldCount: 6, covers: ['goal', 'audience', 'scope'] },
      { id: 'auto-responder', name: 'Auto-responder for inbound forms or email', description: 'Automated reply to incoming messages', fieldCount: 5, covers: ['goal', 'scope'] },
    ],
  },
  {
    id: 'operations', name: 'Operations', icon: 'settings',
    description: 'Workflows, schedules, sync, recurring jobs',
    templates: [
      { id: 'scheduled-scrape', name: 'Scrape data on a schedule', description: 'Recurring web scrape with structured output', fieldCount: 6, covers: ['goal', 'scope', 'tech'] },
      { id: 'service-sync', name: 'Sync between two services', description: 'Move records between two systems on a schedule', fieldCount: 6, covers: ['goal', 'scope', 'tech'] },
      { id: 'form-pipeline', name: 'Form submission to CRM pipeline', description: 'Capture form data into a CRM or sheet with enrichment', fieldCount: 6, covers: ['goal', 'scope', 'tech'] },
      { id: 'recurring-report', name: 'Recurring report delivered to a channel', description: 'Scheduled summary delivered to chat or email', fieldCount: 6, covers: ['goal', 'scope'] },
    ],
  },
  {
    id: 'research', name: 'Research', icon: 'science',
    description: 'Market intel, competitive analysis, data digging',
    templates: [
      { id: 'competitive-analysis', name: 'Competitive analysis', description: 'Side-by-side comparison of products or companies', fieldCount: 6, covers: ['goal', 'scope', 'done-when'] },
      { id: 'market-research', name: 'Market research with cited sources', description: 'Researched brief with citations', fieldCount: 6, covers: ['goal', 'scope'] },
      { id: 'data-analysis', name: 'Data analysis on a CSV or sheet', description: 'Analysis and insights from structured data', fieldCount: 6, covers: ['goal', 'scope', 'done-when'] },
      { id: 'survey', name: 'Survey design + result analysis', description: 'Design a survey and analyze the results', fieldCount: 6, covers: ['goal', 'audience', 'scope'] },
    ],
  },
  {
    id: 'compliance', name: 'Compliance', icon: 'verified',
    description: 'Audits, risk reports, policy, postmortems',
    templates: [
      { id: 'risk-audit', name: 'Risk audit on a process or system', description: 'Structured risk assessment with a decision', fieldCount: 6, covers: ['goal', 'scope', 'constraints'] },
      { id: 'policy-sop', name: 'Policy or SOP document', description: 'Formal policy or standard operating procedure', fieldCount: 7, covers: ['goal', 'audience', 'scope'] },
      { id: 'postmortem', name: 'Incident postmortem report', description: 'Written analysis of what went wrong and what to do', fieldCount: 7, covers: ['goal', 'scope'] },
      { id: 'vendor-review', name: 'Vendor or data-privacy review', description: "Review of a vendor's data handling", fieldCount: 7, covers: ['goal', 'scope', 'constraints'] },
    ],
  },
  {
    id: 'documents', name: 'Documents', icon: 'description',
    description: 'Drafts, reports, notes, source-based docs',
    templates: [
      { id: 'document-draft', name: 'Draft a document', description: 'Create a structured document from a brief or notes', fieldCount: 8, covers: ['goal', 'audience', 'scope'] },
      { id: 'rewrite-document', name: 'Rewrite or polish text', description: 'Revise an existing draft for clarity, tone, or audience', fieldCount: 7, covers: ['goal', 'audience', 'constraints'] },
      { id: 'source-based-report', name: 'Source-based report or memo', description: 'Write a report grounded in provided docs or sources', fieldCount: 7, covers: ['goal', 'scope', 'constraints'] },
      { id: 'meeting-notes', name: 'Meeting notes / minutes', description: 'Turn notes or a transcript into decisions and action items', fieldCount: 7, covers: ['goal', 'audience', 'done-when'] },
    ],
  },
  {
    id: 'creative', name: 'Creative', icon: 'palette',
    description: 'Decks, docs, scripts, briefs -- any purpose',
    templates: [
      { id: 'slide-deck', name: 'Slide deck or presentation', description: 'Slide deck for any audience or purpose', fieldCount: 7, covers: ['goal', 'audience', 'scope'] },
      { id: 'internal-doc', name: 'Internal doc or handbook page', description: 'Document for internal team consumption', fieldCount: 6, covers: ['goal', 'audience', 'scope'] },
      { id: 'video-script', name: 'Video script or podcast outline', description: 'Talk script or outline for video or audio', fieldCount: 8, covers: ['goal', 'audience', 'scope'] },
      { id: 'creative-brief', name: 'Brand or creative brief', description: 'Brief for a designer or creative team', fieldCount: 8, covers: ['goal', 'audience', 'scope', 'constraints'] },
    ],
  },
];

/**
 * Load the full prompt template content for a specific template ID.
 * Uses dynamic import so the 12KB of template strings only loads when needed.
 */
export async function loadTemplateContent(templateId: string): Promise<{
  promptTemplate: string;
} | null> {
  const { planCategories } = await import('./prompt-templates');
  for (const cat of planCategories) {
    const found = cat.templates.find(t => t.id === templateId);
    if (found) return { promptTemplate: found.promptTemplate };
  }
  return null;
}
