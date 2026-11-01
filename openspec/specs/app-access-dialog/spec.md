# app-access-dialog Specification

## Purpose
How the dashboard and the admin deployment dialog show who may sign in to a deployment and let its owner edit the access list, driven only by the deployment's authentication settings and never by its product.

## Requirements

### Requirement: The Access action follows the authentication settings

A deployment's expanded dashboard row SHALL offer an Access action exactly when its read model reports `auth.enabled` and `auth.access: listed`. Whether it appears SHALL NOT depend on the deployment's product.

#### Scenario: Listed deployment

- **WHEN** the owner expands the row of a deployment whose read model reports enabled and `listed`
- **THEN** the row offers Access beside its other actions

#### Scenario: Anyone

- **WHEN** a deployment's read model reports enabled and `anyone`
- **THEN** its row offers no Access action

#### Scenario: Any product

- **WHEN** an App Studio deployment and a custom deployment both report enabled and `listed`
- **THEN** both rows offer the same Access action

### Requirement: The row says who can sign in

When a deployment's read model reports `auth.enabled`, its expanded row SHALL state who can sign in: for `listed`, the owner alone or the owner and the number of listed people; for `anyone`, that the app itself manages it, named by the app's name. Its collapsed row SHALL show the `listed` summary after the status. A deployment without `auth.enabled` SHALL show neither.

#### Scenario: Listed with people

- **WHEN** a `listed` deployment has three entries
- **THEN** its expanded row reads "You and 3 people"

#### Scenario: Managed by the app

- **WHEN** a deployment of a product named "Gallery" reports enabled and `anyone`
- **THEN** its expanded row reads "Managed in Gallery", with no link

### Requirement: The Access dialog shows the owner and every entry

The Access dialog SHALL list the owner first, marked as always having access and with no way to remove them, then every entry. An entry tied to an account SHALL show the person's name when known, their email, and when they first signed in. An unbound entry SHALL show its email, when it was added, and that nobody has signed in with it yet.

#### Scenario: Mixed list

- **WHEN** the owner opens Access on a deployment with one bound entry and one unbound entry
- **THEN** the dialog shows the owner, the bound entry with its first sign-in date, and the unbound entry as invited and not yet signed in

### Requirement: Adding someone from the dialog

The dialog SHALL let the owner add someone by email. It SHALL say that the person will receive an invitation. When the API refuses the addition, the dialog SHALL keep the typed address and show the reason beside the field: invalid address, already on the list, list full, or invitation limit reached.

#### Scenario: Already on the list

- **WHEN** the owner adds `Jules@example.org` and `jules@example.org` is already listed
- **THEN** the field keeps the address and says it is already on the list

### Requirement: Removal is confirmed in place

Removing an entry SHALL first ask for confirmation within the entry's row, saying that the person loses access within a minute and that what they stored in the app stays. The dialog SHALL offer no undo after a removal.

#### Scenario: Confirm a removal

- **WHEN** the owner chooses to remove Ana
- **THEN** Ana's row asks for confirmation, and only confirming removes the entry

### Requirement: Long lists can be searched

When a list holds more than 10 entries, the dialog SHALL offer a search over emails and names and a filter for all, signed in, and not yet signed in entries. It SHALL show how many entries match and how many of the 500 places are used. The list SHALL scroll inside the dialog, keeping the add field in view.

#### Scenario: Searching a long list

- **WHEN** the owner types `sam` into the search of a list with 214 entries
- **THEN** the dialog shows only entries whose email or name contains `sam`, and says how many of 214 match

#### Scenario: Short list

- **WHEN** a list holds 4 entries
- **THEN** the dialog offers no search or filter

### Requirement: The dialog is the same for every product

The Access dialog SHALL show nothing specific to a product beyond the deployment's app name and address. It SHALL NOT refer to a product's own configuration files or settings.

#### Scenario: Custom app

- **WHEN** the owner opens Access on a custom deployment
- **THEN** the dialog has the same content and controls as for any other product

### Requirement: Administrators see access read-only

The admin deployment dialog SHALL show, for a deployment whose read model reports `auth.enabled`, its access mode and, for `listed`, every entry with its email and whether and when it was first used. It SHALL offer no way to change the list.

#### Scenario: Admin views a listed deployment

- **WHEN** an administrator opens a `listed` deployment in the admin dialog
- **THEN** the dialog shows its entries read-only
