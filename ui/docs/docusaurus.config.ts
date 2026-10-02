import { themes as prismThemes } from 'prism-react-renderer'
import type { Config } from '@docusaurus/types'
import type * as Preset from '@docusaurus/preset-classic'

const config: Config = {
  title: 'Freepod Docs',
  tagline: 'Documentation for Freepod',
  favicon: 'img/freepod.svg',
  clientModules: ['./src/fonts.ts'],

  url: 'https://freepod.eu',
  baseUrl: '/docs/',
  trailingSlash: false,

  onBrokenLinks: 'throw',
  onBrokenAnchors: 'throw',
  markdown: {
    // .md is plain CommonMark (the generated CLI reference relies on it); .mdx for components.
    format: 'detect',
    hooks: { onBrokenMarkdownLinks: 'throw' },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
    localeConfigs: { en: { htmlLang: 'en-US' } },
  },

  presets: [
    [
      'classic',
      {
        // The classic preset's own docs instance serves the developer section;
        // the apps section is a second instance below.
        docs: {
          path: 'developers',
          routeBasePath: 'developers',
          sidebarPath: './sidebars/developers.ts',
        },
        blog: {
          path: 'blog',
          routeBasePath: 'blog',
          showReadingTime: false,
          onUntruncatedBlogPosts: 'ignore',
        },
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  plugins: [
    [
      '@docusaurus/plugin-content-docs',
      {
        id: 'apps',
        path: 'apps',
        routeBasePath: 'apps',
        sidebarPath: './sidebars/apps.ts',
      },
    ],
  ],

  themes: [
    [
      '@easyops-cn/docusaurus-search-local',
      {
        hashed: true,
        indexBlog: false,
        docsRouteBasePath: ['developers', 'apps'],
        docsDir: ['developers', 'apps'],
        language: ['en'],
        searchBarShortcutHint: false,
      },
    ],
  ],

  themeConfig: {
    image: 'img/freepod.svg',
    colorMode: {
      defaultMode: 'dark',
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Freepod',
      logo: {
        alt: 'Freepod',
        src: 'img/freepod.svg',
        href: '/docs/',
        target: '_self',
      },
      items: [
        { type: 'docSidebar', docsPluginId: 'apps', sidebarId: 'apps', label: 'Using apps', position: 'left' },
        { type: 'docSidebar', sidebarId: 'developers', label: 'Developers', position: 'left' },
        { to: '/blog', label: 'Blog', position: 'left' },
        { href: 'https://freepod.eu/', label: 'Open Freepod', position: 'right', target: '_self' },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            { label: 'Using apps', to: '/apps' },
            { label: 'Developers', to: '/developers' },
          ],
        },
        {
          title: 'Legal',
          items: [
            { label: 'Terms of Service', href: 'https://freepod.eu/legal/terms', target: '_self' },
            { label: 'Privacy Policy', href: 'https://freepod.eu/legal/privacy', target: '_self' },
            { label: 'Acceptable Use Policy', href: 'https://freepod.eu/legal/aup', target: '_self' },
            { label: 'Data Processing Agreement', href: 'https://freepod.eu/legal/dpa', target: '_self' },
          ],
        },
        {
          title: 'Support',
          items: [{ label: 'support@freepod.eu', href: 'mailto:support@freepod.eu' }],
        },
      ],
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'json', 'python', 'go', 'yaml', 'docker'],
    },
  } satisfies Preset.ThemeConfig,
}

export default config
