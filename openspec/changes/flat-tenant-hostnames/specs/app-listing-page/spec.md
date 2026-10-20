# Spec Delta

## ADDED Requirements

### Requirement: A signed-in visitor's Install opens the deploy dialog
For a signed-in visitor, Install SHALL open the existing deploy dialog for
that product over the app page, with the plan chosen on the page preselected.
The dialog's existing gates, such as claiming a handle first, SHALL still
apply. Closing the dialog SHALL leave the visitor on the app page; only a
successful launch SHALL take them to the dashboard.

#### Scenario: Signed-in install with a chosen plan
- **WHEN** a signed-in visitor chooses the Pro plan on the Immich page and
  selects Install
- **THEN** the deploy dialog for Immich opens over the Immich page with the
  Pro plan selected

#### Scenario: Install canceled
- **WHEN** the visitor closes the deploy dialog without launching
- **THEN** they are still on the Immich page

#### Scenario: Install launched
- **WHEN** the visitor launches the app from the dialog on a free plan
- **THEN** they are taken to the dashboard

#### Scenario: Handle not yet claimed
- **WHEN** a signed-in visitor without a handle selects Install
- **THEN** the handle claim is asked for first, and the deploy dialog opens
  with the chosen plan once it is claimed

## MODIFIED Requirements

### Requirement: Install from the catalog follows the app page's install
Install in a catalog preview SHALL behave as Install on the app page: for a
signed-in visitor it SHALL open the install flow, with the handle claim
first when needed, over the catalog; for an anonymous visitor it SHALL start
sign-up and return them to the app's page with the deploy dialog open. A
chosen plan SHALL carry through in both cases.

#### Scenario: Signed-in install from a row
- **WHEN** a signed-in visitor holding a handle selects Install in the
  Vaultwarden preview
- **THEN** the deploy dialog for Vaultwarden opens over the catalog

#### Scenario: Anonymous install from a row
- **WHEN** an anonymous visitor selects Install in the Vaultwarden preview and
  completes sign-up
- **THEN** they land on the Vaultwarden page with its deploy dialog open

## REMOVED Requirements

### Requirement: Install opens the deploy dialog for a signed-in visitor
**Reason**: The claim that may precede the dialog is now the handle claim.
**Migration**: See *A signed-in visitor's Install opens the deploy dialog*.
