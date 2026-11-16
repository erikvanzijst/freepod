# deployment-identity Specification

## Purpose
A deployment's own identity: the name, description and icon its owner knows it by,
falling back to its product's where the owner has set none, whatever the product.

## Requirements

### Requirement: Every deployment has a name its owner chooses

A deployment SHALL have a `name`: free-form text of 1 to 100 characters after trimming
surrounding whitespace, containing no control characters. It SHALL be stored as
entered, apart from the trimming. A name failing these rules SHALL be refused with `400`.

#### Scenario: A name with spaces and capitals

- **WHEN** a deployment is created with name `  Family photos `
- **THEN** its name reads `Family photos`

#### Scenario: A name with a control character

- **WHEN** a deployment is named with a string containing a newline
- **THEN** the request is refused with `400` and nothing is changed

#### Scenario: An empty name

- **WHEN** a deployment is named with a string of only spaces
- **THEN** the request is refused with `400`

### Requirement: A name is unique among its owner's live deployments

No two deployments of one owner that are not `deleted` SHALL have names equal when
compared case-insensitively. A write that would make two equal SHALL be refused with
`409` and code `name_in_use`. Deployments of different owners MAY share a name. A
deleted deployment's name SHALL be free for reuse.

#### Scenario: A duplicate name for the same owner

- **WHEN** an owner with a deployment named `Arkanoid` creates another named `arkanoid`
- **THEN** the request is refused with `409` and code `name_in_use`

#### Scenario: The same name for two owners

- **WHEN** two owners each name a deployment `Arkanoid`
- **THEN** both are accepted

#### Scenario: Reusing a deleted deployment's name

- **WHEN** an owner deletes the deployment named `Arkanoid` and creates another with that name
- **THEN** the creation is accepted

### Requirement: A deployment created without a name is named after its product

A create that names no deployment SHALL name it after its product's name. If that name
is in use, the platform SHALL append ` 2`, ` 3` and so on, taking the first free one.

#### Scenario: A first Nextcloud

- **WHEN** an owner with no deployments creates a Nextcloud deployment without a name
- **THEN** it is named `Nextcloud`

#### Scenario: A second Nextcloud

- **WHEN** the same owner creates another Nextcloud deployment without a name
- **THEN** it is named `Nextcloud 2`

### Requirement: A name can be changed and nothing else follows it

The owner SHALL be able to rename a deployment at any status other than `deleting` or
`deleted`. A rename SHALL change neither the hostname nor the release name, SHALL create
no release, and SHALL queue no reconcile.

#### Scenario: Renaming a running app

- **WHEN** the owner renames a `ready` deployment from `arkanoid` to `Arkanoid: Space Edition`
- **THEN** its name reads `Arkanoid: Space Edition`
- **AND** its hostname, release name and desired release are unchanged
- **AND** no reconcile is queued

### Requirement: Description and icon fall back to the product's

A deployment MAY carry its own `description`, up to 500 characters, and its own icon.
Where it carries none, every surface that shows the deployment SHALL show its product's
description or icon. Clearing either SHALL restore the product's.

#### Scenario: A Custom deployment with its own icon

- **WHEN** a Custom deployment has an icon of its own
- **THEN** its dashboard row shows that icon, not the Custom product's

#### Scenario: A catalog app with no override

- **WHEN** a Nextcloud deployment has no description or icon of its own
- **THEN** its row shows Nextcloud's icon and description

#### Scenario: Clearing an override

- **WHEN** the owner clears a deployment's icon
- **THEN** the product's icon is shown again

### Requirement: A deployment icon is stored only as a re-encoded raster image

An icon SHALL be sent in a create or update as base64 `icon`, and SHALL be a PNG, JPEG
or WebP image of at most 256 KiB before encoding. Any other format, SVG included, and a
larger image SHALL be refused with `400`. The platform SHALL decode the image and store
a re-encoded PNG of at most 256×256 pixels, never the sent bytes. It SHALL record the
SHA-256 of the sent bytes, and an icon whose hash equals the recorded one SHALL be left
as it is without being decoded again.

#### Scenario: An SVG icon

- **WHEN** an update carries an SVG as the deployment's icon
- **THEN** the request is refused with `400`

#### Scenario: A large PNG

- **WHEN** an update carries a 1024×1024 PNG within the size limit
- **THEN** the stored icon is a PNG no larger than 256×256

#### Scenario: An oversized icon

- **WHEN** an update carries an icon larger than 256 KiB
- **THEN** the request is refused with `400`, naming the limit

#### Scenario: The same icon sent again

- **WHEN** an update carries the bytes the stored icon was made from
- **THEN** the icon is unchanged and is not re-encoded

### Requirement: Deployment reads report the identity

Every deployment read, single and listed, SHALL include `name`, `description` and
`icon_url`. `description` and `icon_url` SHALL be null where the deployment has none of
its own. The product's own values SHALL remain available in the read's template, for
the fallback. Reads SHALL NOT report the generated release name.

#### Scenario: A deployment with no overrides

- **WHEN** a deployment with no description or icon of its own is read
- **THEN** `description` and `icon_url` are null and `name` is set

### Requirement: Identity is written by the deployment create and update

The deployment create and update SHALL be the only writes of `name`, `description` and
`icon`. They SHALL be authorized as other deployment writes are. The operator CLI's
create and update commands SHALL accept the same fields.

#### Scenario: Editing the description

- **WHEN** the owner sends an update holding only a new description
- **THEN** the description is changed and no release is created

#### Scenario: Another user's deployment

- **WHEN** a user who is neither the owner nor an administrator sends an update changing a deployment's name
- **THEN** the request is refused as other deployment writes are

### Requirement: Existing deployments receive a meaningful name

The migration that introduces the identity SHALL name every existing deployment, in a
new column beside the generated release name, which keeps its column. A
`custom` deployment on a tenant hostname SHALL be named after its hostname's
application label. One on a custom domain SHALL be named after the whole domain. Any
other deployment SHALL be named after its product. Every name SHALL then be made unique
per owner by the same numeric suffix rule as at create.

#### Scenario: A Custom deployment under the account handle

- **WHEN** a `custom` deployment's hostname is `arkanoid-erik.freepod.app`
- **THEN** after the migration it is named `arkanoid`

#### Scenario: Two Nextclouds of one owner

- **WHEN** an owner has two Nextcloud deployments before the migration
- **THEN** afterwards they are named `Nextcloud` and `Nextcloud 2`

### Requirement: Sign in with Freepod shows the deployment's identity

The Sign in with Freepod pages for a deployment SHALL show the deployment's name and
its effective icon, where they showed the product's name and icon before.

#### Scenario: Signing in to a Custom app

- **WHEN** a visitor reaches the sign-in page of a Custom deployment named `Arkanoid` with its own icon
- **THEN** the page names `Arkanoid` and shows that icon
