export interface TemplateField {
  id: string;
  label: string;
  hint: string;
  type: 'short' | 'long' | 'choice' | 'checklist';
  required: boolean;
  options?: string[];
  group: string;
}

export interface TemplateGroup {
  id: string;
  label: string;
  description?: string;
}

export interface PromptTemplate {
  id: string;
  name: string;
  description: string;
  promptTemplate: string;
  /** Structured fields parsed from the promptTemplate */
  fields: TemplateField[];
  groups: TemplateGroup[];
  /** Roles the agent should consider when building a plan from this template */
  suggestedRoles?: string[];
}

export interface PlanCategory {
  id: string;
  name: string;
  icon: string;
  description: string;
  templates: PromptTemplate[];
}

// ---------------------------------------------------------------------------
// Field extraction helpers
// ---------------------------------------------------------------------------

/**
 * Automatically extract structured fields from a {{ }} prompt template string.
 * Each `{{ }}` or `{{hint text}}` block becomes a TemplateField.
 * Sections prefixed by `## ` become groups.
 */
export function extractFieldsFromTemplate(
  promptTemplate: string,
): { fields: TemplateField[]; groups: TemplateGroup[] } {
  const fields: TemplateField[] = [];
  const groupsMap = new Map<string, TemplateGroup>();
  let currentGroup = 'basics';
  let currentGroupOptional = false;
  groupsMap.set(currentGroup, { id: 'basics', label: 'The basics' });

  const lines = promptTemplate.split('\n');
  let fieldIndex = 0;

  for (const line of lines) {
    // Detect group boundaries from markdown headings
    const headingMatch = line.match(/^##\s+(.+)/);
    if (headingMatch) {
      currentGroupOptional = /\(optional\)/i.test(headingMatch[1]);
      const label = headingMatch[1].replace(/\s*\(optional\)\s*/i, '').trim();
      const id = label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+$/, '');
      if (!groupsMap.has(id)) {
        groupsMap.set(id, { id, label });
      }
      currentGroup = id;
      continue;
    }

    // Extract {{ }} placeholders
    const placeholderRegex = /\{\{([^}]*)\}\}/g;
    let match: RegExpExecArray | null;
    while ((match = placeholderRegex.exec(line)) !== null) {
      const hint = match[1].trim();
      const isOptional = currentGroupOptional || /\(optional\)/i.test(line) || /optional/i.test(hint);

      // Derive a label from the preceding markdown line content
      let label = line.replace(/\{\{[^}]*\}\}/g, '').replace(/^[-*#\s]+/, '').replace(/:?\s*$/, '').trim();
      if (!label || label === '-') {
        // Use the heading above or the hint
        label = hint.startsWith('e.g.') ? `Item ${fieldIndex + 1}` : hint.split(',')[0];
      }

      const id = `field-${fieldIndex}`;
      const isLong = /\n/.test(hint) || hint.length > 60;
      const isChecklist = /^\s*-\s*\[/.test(line);

      fields.push({
        id,
        label,
        hint: hint || '',
        type: isChecklist ? 'checklist' : isLong ? 'long' : 'short',
        required: !isOptional,
        group: currentGroup,
      });
      fieldIndex++;
    }
  }

  return { fields, groups: Array.from(groupsMap.values()) };
}

/**
 * Given a promptTemplate string, count total placeholders and how many the user
 * has filled (i.e. replaced the `{{ }}` markers with real content).
 */
export function computeCompleteness(promptTemplate: string, currentValue: string): {
  total: number;
  filled: number;
  percent: number;
  unfilledLabels: string[];
} {
  // Extract original placeholders
  const originalPlaceholders = promptTemplate.match(/\{\{[^}]*\}\}/g) || [];
  const total = originalPlaceholders.length;
  if (total === 0) return { total: 0, filled: 0, percent: 100, unfilledLabels: [] };

  // Count remaining {{ }} in user's current text
  const remaining = currentValue.match(/\{\{[^}]*\}\}/g) || [];
  const filled = total - remaining.length;
  const percent = Math.round((filled / total) * 100);

  // Extract labels for unfilled fields
  const unfilledLabels: string[] = [];
  const lines = currentValue.split('\n');
  for (const line of lines) {
    const placeholderMatch = line.match(/\{\{([^}]*)\}\}/);
    if (placeholderMatch) {
      let label = line.replace(/\{\{[^}]*\}\}/g, '').replace(/^[-*#\s]+/, '').replace(/:?\s*$/, '').trim();
      if (!label) label = placeholderMatch[1].trim();
      if (label) unfilledLabels.push(label);
    }
  }

  return { total, filled, percent, unfilledLabels };
}

