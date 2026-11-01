## MODIFIED Requirements

### Requirement: The owner is always admitted

The deployment's owner SHALL be admitted to a `listed` deployment without being on its list. The owner SHALL be recognized by the subject stored on their user record: when the record carries one, only a sign-in with that subject is the owner, whatever its email. Only while the record carries no subject SHALL the owner be recognized by email, case-insensitively. The owner SHALL NOT be an entry on the list, and no operation on the list SHALL be able to refuse the owner.

#### Scenario: Owner with an empty list

- **WHEN** the owner signs in to a `listed` deployment whose list is empty
- **THEN** the owner reaches the app

#### Scenario: Owner who changed their email

- **WHEN** the owner's record carries their subject and the owner signs in with an email address the record does not hold
- **THEN** the owner reaches the app

#### Scenario: The owner's former address under another account

- **WHEN** the owner's record carries a subject, and a different Freepod account that now holds the email stored on the owner's record signs in to a `listed` deployment and is not on its list
- **THEN** it is refused as a stranger

#### Scenario: Owner without a stored subject

- **WHEN** the owner's record carries no subject and the owner signs in with the email the record holds
- **THEN** the owner reaches the app

#### Scenario: Adding the owner

- **WHEN** the owner asks to add their own email to the list
- **THEN** the request is refused as a duplicate and the list is unchanged
