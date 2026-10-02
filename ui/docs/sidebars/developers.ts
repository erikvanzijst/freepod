import type { SidebarsConfig } from '@docusaurus/plugin-content-docs'

const sidebars: SidebarsConfig = {
  developers: [
    'get-started',
    'how-it-works',
    'runtime',
    'constraints',
    {
      type: 'category',
      label: 'Build and deploy',
      collapsed: false,
      items: [
        {
          type: 'category',
          label: 'Builds',
          link: { type: 'doc', id: 'builds/index' },
          items: ['builds/nodejs', 'builds/python', 'builds/go'],
        },
        'deployments-and-releases',
        'ci-deploys',
        'coding-agents',
      ],
    },
    {
      type: 'category',
      label: 'Configuration',
      collapsed: false,
      items: ['variables-and-secrets', 'hostnames-and-custom-domains', 'authentication', 'email'],
    },
    {
      type: 'category',
      label: 'Storage',
      collapsed: false,
      link: { type: 'doc', id: 'storage/index' },
      items: ['storage/postgresql', 'storage/object-storage'],
    },
    {
      type: 'category',
      label: 'Operations',
      collapsed: false,
      items: ['logs-and-debugging', 'usage-and-billing'],
    },
    'cli-reference',
    { type: 'link', label: 'Getting help', href: '/apps/getting-help' },
  ],
}

export default sidebars
