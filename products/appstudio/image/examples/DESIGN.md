# Design

Every app starts with the same look: the app shell (header, page, footer) and
the theme in `src/index.css`. Keep it unless the user asks for another; the
pages in `/opt/appstudio/examples/src/pages/` show it applied.

- **Frame**: every page renders inside `AppShell`; pages add content only, no
  headers or footers of their own. Navigation links go in the shell's header.
- **Footer**: keep the "Hosted on Freepod" credit unless the user asks to
  remove it.
- **Components**: the shadcn/ui components in `src/components/ui/`. Add more
  with `npx shadcn add <name>` (dialog, table, select, tabs, …) instead of
  writing them by hand or adding another component library.
- **Colors**: only theme tokens (`bg-background`, `text-foreground`,
  `text-muted-foreground`, `bg-primary`, `bg-accent`, `border`, …), and the
  brand gradient `from-brand-from to-brand-to` for one accent per page (the
  logo mark, a heading word). Never hex values or palette colors like
  `bg-blue-500`. To rebrand, change the tokens in `src/index.css`.
- **Type**: Geist. Page title `text-2xl font-semibold tracking-tight` (a
  landing hero may go to `text-4xl`); section title `text-lg font-semibold`;
  body `text-sm`, secondary text `text-muted-foreground`.
- **Layout**: forms and lists in `mx-auto max-w-2xl`, dashboards and tables use
  the shell's full width (`max-w-5xl`); `gap-6` between blocks, `gap-2`–`gap-4`
  inside them. Group related content in a `Card`.
- **Corners**: the theme's radius (10 px); don't add larger rounding.
- **Icons**: `lucide-react`, at the default size inside buttons.
- **States**: a skeleton while loading, an empty state for every list, a
  disabled submit while a form is invalid or sending, a readable error message
  for every request that fails.
- **Dark mode**: follows the system; using tokens is all it takes.
