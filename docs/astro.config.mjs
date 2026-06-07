import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://twin.igot.ai',
  integrations: [
    starlight({
      title: 'OSTwin',
      description: 'A zero-agent operating system for composable AI engineering teams.',
      logo: {
        light: './src/assets/logo-light.svg',
        dark: './src/assets/logo-dark.svg',
        replacesTitle: false,
      },
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/igot-ai/os-twin' },
      ],
      editLink: {
        baseUrl: 'https://github.com/igot-ai/os-twin/edit/main/docs/',
      },
      customCss: ['./src/styles/custom.css'],
      head: [
        {
          tag: 'meta',
          attrs: { property: 'og:url', content: 'https://twin.igot.ai' },
        },
        {
          tag: 'link',
          attrs: { rel: 'canonical', href: 'https://twin.igot.ai' },
        },
      ],
      sidebar: [
        {
          label: 'Getting Started',
          items: [
            { label: 'Introduction', slug: 'getting-started/introduction' },
            { label: 'Installation', slug: 'getting-started/installation' },
            { label: 'Quick Start', slug: 'getting-started/quick-start' },
            { label: 'Your First Plan', slug: 'getting-started/first-plan' },
          ],
        },
        {
          label: 'Core Concepts',
          items: [
            {
              label: 'The Five Pillars',
              items: [
                { label: '🚀 1. Role Pattern', slug: 'concepts/role-pattern' },
                { label: '🚀 2. Skills as Expertise', slug: 'concepts/skills' },
                { label: '🚀 3. MCP Isolation', slug: 'concepts/mcp-isolation' },
                { label: '🚀 4. War-Rooms', slug: 'concepts/war-rooms' },
                { label: '🚀 5. Layered Memory', slug: 'concepts/memory' },
              ],
            },
            { label: 'Plans, Epics & DAG', slug: 'concepts/plans-epics-dag' },
            { label: 'Epic Lifecycle', slug: 'concepts/lifecycle' },
            { label: 'Architecture Overview', slug: 'concepts/architecture' },
          ],
        },
        {
          label: 'Guides',
          items: [
            { label: 'Creating Plans', slug: 'guides/creating-plans' },
            { label: 'Defining Roles', slug: 'guides/defining-roles' },
            { label: 'Working with War-Rooms', slug: 'guides/working-with-war-rooms' },
            { label: 'Using the Memory System', slug: 'guides/memory-usage' },
            { label: 'Dashboard Setup', slug: 'guides/dashboard-setup' },
            { label: 'Bot Configuration', slug: 'guides/bot-configuration' },
            { label: 'MCP Server Configuration', slug: 'guides/mcp-configuration' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { label: 'CLI Commands', slug: 'reference/cli-commands' },
            { label: 'Configuration', slug: 'reference/configuration' },
            { label: 'Plan Format', slug: 'reference/plan-format' },
            { label: 'Role Schema', slug: 'reference/role-schema' },
            { label: 'Skill Schema', slug: 'reference/skill-schema' },
            { label: 'War-Room Schema', slug: 'reference/war-room-schema' },
            { label: 'Channel Message Format', slug: 'reference/channel-format' },
            { label: 'Lifecycle States', slug: 'reference/lifecycle-states' },
            { label: 'DAG Format', slug: 'reference/dag-format' },
          ],
        },
        {
          label: 'Contributing',
          items: [
            { label: 'Contribution Guide', slug: 'contributing/guide' },
            { label: 'Creating Custom Roles', slug: 'contributing/custom-roles' },
            { label: 'Publishing Skills', slug: 'contributing/publishing-skills' },
            { label: 'Community Roles', slug: 'contributing/community-roles' },
          ],
        },
        {
          label: 'Internals',
          badge: { text: 'Advanced', variant: 'caution' },
          items: [
            { label: 'Developer Context', slug: 'internals/developer-context' },
            { label: 'Installer Release Flow', slug: 'internals/installer-release-flow' },
            { label: 'Testing', slug: 'internals/testing' },
            { label: 'Debugging', slug: 'internals/debugging' },
          ],
        },
      ],
    }),
  ],
});