/**
 * Hydrate a prompt template with field values, replacing {{ }} markers.
 */
export function hydrateTemplate(
  promptTemplate: string,
  values: Record<string, string>,
): string {
  let result = promptTemplate;
  const placeholders = promptTemplate.match(/\{\{[^}]*\}\}/g) || [];
  placeholders.forEach((placeholder, idx) => {
    const fieldId = `field-${idx}`;
    const val = values[fieldId];
    if (val && val.trim()) {
      result = result.replace(placeholder, val);
    }
  });
  return result;
}

const OSTWIN_INSTRUCTION = `
---

Turn the details I've filled in above into an Ostwin plan with epics, roles, lifecycle, tasks, and acceptance criteria.`;

/**
 * Build a PromptTemplate stub -- fields/groups default to empty arrays.
 * Call `ensureFieldsExtracted(template)` to populate them on demand.
 */
function tpl(
  raw: Omit<PromptTemplate, 'fields' | 'groups'>,
): PromptTemplate {
  return { ...raw, fields: [], groups: [] };
}

/**
 * Populate `fields` and `groups` on a template if not already done.
 * This is called on-demand (e.g. when the user selects a template)
 * to avoid running regex extraction for all 32 templates at load time.
 */
export function ensureFieldsExtracted(t: PromptTemplate): PromptTemplate {
  if (t.fields.length > 0) return t;
  const { fields, groups } = extractFieldsFromTemplate(t.promptTemplate);
  return { ...t, fields, groups };
}

