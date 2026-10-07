// Package main implements the SSH auth resolver: sshpiper's gRPC plugin.
//
// sshpiperd asks one question per offered key -- may this key open the
// deployment this username names, and where is that deployment's sidecar --
// and this answers it from the platform's own rows. Nothing is projected into
// the cluster, so there is no second copy of the answer to fall out of step
// with the first.
package main

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Why a refusal happened. For the operator's log; the client is told only "no".
type cause string

const (
	causeAdmitted         cause = "admitted"
	causeMalformedKey     cause = "malformed_key"
	causeUnknownUsername  cause = "unknown_username"
	causeNotReachable     cause = "deployment_not_reachable"
	causeKeyNotRegistered cause = "key_not_registered"
)

// One query, and it distinguishes every refusal the log has to tell apart.
//
// The join to user_ssh_key is a LEFT JOIN on purpose. An inner join would
// answer "admit or not" in one row, but no rows would then mean either "no such
// deployment" or "that key is registered nowhere", and the spec requires an
// operator to be able to tell those apart even though the client cannot. With
// the outer join, no rows means the username names nothing and a row with
// key_registered = false means the deployment exists and the key does not.
//
// It joins deployment straight to user_ssh_key on user_id rather than through
// `user`. The extra hop returns the same rows and would put a third table --
// one holding email addresses -- into the grant of a service on the public SSH
// port.
//
// The username is the deployment's id: a primary key, so at most one row can
// match and the lookup needs no tie-break. `d.name` is still read, but only as
// the account to present upstream -- the two are deliberately different things.
//
// Reachability is an allowlist, and `error` is in it deliberately: access
// matters most when the application is broken, and the sidecar's Service
// publishes not-ready addresses for exactly that reason (var/ssh_access.md D17).
const resolveQuery = `
SELECT d.name,
       d.namespace,
       d.status,
       d.name || '-ssh.' || d.namespace || '.svc' AS host,
       (k.id IS NOT NULL) AS key_registered
  FROM deployment AS d
  LEFT JOIN user_ssh_key AS k
         ON k.user_id = d.user_id
        AND k.fingerprint = $2
 WHERE d.id = $1::uuid
   AND d.status <> 'deleted'`

var reachable = map[string]bool{"ready": true, "error": true}

type decision struct {
	cause       cause
	host        string
	port        int
	username    string
	fingerprint string
	status      string
}

func (d decision) admitted() bool { return d.cause == causeAdmitted }

func (d decision) uri() string {
	// sshpiperd parses this with url.Parse and dials scheme://host, so the
	// scheme is required rather than decorative.
	return fmt.Sprintf("tcp://%s:%d", d.host, d.port)
}

// fingerprint is `SHA256:<unpadded base64>`, byte-identical to `ssh-keygen -lf`
// and to what the API stores. sshpiperd hands us the SSH wire blob -- the
// base64 body of an authorized_keys line -- so this needs no key parsing.
func fingerprint(blob []byte) string {
	sum := sha256.Sum256(blob)
	return "SHA256:" + base64.RawStdEncoding.EncodeToString(sum[:])
}

// resolve never returns an error for a refusal. An error means the store could
// not be read, and the caller turns that into a refusal too -- an unavailable
// dependency is a closed door, not an open one.
func resolve(ctx context.Context, db *pgxpool.Pool, username string, blob []byte, sidecarPort int) (decision, error) {
	if len(blob) == 0 {
		return decision{cause: causeMalformedKey}, nil
	}
	fp := fingerprint(blob)

	// Parsed here rather than left to PostgreSQL: a username that is not a uuid
	// is an unknown username, not a failed query, and must cost neither a round
	// trip nor an error the operator has to read as a refusal.
	id, err := uuid.Parse(username)
	if err != nil {
		return decision{cause: causeUnknownUsername, fingerprint: fp}, nil
	}

	var name, namespace, status, host string
	var keyRegistered bool
	err = db.QueryRow(ctx, resolveQuery, id.String(), fp).
		Scan(&name, &namespace, &status, &host, &keyRegistered)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		return decision{cause: causeUnknownUsername, fingerprint: fp}, nil
	case err != nil:
		return decision{}, err
	}

	if !reachable[status] {
		return decision{cause: causeNotReachable, fingerprint: fp, status: status}, nil
	}
	if !keyRegistered {
		return decision{cause: causeKeyNotRegistered, fingerprint: fp, status: status}, nil
	}
	return decision{
		cause:       causeAdmitted,
		host:        host,
		port:        sidecarPort,
		username:    name,
		fingerprint: fp,
		status:      status,
	}, nil
}
