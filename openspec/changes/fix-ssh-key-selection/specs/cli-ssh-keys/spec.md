## MODIFIED Requirements

### Requirement: `freepod key` manages the account's keys
The client MUST provide a `key` command group with subcommands to add, list and remove the authenticated account's SSH keys, operating against the environment the invocation targets.

`list` MUST show enough to identify a key for revocation — its fingerprint and label at minimum — and MUST indicate which of the listed keys, if any, this machine **can offer**. A key is only indicated when the client would actually select it for a connection: a local record naming a file that is missing, or that no longer holds that key, MUST NOT be indicated, because no connection would use it.

Listing MUST NOT fail on an unresolvable local key. Where the client cannot choose which key this machine holds, `list` MUST indicate none and still report the account's keys.

#### Scenario: User lists their keys
- **WHEN** a user runs the list subcommand
- **THEN** their registered keys are shown with fingerprint and label

#### Scenario: Local key is marked
- **WHEN** a user runs the list subcommand on a machine that holds a registered key
- **THEN** that key is distinguished from the others in the output

#### Scenario: A key this machine cannot offer is not marked
- **WHEN** the local record names a file that is gone or no longer holds the recorded key
- **THEN** no key is distinguished as this machine's, matching what the SSH commands would do

#### Scenario: No keys registered
- **WHEN** a user with no registered keys runs the list subcommand
- **THEN** the client reports that plainly and says how to add one, rather than printing an empty table with no guidance

### Requirement: Adding an existing key records where it came from
`freepod key add <path>` MUST accept a path to an existing **public** key file, register it, and record that path locally as this machine's key. Supplying a private key path MUST be refused with an error that says so and names the corresponding public key file.

Recording the path at registration time is what makes later key selection deterministic. The client MUST NOT defer this to connection time, where it would have to guess among the user's keys.

Where the account **already holds** the named key, the client MUST record it as this machine's key and report success, rather than failing on the platform's duplicate refusal. Registering a key the account already holds is how a user states which of several keys this machine should offer, so it MUST NOT be an error. Every other refusal from the platform MUST still end the run and be reported in the platform's own words.

#### Scenario: Existing public key is registered and remembered
- **WHEN** a user runs the add subcommand naming an existing public key file
- **THEN** the key is registered and the client records that file as this machine's key

#### Scenario: Naming an already-registered key binds it to this machine
- **WHEN** a user runs the add subcommand naming a key the account already holds
- **THEN** the client records it as this machine's key, reports that it was already registered, and exits successfully

#### Scenario: Other refusals still end the run
- **WHEN** the platform refuses a submission for any reason other than the account already holding that key
- **THEN** the client reports the platform's message and exits with its error status

#### Scenario: Private key path is refused
- **WHEN** a user names a private key file
- **THEN** the client refuses, explains that a public key is required, and names the expected `.pub` file

### Requirement: A lost local record is recovered by fingerprint, not by guessing
When the local record is absent or no longer matches a registered key — a new machine, a cleared configuration directory, or a key registered through the web UI — the client MUST attempt recovery by comparing fingerprints: it computes the fingerprint of each candidate **public** key file available to it and looks for one the account has registered.

Recovery MUST operate on public key files, never on private ones, so that keys whose private half exists only in an agent or on a hardware token are still matched.

If exactly one candidate matches, the client MUST adopt it and record it. If none matches, the client MUST say so and direct the user to register a key, rather than attempting a connection that will fail.

If several match, the client MUST adopt the key it generated itself when that key is among them, and MUST otherwise ask. Every key registered on the account authenticates equally — the platform resolves a connection against the account, not against one key — so a tie including the client's own key is a question about which key this machine is bound to, and the client's own key is the answer it may give. A tie among keys the user owns MUST still be reported, naming each candidate and the command that settles it.

#### Scenario: New machine with an already-registered key
- **WHEN** a user runs a command needing a key on a machine holding a public key file whose fingerprint is registered on the account
- **THEN** the client adopts that key and records it, without the user re-registering

#### Scenario: Hardware-backed key is matched
- **WHEN** the only local material for a registered key is its public key file, the private half being held in an agent or on a security key
- **THEN** the client matches it by fingerprint and uses it

#### Scenario: No local key matches
- **WHEN** no available public key file matches any registered key
- **THEN** the client reports that no registered key is available on this machine and names the command that registers one

#### Scenario: The client's own key settles a tie
- **WHEN** several local public key files match registered keys and one of them is the key this client generated
- **THEN** the client adopts and records the generated key rather than refusing

#### Scenario: Ambiguous match is not resolved silently
- **WHEN** several local public key files match registered keys and none of them is the key this client generated
- **THEN** the client asks which to use rather than picking one, naming each candidate and a command that will bind one