const engineeringTemplates: PromptTemplate[] = [
  tpl({
    id: 'landing-page',
    name: 'Landing page or marketing site',
    description: 'Single page with hero, features, and call to action',
    promptTemplate: `# Landing page for {{product or service name}}

## What it does (one sentence)
{{ }}

## Who it's for
{{ }}

## Sections I want
- {{e.g. hero with email signup}}
- {{e.g. feature highlights}}
- {{e.g. pricing}}

## Primary call to action
{{e.g. start free trial, join waitlist}}

## Vibe / style (optional)
{{e.g. minimalist, playful, enterprise}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'web-app',
    name: 'Web app with login + database',
    description: 'Multi-user app with auth, persistence, and a dashboard',
    promptTemplate: `# Web app: {{one-line description}}

## What it does
{{ }}

## Who logs in
{{e.g. customers, my team, both}}

## Main things users do
- {{ }}
- {{ }}

## Data I need to store
{{e.g. users, orders, files, messages}}

## Must-have integrations (optional)
{{e.g. Stripe, Google login}}

## Done when
{{ }}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'admin-dashboard',
    name: 'Internal tool or admin dashboard',
    description: 'CRUD interface over your data, for you or your team',
    promptTemplate: `# Admin tool for {{what data or process}}

## Records I need to manage
{{e.g. customers, orders, support tickets}}

## What I need to do with them
- {{view / search / filter}}
- {{create / edit / delete}}
- {{export / import}}

## Who logs in
{{e.g. just me, my team of 3}}

## Where the data lives today
{{e.g. Postgres, Google Sheets, build me a new DB}}

## Must-haves vs nice-to-haves
{{ }}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'browser-extension',
    name: 'Browser extension or integration',
    description: 'Add behavior to web pages or connect two services',
    promptTemplate: `# Browser extension: {{one-line purpose}}

## What it does
{{ }}

## Where it shows up
{{e.g. on every page, on specific sites, only when I click the icon}}

## Trigger
{{e.g. button click, page load, text selection, keyboard shortcut}}

## What happens when triggered
{{ }}

## Browsers to support
{{e.g. Chrome, Firefox, Edge}}${OSTWIN_INSTRUCTION}`,
  }),
];

const marketingTemplates: PromptTemplate[] = [
  tpl({
    id: 'product-launch',
    name: 'Product launch (landing + email + waitlist)',
    description: 'End-to-end launch with the surfaces you need',
    promptTemplate: `# Launch plan for {{product name}}

## What it is, in one sentence
{{ }}

## Who it's for
{{ }}

## Launch surfaces (pick any)
- [ ] Landing page
- [ ] Waitlist signup
- [ ] Email announcement
- [ ] Social posts
- [ ] Press / blog post

## What I already have
{{e.g. logo, copy draft, screenshots, nothing}}

## Launch date (optional)
{{ }}

## Tone
{{e.g. confident, technical, playful}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'blog-post',
    name: 'Long-form blog post for SEO',
    description: 'Researched article targeting a keyword',
    promptTemplate: `# Blog post about {{topic}}

## Target keyword(s)
{{ }}

## Who the reader is
{{ }}

## What they should learn or do after reading
{{ }}

## Angle or hook (optional)
{{ }}

## Length target
{{e.g. 800, 1500, 3000 words}}

## Sources I want cited
{{e.g. our own data, public studies, none}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'email-campaign',
    name: 'Email campaign or newsletter',
    description: 'One-off email or recurring sequence',
    promptTemplate: `# Email campaign: {{purpose}}

## Audience
{{e.g. existing customers, free trial users, cold list}}

## Goal of this campaign
{{e.g. announce a feature, drive renewals, re-engage churned users}}

## Number of emails
{{e.g. one-off, 3-email sequence, weekly newsletter}}

## Key message
{{ }}

## Call to action
{{ }}

## Tone
{{ }}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'seo-plan',
    name: 'SEO content plan',
    description: 'Multi-article keyword and topic strategy',
    promptTemplate: `# SEO content plan for {{site or product}}

## What we sell / what the site is about
{{ }}

## Who I'm trying to reach
{{ }}

## Keywords I already know I want to rank for
{{ }}

## Competitors ranking on those keywords (optional)
{{ }}

## How many articles
{{e.g. 10, 30, ongoing monthly}}

## Time horizon
{{e.g. 1 month, quarterly, annual}}${OSTWIN_INSTRUCTION}`,
  }),
];

const salesTemplates: PromptTemplate[] = [
  tpl({
    id: 'cold-outreach',
    name: 'Cold outreach sequence',
    description: 'Multi-touch email or LinkedIn campaign',
    promptTemplate: `# Cold outreach sequence to {{audience}}

## Who I'm reaching out to
{{job title, industry, company size}}

## What I'm offering
{{ }}

## Why they should care (the hook)
{{ }}

## Channel
{{e.g. email, LinkedIn DM, both}}

## How many touches
{{e.g. 3-step over 2 weeks}}

## Where the lead list comes from
{{e.g. I'll upload a CSV, scrape from LinkedIn, generate by ICP}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'lead-list',
    name: 'Lead list from a target ICP',
    description: 'Sourced and enriched prospect list',
    promptTemplate: `# Lead list for {{what offer or product}}

## Ideal customer profile
- Industry: {{ }}
- Company size: {{ }}
- Role / title: {{ }}
- Geography: {{ }}

## Signals to look for (optional)
{{e.g. recently raised funding, hiring for X, using Y tech}}

## How many leads
{{ }}

## Format I want back
{{e.g. CSV with name + email + company, enriched profiles, just companies}}

## Sources to use
{{e.g. LinkedIn, Crunchbase, public web, anywhere}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'sales-proposal',
    name: 'Sales proposal or quote document',
    description: 'Written proposal for a specific prospect',
    promptTemplate: `# Sales proposal for {{prospect or use case}}

## Who the proposal is for
{{ }}

## What I'm proposing
{{ }}

## Their pain point or goal
{{ }}

## My pricing
{{ }}

## Timeline
{{ }}

## Deliverables / scope
{{ }}

## Tone
{{e.g. formal, founder-to-founder, technical}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'demo-prep',
    name: 'Demo script or call prep',
    description: 'Talk-track and prep notes for a sales call',
    promptTemplate: `# Demo / call prep for {{prospect or call type}}

## Who I'm meeting
{{name, role, company}}

## What I know about them
{{ }}

## Goal of the call
{{e.g. discovery, demo, close, negotiation}}

## Key things to show or explain
- {{ }}
- {{ }}

## Likely objections
{{ }}

## Next-step ask
{{ }}${OSTWIN_INSTRUCTION}`,
  }),
];

const supportTemplates: PromptTemplate[] = [
  tpl({
    id: 'rag-chatbot',
    name: 'AI chatbot over our docs (RAG)',
    description: 'Chat assistant grounded in your own content',
    promptTemplate: `# AI chatbot that answers questions about {{topic / domain}}

## Source material
{{e.g. PDF manuals, our Notion workspace, a folder of markdown}}

## Who's asking
{{e.g. customers, my support team, internal staff}}

## What kinds of questions
- {{example question 1}}
- {{example question 2}}

## Where it lives
{{e.g. a web chat widget, a Slack bot, a standalone page}}

## Out of scope
{{things it shouldn't try to answer}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'chat-support-bot',
    name: 'Telegram / Discord / Slack support bot',
    description: 'Bot that handles questions in a chat platform',
    promptTemplate: `# Support bot on {{Telegram / Discord / Slack}}

## What kind of questions or commands it handles
- /{{command}} → {{what it does}}
- {{plain message pattern}} → {{what it does}}

## Where its knowledge comes from
{{e.g. our docs, a Google Sheet, an API}}

## When to escalate to a human
{{ }}

## Tone of replies
{{ }}

## Done when
{{ }}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'help-center',
    name: 'FAQ or help center site',
    description: 'Browsable searchable help content',
    promptTemplate: `# Help center for {{product or service}}

## Audience
{{e.g. end customers, technical users, internal team}}

## Sections I want
- {{e.g. getting started}}
- {{e.g. billing}}
- {{e.g. troubleshooting}}

## Source material I have
{{e.g. existing docs, support tickets, nothing yet}}

## Search required?
{{yes / no}}

## Where it should be hosted
{{e.g. our own subdomain, a hosted service, just markdown files}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'auto-responder',
    name: 'Auto-responder for inbound forms or email',
    description: 'Automated reply to incoming messages',
    promptTemplate: `# Auto-responder for {{form or inbox}}

## What triggers it
{{e.g. a form submission, a new email matching a filter}}

## What information comes in
{{ }}

## What the auto-reply should say or do
{{ }}

## Who else should be notified (optional)
{{e.g. CC the team Slack, email the sales lead}}

## When it should NOT respond
{{e.g. obvious spam, replies from team members}}${OSTWIN_INSTRUCTION}`,
  }),
];

const operationsTemplates: PromptTemplate[] = [
  tpl({
    id: 'scheduled-scrape',
    name: 'Scrape data on a schedule',
    description: 'Recurring web scrape with structured output',
    promptTemplate: `# Scrape {{what data}} on a schedule

## Source(s)
{{e.g. specific URL, list of sites, an API}}

## What fields to extract
- {{ }}
- {{ }}

## How often
{{e.g. daily at 9am, every hour, weekly}}

## Where to store the result
{{e.g. Google Sheet, our database, a CSV file}}

## What to do when something changes
{{e.g. notify me on Slack, append to history, just overwrite}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'service-sync',
    name: 'Sync between two services',
    description: 'Move records between two systems on a schedule',
    promptTemplate: `# Sync between {{service A}} and {{service B}}

## What records to sync
{{ }}

## Direction
{{e.g. one-way A→B, two-way}}

## How often
{{e.g. real-time, every 15 min, nightly}}

## How to handle conflicts (optional)
{{ }}

## What to skip
{{e.g. archived items, items older than 30 days}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'form-pipeline',
    name: 'Form submission → CRM pipeline',
    description: 'Capture form data into a CRM or sheet with enrichment',
    promptTemplate: `# Pipeline: {{form source}} → {{destination}}

## Where the form lives
{{e.g. our website, Typeform, Google Form}}

## Fields collected
- {{ }}
- {{ }}

## Where the data should land
{{e.g. HubSpot, Airtable, Notion, Google Sheet}}

## Mapping or enrichment
{{e.g. tag by source, look up company info, score the lead}}

## Notifications (optional)
{{e.g. Slack alert on new submission}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'recurring-report',
    name: 'Recurring report delivered to a channel',
    description: 'Scheduled summary delivered to chat or email',
    promptTemplate: `# Recurring report: {{topic}}

## What metrics or data to include
- {{ }}
- {{ }}

## Where the data comes from
{{ }}

## How often
{{e.g. daily 8am, weekly Monday, monthly first}}

## Where to deliver it
{{e.g. Slack #channel, email, Telegram, dashboard}}

## Format
{{e.g. plain summary, table, chart, PDF}}${OSTWIN_INSTRUCTION}`,
  }),
];

const researchTemplates: PromptTemplate[] = [
  tpl({
    id: 'competitive-analysis',
    name: 'Competitive analysis',
    description: 'Side-by-side comparison of products or companies',
    promptTemplate: `# Competitive analysis of {{market or product space}}

## Companies / products to look at
- {{ }}
- {{ }}
*(or: "find them for me — here's how I'd describe the space: ...")*

## What I want to know about each
- {{e.g. pricing tiers}}
- {{e.g. positioning and target audience}}
- {{e.g. recent product launches}}

## Why I need this
{{e.g. deciding our own positioning, pitching to investors}}

## Format I want back
{{e.g. side-by-side table, written brief, slide deck}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'market-research',
    name: 'Market research with cited sources',
    description: 'Researched brief with citations',
    promptTemplate: `# Market research on {{topic / industry}}

## Specific questions I need answered
- {{ }}
- {{ }}

## Why I need this
{{ }}

## Source preferences
{{e.g. recent (2024+) only, peer-reviewed, industry reports}}

## Format I want back
{{e.g. brief with citations, numbers + sources, slide deck}}

## Length / depth
{{e.g. one-pager, 5-page brief, deep dive}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'data-analysis',
    name: 'Data analysis on a CSV or sheet',
    description: 'Analysis and insights from structured data',
    promptTemplate: `# Analyze {{dataset name or description}}

## Where the data is
{{e.g. CSV I'll upload, Google Sheet link, database table}}

## Questions to answer
- {{ }}
- {{ }}

## What I already know about the data
{{e.g. schema, known issues, what's clean/dirty}}

## Format of the answer
{{e.g. summary text, charts, written brief, slides}}

## Decisions this informs
{{ }}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'survey',
    name: 'Survey design + result analysis',
    description: 'Design a survey and analyze the results',
    promptTemplate: `# Survey: {{purpose}}

## Who I want to survey
{{ }}

## What I'm trying to learn
- {{ }}
- {{ }}

## Approximate sample size or list
{{ }}

## How I'll distribute it
{{e.g. email list, social, in-product, intercept}}

## What I want at the end
{{e.g. summary report, raw data, charts + recommendations}}${OSTWIN_INSTRUCTION}`,
  }),
];

const complianceTemplates: PromptTemplate[] = [
  tpl({
    id: 'risk-audit',
    name: 'Risk audit on a process or system',
    description: 'Structured risk assessment with a decision',
    promptTemplate: `# Risk audit of {{process, system, or vendor}}

## What's being audited
{{One-paragraph description}}

## What I'm worried about
- {{e.g. data leaving our systems}}
- {{e.g. single points of failure}}
- {{e.g. regulatory exposure}}

## Standards or frameworks to apply (optional)
{{e.g. SOC2, GDPR, internal policy}}

## Evidence I can provide
{{e.g. system diagrams, access logs, vendor contracts}}

## Decision I need to make
{{e.g. approve the vendor, stop the process, file remediation}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'policy-sop',
    name: 'Policy or SOP document',
    description: 'Formal policy or standard operating procedure',
    promptTemplate: `# Policy / SOP: {{topic}}

## What process or behavior this governs
{{ }}

## Who must follow it
{{ }}

## Why we need it
{{e.g. regulatory requirement, internal incident, customer demand}}

## Existing rules or precedent
{{e.g. our current handbook, industry standard, none}}

## Approval / sign-off needed from
{{ }}

## Format
{{e.g. one-pager, full policy doc, checklist}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'postmortem',
    name: 'Incident postmortem report',
    description: 'Written analysis of what went wrong and what to do',
    promptTemplate: `# Postmortem: {{incident name or date}}

## What happened (one paragraph)
{{ }}

## When it started / ended
{{ }}

## Impact
{{e.g. customers affected, downtime, financial cost}}

## What I know about the cause
{{ }}

## Evidence available
{{e.g. logs, screenshots, timeline notes}}

## Audience for the report
{{e.g. internal eng, exec, customer-facing}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'vendor-review',
    name: 'Vendor or data-privacy review',
    description: "Review of a vendor's data handling",
    promptTemplate: `# Vendor / privacy review of {{vendor or data flow}}

## What the vendor does for us
{{ }}

## What data we send them
{{ }}

## Where their servers are (if known)
{{ }}

## Their certifications (if known)
{{e.g. SOC2, ISO 27001, none listed}}

## Specific concerns to investigate
- {{ }}

## Decision needed
{{e.g. approve, reject, conditional}}${OSTWIN_INSTRUCTION}`,
  }),
];

const creativeTemplates: PromptTemplate[] = [
  tpl({
    id: 'slide-deck',
    name: 'Slide deck or presentation',
    description: 'Slide deck for any audience or purpose',
    promptTemplate: `# Slide deck: {{title or purpose}}

## Audience
{{ }}

## Goal of the deck
{{e.g. raise funding, internal alignment, conference talk}}

## Key message in one sentence
{{ }}

## Slides I know I want
- {{ }}
- {{ }}

## Length
{{e.g. 10 slides, 30 slides}}

## Tone / style
{{e.g. minimalist, data-heavy, narrative}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'internal-doc',
    name: 'Internal doc or handbook page',
    description: 'Document for internal team consumption',
    promptTemplate: `# Internal doc: {{topic}}

## Who reads this
{{e.g. new hires, the eng team, everyone}}

## What they should know or do after reading
{{ }}

## Sections I want
- {{ }}
- {{ }}

## Existing material I have
{{e.g. notes, prior version, nothing}}

## How long
{{e.g. one-pager, full handbook chapter}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'video-script',
    name: 'Video script or podcast outline',
    description: 'Talk script or outline for video or audio',
    promptTemplate: `# Script / outline: {{topic}}

## Format
{{e.g. 60-second short, 10-minute YouTube, 30-min podcast}}

## Audience
{{ }}

## Hook (first 10 seconds)
{{ }}

## Key points to hit
- {{ }}
- {{ }}

## Call to action at the end
{{ }}

## Tone
{{e.g. casual, authoritative, comedic}}${OSTWIN_INSTRUCTION}`,
  }),
  tpl({
    id: 'creative-brief',
    name: 'Brand or creative brief',
    description: 'Brief for a designer or creative team',
    promptTemplate: `# Creative brief: {{project name}}

## What we're making
{{e.g. logo, ad campaign, landing page visuals}}

## Who it's for
{{ }}

## Brand personality (3 words)
{{ }}

## What we want people to feel
{{ }}

## Things to avoid
{{ }}

## References we like (optional)
{{ }}

## Deadline
{{ }}${OSTWIN_INSTRUCTION}`,
  }),
];

export const planCategories: PlanCategory[] = [
  { id: 'engineering', name: 'Engineering', icon: 'engineering', description: 'Software, sites, tools, integrations', templates: engineeringTemplates },
  { id: 'marketing', name: 'Marketing', icon: 'campaign', description: 'Awareness, content, SEO, campaigns', templates: marketingTemplates },
  { id: 'sales', name: 'Sales', icon: 'handshake', description: 'Outreach, lead lists, proposals, sales calls', templates: salesTemplates },
  { id: 'support', name: 'Support', icon: 'support_agent', description: 'Chatbots, helpdesk, FAQ, response automation', templates: supportTemplates },
  { id: 'operations', name: 'Operations', icon: 'settings', description: 'Workflows, schedules, sync, recurring jobs', templates: operationsTemplates },
  { id: 'research', name: 'Research', icon: 'science', description: 'Market intel, competitive analysis, data digging', templates: researchTemplates },
  { id: 'compliance', name: 'Compliance', icon: 'verified', description: 'Audits, risk reports, policy, postmortems', templates: complianceTemplates },
  { id: 'creative', name: 'Creative', icon: 'palette', description: 'Decks, docs, scripts, briefs — assets, any purpose', templates: creativeTemplates },
];
