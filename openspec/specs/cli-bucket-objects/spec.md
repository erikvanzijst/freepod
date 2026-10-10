# cli-bucket-objects Specification

## Purpose

Lets a developer work with the objects in their deployment's bucket from their own machine:
list them, copy and move them in both directions and within the bucket, delete them, stream
them to stdout, and hand out presigned URLs. The client talks to the bucket directly over its
public S3 endpoint using the credentials the platform gives the owner.

## Requirements

### Requirement: Object commands reach the bucket directly with credentials fetched per run
The `bucket` command group MUST provide `ls`, `cp`, `mv`, `rm`, `cat` and `link` subcommands acting on the bucket of the deployment recorded in the project file, resolved as the other project-scoped commands resolve it.

Each invocation MUST obtain the bucket's credentials from the platform's bucket endpoint without requesting usage, and MUST then talk to the S3 endpoint the platform named, directly rather than through the deployment's pod. Nothing about the endpoint, region or bucket name MUST be hardcoded in the client.

The credentials MUST be held in memory for the duration of the invocation only. They MUST NOT be written to disk, and the secret MUST NOT be printed or included in any diagnostic output, including verbose output.

#### Scenario: Credentials come from the platform
- **WHEN** a developer runs any object command
- **THEN** the client reads the bucket details from the platform with usage opted out
- **AND** sends its S3 requests to the endpoint the platform returned

#### Scenario: Nothing is stored
- **WHEN** an object command has completed
- **THEN** no file written by the client contains the secret access key

#### Scenario: Verbose output carries no secret
- **WHEN** an object command runs with `--verbose`
- **THEN** no output contains the secret access key or a request signature computed from it, other than the URL `link` is asked to print

#### Scenario: Deployment without a bucket
- **WHEN** an object command runs in a project whose deployment has no bucket
- **THEN** the command exits non-zero, saying the deployment has no bucket

#### Scenario: Secret withheld
- **WHEN** an administrator runs an object command against a deployment they do not own
- **THEN** the command exits non-zero, saying the bucket's contents are reachable by its owner alone, and sends no S3 request

### Requirement: Remote paths are marked with a leading colon and rooted at the bucket
A path beginning with `:` MUST name a location in the bucket. Everything after the colon is the key or prefix, with any leading `/` removed, so `:`, `:/`, `:a/b` and `:/a/b` name the root, the root, and `a/b` twice.

`ls`, `rm`, `cat` and `link` act only on the bucket. Their arguments MUST be read as remote paths whether or not they carry the colon, and these commands MUST NOT read, list or delete local files.

`cp` and `mv` MUST take a source and a destination, at least one of them marked. When exactly one is marked, the marked side is the bucket and the direction follows from it. When both are marked, the operation happens within the bucket. A `cp` or `mv` with neither side marked MUST be refused before any request is sent, as a local operation the user's own shell already performs.

#### Scenario: Leading slash is the same key
- **WHEN** a developer runs `freepod bucket cat :/a/b.txt`
- **THEN** the object with key `a/b.txt` is printed

#### Scenario: Colon optional where only the bucket is meant
- **WHEN** a developer runs `freepod bucket ls uploads`
- **THEN** the bucket's `uploads` prefix is listed, not a local directory

#### Scenario: Direction follows the marked side
- **WHEN** a developer runs `freepod bucket cp report.csv :reports/`
- **THEN** the local file is uploaded to the key `reports/report.csv`

#### Scenario: Neither side marked
- **WHEN** a developer runs `freepod bucket cp a.txt b.txt`
- **THEN** the client refuses, telling them to mark the bucket's side with `:`, and sends no request

### Requirement: A remote path names an object or a prefix, the object first
A remote path without a trailing `/` MUST name the object with exactly that key when one exists, and otherwise the prefix formed by adding `/`, when objects exist under it. A remote path with a trailing `/` MUST name the prefix only. The bucket root is a prefix.

A path naming neither an existing object nor a prefix holding objects MUST be reported as not found by commands that read it.

#### Scenario: Object and prefix share a name
- **GIVEN** the bucket holds both an object `x` and objects under `x/`
- **WHEN** a developer runs `freepod bucket cat :x`
- **THEN** the object `x` is printed
- **AND** `freepod bucket ls :x/` lists the objects under `x/`

