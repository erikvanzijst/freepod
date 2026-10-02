import { themes as prismThemes } from 'prism-react-renderer'
import type { Config } from '@docusaurus/types'
import type * as Preset from '@docusaurus/preset-classic'
import appLinks from './src/remark/app-links.mjs'

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
          remarkPlugins: [appLinks],
          path: 'developers',
          routeBasePath: 'developers',
          sidebarPath: './sidebars/developers.ts',
        },
        blog: {
          remarkPlugins: [appLinks],
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
        remarkPlugins: [appLinks],
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
      },
      items: [
        { type: 'docSidebar', docsPluginId: 'apps', sidebarId: 'apps', label: 'Using apps', position: 'left' },
        { type: 'docSidebar', sidebarId: 'developers', label: 'Developers', position: 'left' },
        { to: '/blog', label: 'Blog', position: 'left' },
        { type: 'html', position: 'right', value: '<a class="navbar__item navbar__link" href="/">Open Freepod</a>' },
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
          title: 'Freepod',
          items: [
            { html: '<a class="footer__link-item" href="/">Home</a>' },
            { html: '<a class="footer__link-item" href="/dev">Developers</a>' },
          ],
        },
        {
          title: 'Legal',
          items: [
            { html: '<a class="footer__link-item" href="/legal/terms">Terms of Service</a>' },
            { html: '<a class="footer__link-item" href="/legal/privacy">Privacy Policy</a>' },
            { html: '<a class="footer__link-item" href="/legal/aup">Acceptable Use Policy</a>' },
            { html: '<a class="footer__link-item" href="/legal/dpa">Data Processing Agreement</a>' },
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
