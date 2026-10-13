# apps-dashboard Specification

## Purpose

Present the signed-in dashboard as the list of the user's own apps, each in
plain language with its details and actions one expansion away, and keep the
app catalog one click away without leaving the dashboard.

## Requirements

### Requirement: The dashboard lists the user's own apps
The dashboard SHALL list the signed-in user's deployments under "Your apps"
and SHALL NOT list the product catalog itself. It SHALL offer adding an app
from a button beside the heading and from a row at the end of the list, both
opening the app catalog in a side panel over the dashboard. A user with no
deployments SHALL see a few starter apps from the storefront in place of the
list, and a way to open the full catalog. The signed-in navigation SHALL link
to `/apps`.

#### Scenario: Catalog opens in a side panel
- **WHEN** a user selects "Add an app" on the dashboard
- **THEN** the app catalog opens in a side panel and the dashboard stays
  underneath it

#### Scenario: Installing from the side panel
- **WHEN** a user installs an app from the side panel and it launches
- **THEN** the deploy dialog and the panel close, and the user is on the
  dashboard

#### Scenario: New user
- **WHEN** a user with no deployments opens the dashboard
- **THEN** starter apps are offered, and none of the starter apps is
  `unlisted` or `admin`

### Requirement: Each deployment is a row with a plain-language status
Each deployment SHALL be shown as a row with the app's icon and name, a
status in plain words, the deployment's address, its plan and price, its
running version and an Open action. A deployment in progress SHALL show a
progress indicator. Open SHALL be disabled until the app can be reached.

#### Scenario: Statuses in plain words
- **WHEN** deployments are `ready`, `pending`, `error` and `deleting`
- **THEN** their statuses read Running, Waiting for payment, Needs attention
  and Removing

#### Scenario: Applying changes
- **WHEN** a deployment is `provisioning` without changing version
- **THEN** its status reads "Applying changes"

#### Scenario: Update to a new version
- **WHEN** a deployment running 1.120.2 is `provisioning` toward 1.121.0
- **THEN** its status reads "Updating to 1.121.0" and Open stays available

#### Scenario: First setup
- **WHEN** a new deployment is `provisioning` for the first time
- **THEN** its status reads "Setting up" and Open is disabled

#### Scenario: Not reachable yet
- **WHEN** a deployment is waiting for payment or being removed
- **THEN** Open is disabled

#### Scenario: Plan and price
- **WHEN** a deployment is on the Personal plan at 4.99 euros a month
- **THEN** its row reads "Personal · €4.99/mo"

### Requirement: A row expands to the deployment's details and actions
Selecting a row SHALL expand it in place to the deployment's address (with a
copy action), plan, version and date added, and its actions: Settings, Files
when the deployment offers file access (described as browse and download,
read-only), Database when it has a database, and Remove app. The requests
that tell whether a deployment offers file and database access SHALL be made
only when its row is first expanded. A row whose deployment has a problem
SHALL start expanded.

#### Scenario: Collapsed rows make no access requests
- **WHEN** the dashboard renders deployments and no row is expanded
- **THEN** no file-access or database details are requested

#### Scenario: Expanding offers the database
- **WHEN** a user expands the row of a deployment with a provisioned database
- **THEN** its details are requested and the Database action is offered

### Requirement: Problems are explained, with a route to support
A deployment in `error` SHALL show a notice that explains in plain words that
the app could not finish its last change, that saving its settings again may
resolve it, and that support can help otherwise. The raw error SHALL be
hidden behind a "Show details" control, and the notice SHALL offer an email
link to support@freepod.eu prefilled with the deployment's id, address and
error. A running deployment whose subscription is in arrears SHALL show a
separate payment notice.

#### Scenario: Failed change
- **WHEN** a deployment's status is `error` with a Helm timeout as its error
- **THEN** its row reads "Needs attention", the notice explains the problem
  without showing the timeout until "Show details" is selected
- **AND** the support link opens an email to support@freepod.eu whose body
  names the deployment and the timeout

#### Scenario: Failed payment
- **WHEN** a `ready` deployment's subscription has `payment_status` `arrears`
- **THEN** its row shows a "Payment failed" notice

### Requirement: The list can be searched and sorted
The dashboard SHALL offer a search over each deployment's app (the same
fields as the catalog search), address and plan name, and a sort by newest
first (the default), oldest first, app name, or most recently updated. Both
SHALL be kept in the address (`search` and `sort`). Pressing `/` outside a
text field SHALL focus the search.

#### Scenario: Search by address
- **WHEN** a user searches their apps for part of a deployment's address
- **THEN** only deployments whose address or other searched fields contain
  it are listed

#### Scenario: Sort by name
- **WHEN** a user sorts by name
- **THEN** deployments are ordered by app name, then by address