#### Scenario: Missing path
- **WHEN** a developer runs `freepod bucket ls :nothing-here`
- **THEN** the command exits non-zero, saying no such object or prefix exists

### Requirement: `ls` lists a prefix, one level or the whole tree
`freepod bucket ls [path]` MUST list the bucket root when no path is given. On a prefix, it MUST list that prefix's immediate children: objects by name, and sub-prefixes by name with a trailing `/`. On an object, it MUST list that object alone.

`-r` MUST list every object under the prefix, recursively, by its key relative to the listed prefix, with no sub-prefix entries. `-l` MUST add each object's size and last-modified time. Both MUST work together.

An empty bucket listed at its root MUST produce no entries and exit successfully.

#### Scenario: One level
- **GIVEN** the bucket holds `a.txt`, `img/1.png` and `img/2.png`
- **WHEN** a developer runs `freepod bucket ls`
- **THEN** the output lists `a.txt` and `img/`

#### Scenario: Recursive
- **GIVEN** the same bucket
- **WHEN** a developer runs `freepod bucket ls -r :img`
- **THEN** the output lists `1.png` and `2.png`

#### Scenario: Long format
- **WHEN** a developer runs `freepod bucket ls -l`
- **THEN** each listed object is shown with its size and last-modified time

#### Scenario: Empty bucket
- **WHEN** a developer lists the root of an empty bucket
- **THEN** nothing is listed and the command exits successfully

### Requirement: `cp` copies files and trees, recursively without a flag
`freepod bucket cp` MUST copy a file or object, and MUST copy a local directory or a remote prefix recursively without being asked, as `freepod cp` copies directories.

Destination rules:
- A single file or object copied to a remote destination ending in `/`, or to the bucket root, MUST land at that prefix plus the source's base name. Copied to a remote destination without a trailing `/`, it MUST land at exactly that key.
- A single object copied to an existing local directory MUST land inside it under the object's base name. Otherwise it MUST be written at exactly the local path given.
- A directory or prefix MUST have its contents copied under the destination, keeping their relative structure, without an extra level named after the source.

Copies MUST overwrite an existing object or local file at the destination without asking. A copy within the bucket MUST be performed by the object store itself; the objects' contents MUST NOT pass through the client.

Local directories without files have no representation in the bucket and MUST NOT be uploaded. When downloading, a zero-length object whose key ends in `/` MUST produce a directory rather than a file.

#### Scenario: File into a prefix
- **WHEN** a developer runs `freepod bucket cp ./photo.jpg :images/`
- **THEN** the object `images/photo.jpg` holds the file's contents

#### Scenario: File to an exact key
- **WHEN** a developer runs `freepod bucket cp ./photo.jpg :images/cover.jpg`
- **THEN** the object `images/cover.jpg` holds the file's contents

#### Scenario: Directory to a prefix
- **GIVEN** a local directory `site` holding `index.html` and `css/main.css`
- **WHEN** a developer runs `freepod bucket cp ./site :public`
- **THEN** the objects `public/index.html` and `public/css/main.css` exist

#### Scenario: Prefix to a local directory
- **WHEN** a developer runs `freepod bucket cp :public ./backup`
- **THEN** `./backup/index.html` and `./backup/css/main.css` exist locally

#### Scenario: Object into a local directory
- **GIVEN** `./downloads` is an existing directory
- **WHEN** a developer runs `freepod bucket cp :public/index.html ./downloads`
- **THEN** `./downloads/index.html` holds the object's contents

#### Scenario: Within the bucket
- **WHEN** a developer runs `freepod bucket cp :public :public-old`
- **THEN** every object under `public/` also exists under `public-old/`
- **AND** none of their contents were transferred to or from the client

#### Scenario: Overwrite
- **GIVEN** the object `a.txt` exists
- **WHEN** a developer copies a different file to `:a.txt`
- **THEN** the object holds the new contents and the command did not prompt

