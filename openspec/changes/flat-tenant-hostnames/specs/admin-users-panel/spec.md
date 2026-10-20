# Spec Delta

## MODIFIED Requirements

### Requirement: Users table lists all users
The users panel SHALL display a table containing every user returned by
`GET /api/users`. Each row SHALL show the user's id, email, admin status,
handle, and join date. The handle SHALL be shown as the user's `handle` as
returned by the API. A user who has not claimed a handle SHALL show an empty
handle cell.

#### Scenario: Table populated
- **WHEN** an admin opens the Users tab and the user list has loaded
- **THEN** the table SHALL contain one row per user
- **AND** each row SHALL show the user's id, email, admin status, handle,
  and join date

#### Scenario: An unclaimed handle is an empty cell
- **WHEN** a listed user holds no handle
- **THEN** their handle cell is empty

#### Scenario: Loading state
- **WHEN** the user list has not yet loaded
- **THEN** the panel SHALL display a loading indicator in place of the table
