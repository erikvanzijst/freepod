# admin-users-panel Specification

## Purpose
Gives admins a view of all platform users in the admin UI: a paginated,
sortable, searchable table of users with each user's deployment count, so
operators can see who is on the platform without database access.

## Requirements

### Requirement: Users tab in admin navigation
The admin sidebar SHALL include a "Users" tab alongside the existing
Products, Deployments, and Plans tabs. Selecting it SHALL navigate to
`/admin/users` and display the users panel. Access to the tab SHALL be gated
the same way as the rest of the admin surface (visible to admins only).

#### Scenario: Admin sees the Users tab
- **WHEN** an admin user opens the admin area
- **THEN** the sidebar SHALL list a "Users" tab
- **AND** selecting it SHALL display the users panel at `/admin/users`

#### Scenario: Non-admin does not see the admin surface
- **WHEN** a non-admin user is signed in
- **THEN** the admin entry point SHALL NOT be shown, consistent with the
  existing admin gating

### Requirement: Users table lists all users
The users panel SHALL display a table containing every user returned by
`GET /api/users`. Each row SHALL show the user's id, email, admin status,
subdomain, and join date. The subdomain SHALL be shown as the user's
`wildcard_domain` as returned by the API (`*.<subdomain>.<platform domain>`,
the name every host the account deploys is addressed under). A user who has
not claimed a subdomain SHALL show an empty subdomain cell.

#### Scenario: Table populated
- **WHEN** an admin opens the Users tab and the user list has loaded
- **THEN** the table SHALL contain one row per user
- **AND** each row SHALL show the user's id, email, admin status, subdomain,
  and join date

#### Scenario: Loading state
- **WHEN** the user list has not yet loaded
- **THEN** the panel SHALL display a loading indicator in place of the table

### Requirement: Client-side pagination
The users table SHALL paginate client-side, with a page size selector
consistent with the Deployments tab (25, 50, 100).

#### Scenario: More users than one page
- **WHEN** there are more users than the current page size
- **THEN** the table SHALL show only one page of rows at a time with
  pagination controls to move between pages

#### Scenario: Change page size
- **WHEN** the admin selects a different page size
- **THEN** the table SHALL re-paginate using the new page size

### Requirement: Sortable columns
Every column in the users table SHALL be sortable. The default sort SHALL
be join date descending (newest users first).

#### Scenario: Sort by a column
- **WHEN** the admin clicks a column header
- **THEN** the rows SHALL be sorted by that column, toggling between
  ascending and descending

#### Scenario: Default order
- **WHEN** the table first loads
- **THEN** rows SHALL be ordered by join date, newest first

### Requirement: Search by email
The users panel SHALL provide a search box that filters the table by email.
Matching SHALL be case-insensitive and SHALL match any substring of the
email address. The user model has no username field, so email is the only
identity field that can be searched.

#### Scenario: Search narrows rows
- **WHEN** the admin types a substring of a user's email into the search box
- **THEN** the table SHALL show only the rows whose email contains that
  substring, ignoring case

#### Scenario: No matches
- **WHEN** the search text matches no user's email
- **THEN** the table SHALL show no rows

#### Scenario: Clearing search
- **WHEN** the admin clears the search box
- **THEN** the table SHALL show all users again

### Requirement: Per-user deployment count
Each row in the users table SHALL show the number of deployments the user
has. The count SHALL be derived from the admin deployments list
(`GET /api/deployments`), which excludes deleted deployments. A user with
no non-deleted deployments SHALL show a count of zero.

#### Scenario: User with deployments
- **WHEN** a user has three non-deleted deployments
- **THEN** the user's row SHALL show a deployment count of 3

#### Scenario: User without deployments
- **WHEN** a user has no non-deleted deployments
- **THEN** the user's row SHALL show a deployment count of 0

#### Scenario: Deleted deployments not counted
- **WHEN** a user's only deployment has been deleted
- **THEN** the user's row SHALL show a deployment count of 0