### Requirement: A downloaded key is made a safe local path, or skipped
When a download, by `cp` or `mv`, turns an object key into a local path, the client MUST normalize the key relative to the destination: empty and `.` segments are dropped and `..` segments are resolved. A key whose normalized path is still outside the destination MUST be skipped with a warning that names it, and nothing MUST be written for it.

A key whose local path cannot be written because of another key, such as an object `a` alongside objects under `a/`, or that resolves to a path already written by an earlier key in the same run, MUST be skipped with a warning that names it. The client MUST NOT list the whole source before starting in order to detect these in advance.

A copy that skipped any key MUST finish the remaining keys and then exit non-zero.

#### Scenario: Normalizable key
- **GIVEN** the bucket holds `foo/bar/../quux/file.txt`
- **WHEN** a developer runs `freepod bucket cp : ./out`
- **THEN** the object is written to `./out/foo/quux/file.txt`

#### Scenario: Escaping key
- **GIVEN** the bucket holds `../../../../escape.txt`
- **WHEN** a developer runs `freepod bucket cp : ./out`
- **THEN** no file is written outside `./out`
- **AND** a warning names the skipped key
- **AND** the command exits non-zero after copying the other objects

#### Scenario: File and directory collide
- **GIVEN** the bucket holds both `plain/a` and `plain/a/b`
- **WHEN** a developer downloads the root
- **THEN** whichever of them cannot be written is skipped with a warning naming it
- **AND** the command exits non-zero

### Requirement: Large uploads go up in parts and interrupted ones are aborted
An upload of a file above a fixed size threshold MUST use a multipart upload. An upload that fails, or is interrupted by the user, MUST abort its multipart upload before the client exits, so its parts do not keep holding disk until the bucket's lifecycle rule removes them.

Every upload MUST be verified by the object store against the content the client read, so that a corrupted transfer is refused rather than stored.

#### Scenario: Large file
- **WHEN** a developer uploads a file larger than the threshold
- **THEN** it is transferred as a multipart upload and the stored object is byte-identical to the file

#### Scenario: Interrupted upload
- **WHEN** a developer interrupts a multipart upload with Ctrl-C
- **THEN** the client aborts the multipart upload
- **AND** no object appears at the destination key
- **AND** the command exits non-zero

### Requirement: An interrupted download leaves no partial file behind
A download MUST write each object to a temporary file beside its destination and move it into place only once the object has been received completely, so that an interrupted or failed download never leaves a truncated file at the destination path.

#### Scenario: Interrupted download
- **WHEN** a download of a large object is interrupted
- **THEN** no file exists at the destination path that was not there before, and no temporary file remains

### Requirement: `mv` is a copy followed by deleting the source
`freepod bucket mv` MUST accept the same paths and apply the same destination rules as `cp`, and MUST delete each source object or local file only after its copy has completed. Local directories emptied by a move MUST be removed.

A move within the bucket MUST be a server-side copy followed by a delete, and MUST NOT transfer the objects' contents through the client.

A move is not atomic. If a copy fails, its source MUST remain. A source left behind MUST be reported, and the command MUST exit non-zero.

#### Scenario: Rename within the bucket
- **WHEN** a developer runs `freepod bucket mv :draft.txt :final.txt`
- **THEN** the object `final.txt` holds the former contents of `draft.txt`
- **AND** `draft.txt` no longer exists
- **AND** the contents were not transferred to or from the client

#### Scenario: Upload and remove
- **WHEN** a developer runs `freepod bucket mv ./exports :exports`
- **THEN** the files exist under `exports/` in the bucket
- **AND** the local `./exports` directory no longer exists

#### Scenario: Download and remove
- **WHEN** a developer runs `freepod bucket mv :exports ./exports`
- **THEN** the objects exist locally under `./exports`
- **AND** no objects remain under `exports/` in the bucket

#### Scenario: Copy fails partway
- **WHEN** one object of a prefix move fails to copy
- **THEN** that object's source remains and is reported
- **AND** the command exits non-zero

### Requirement: `rm` deletes an object, or a prefix only when asked to recurse
`freepod bucket rm` MUST delete the objects it names. A path naming a prefix MUST be refused unless `-r` is given, with a refusal that says `-r` deletes everything under it. With `-r`, every object under the prefix MUST be deleted. A path naming nothing MUST be reported as not found and exit non-zero.

