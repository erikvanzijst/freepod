## Context

The catalog is expected to grow to around fifteen apps, and some users run
many deployments of the developer product. Both lists must stay usable at
that size, on a phone as well as a desktop.

## Decisions

### D1: Rows that expand in place, for both lists

The catalog and the dashboard use the same shape: a compact row that expands
to the details. A row scans quickly when there are many, and expanding keeps
the reader's place, where a separate detail page or a modal would not. The
catalog row's preview links on to the full app page for everything else.

### D2: The dashboard stops repeating the catalog

`/apps` is the one place to browse. The dashboard opens the same catalog list
in a side panel rather than navigating away, so an install that starts on the
dashboard ends there, with the new app in the list.

### D3: Access details are requested when a row expands

The file and database actions each depend on a request that tells whether the
deployment offers them. Made for every row on load, a user with twenty
deployments would trigger forty requests to show a list. They are made when a
row first expands, which is when the actions become visible.

### D4: `noindex` is set by the page at run time

Visibility lives in the database and an administrator can change it at any
time, while the per-app HTML is built from the catalog at image build time.
The build cannot know whether a page is public, so the app page adds a
`robots` `noindex` tag once the product has resolved. Search engines that
render the page honor it; unlisted pages are also not linked from anywhere
public, which keeps them out of crawls in the first place.

### D5: Statuses describe what the user can expect

| Deployment state | Shown as |
|---|---|
| `ready` | Running |
| `pending` | Waiting for payment |
| `provisioning`, first generation | Setting up |
| `provisioning`, new version | Updating to *version* |
| `provisioning`, same version | Applying changes |
| `error` | Needs attention |
| `deleting` | Removing |

## Risks

- Crawlers that do not run JavaScript see an unlisted app's prebuilt page
  without `noindex`. Accepted: the page is unlinked, and its content is the
  product's public catalog entry.
