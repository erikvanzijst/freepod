## MODIFIED Requirements

### Requirement: Project files are readable over SFTP

The owner SHALL be able to copy files out of every app in the studio over the platform's SFTP access, with the same SSH keys and connection details as any other deployment. The session SHALL be read-only and SHALL expose the apps directory alone, each app as a folder in it: the rest of the workspace, which holds the owner's Freepod credentials and the studio's configuration, SHALL NOT be reachable through it.

#### Scenario: Getting a file out

- **WHEN** the owner connects over SFTP with a key registered on their account
- **THEN** they see a folder per app and can download its files

#### Scenario: Credentials stay out of reach

- **WHEN** the owner lists everything the SFTP session can reach
- **THEN** the workspace's configuration directory is not among it

#### Scenario: Read-only

- **WHEN** the owner tries to upload or delete a file over SFTP
- **THEN** the write is refused