Unlike `cp` and `mv`, `rm` requires the flag: it is the one command that cannot be undone, and the bucket keeps no previous versions.

#### Scenario: Delete an object
- **WHEN** a developer runs `freepod bucket rm :a.txt`
- **THEN** the object `a.txt` no longer exists

#### Scenario: Prefix without the flag
- **WHEN** a developer runs `freepod bucket rm :uploads` and `uploads/` holds objects
- **THEN** the command refuses, nothing is deleted, and the refusal mentions `-r`

#### Scenario: Prefix with the flag
- **WHEN** a developer runs `freepod bucket rm -r :uploads`
- **THEN** no objects remain under `uploads/`

#### Scenario: Nothing to delete
- **WHEN** a developer runs `freepod bucket rm :missing.txt` and no such object exists
- **THEN** the command exits non-zero, saying so

### Requirement: `cat` streams objects to stdout unchanged
`freepod bucket cat` MUST write the contents of each object it names to stdout, in argument order, exactly as stored and while they arrive, without buffering a whole object and without inspecting or transforming the bytes. A path naming a prefix MUST be refused.

#### Scenario: Streaming
- **WHEN** a developer pipes `freepod bucket cat :dump.sql` into another program
- **THEN** that program receives the object's bytes exactly as stored

#### Scenario: Several objects
- **WHEN** a developer runs `freepod bucket cat :a.txt :b.txt`
- **THEN** stdout carries `a.txt` followed by `b.txt`

#### Scenario: Prefix
- **WHEN** a developer runs `freepod bucket cat :uploads` and `uploads` is a prefix
- **THEN** the command exits non-zero, saying it names a prefix rather than an object

### Requirement: `link` prints a presigned URL
`freepod bucket link` MUST print a presigned URL for one key: a GET URL by default, or a PUT URL with `--put`. `--expires` MUST set its lifetime, defaulting to one hour, and a lifetime longer than seven days MUST be refused.

The URL MUST be the only output on stdout. A GET link MUST be refused for a key with no object. A PUT link MUST be issued whether or not an object exists at the key.

The URL MUST work for a holder with no other credentials until it expires.

#### Scenario: Download link
- **WHEN** a developer runs `freepod bucket link :report.pdf` and fetches the printed URL with no credentials
- **THEN** the object's contents are returned

#### Scenario: Upload link
- **WHEN** a developer runs `freepod bucket link --put :incoming/data.csv` and sends a PUT with a body to the printed URL
- **THEN** the object `incoming/data.csv` holds that body

#### Scenario: Lifetime too long
- **WHEN** a developer runs `freepod bucket link --expires 8d :report.pdf`
- **THEN** the command refuses and prints no URL

#### Scenario: Missing object
- **WHEN** a developer requests a GET link for a key with no object
- **THEN** the command exits non-zero and prints no URL

### Requirement: Failures are reported in the owner's terms
An object command that does not complete MUST exit non-zero and say what did not happen. A write refused because the bucket is at its size or object limit MUST be reported as the bucket being full, not as a bare access-denied error. A request refused because the local clock is too far from the object store's MUST say so.

#### Scenario: Bucket full
- **WHEN** an upload is refused because the bucket has reached its size limit
- **THEN** the command exits non-zero, saying the bucket is full

#### Scenario: Clock skew
- **WHEN** the object store refuses a request because the local clock is skewed
- **THEN** the command says the machine's clock is wrong rather than reporting an authentication failure

### Requirement: Results go to stdout and progress to stderr
Listings, object contents and URLs MUST go to stdout. Progress and warnings MUST go to stderr, following the client's stream discipline. Transfer progress MUST be shown only when stderr is a terminal. `--quiet` MUST silence progress and success messages, but MUST NOT silence errors or the report of a skipped key or a source left behind, because those explain a non-zero exit.

#### Scenario: Piped output is clean
- **WHEN** `freepod bucket cat` or `freepod bucket ls` runs with stdout piped
- **THEN** stdout carries only the result

#### Scenario: Quiet
- **WHEN** a copy that skips one key runs with `--quiet`
- **THEN** no progress or success message is printed
- **AND** the skipped key is still reported
