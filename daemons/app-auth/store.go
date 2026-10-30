package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

// codeTTL is how long a sign-in code may take to travel from the broker to the
// app host and be redeemed. It is one redirect; a minute is generous.
const codeTTL = 60 * time.Second

// disclosedClaims is exactly what the consent page lists and the verifier
// forwards. A consent recorded for fewer claims than this does not count.
var disclosedClaims = []string{"sub", "email", "name"}

type codeRecord struct {
	Host       string
	Subject    string
	Email      string
	Name       string
	ReturnPath string
	NonceHash  []byte
}

// oidcCode is an authorization code the provider issued, bound to the client
// and the redirect URI it was issued for (D5).
type oidcCode struct {
	DeploymentID  string
	RedirectURI   string
	Subject       string
	Email         string
	Name          string
	Nonce         string
	CodeChallenge string
	AuthTime      time.Time
}

// headerApp is a deployment whose serving release enables header
// authentication, as eligible finds it.
type headerApp struct {
	ID string
	// Listed is `auth.access: listed`, or any access the platform does not
	// recognize (D2).
	Listed bool
}

// accessEntry is one person on a deployment's access list. Subject is empty
// until someone signs in with the entry (D3).
type accessEntry struct {
	ID      string
	Email   string
	Subject string
}

// accessList is everything admit needs: the owner, then the list.
type accessList struct {
	OwnerEmail string
	Entries    []accessEntry
}

type store interface {
	// eligible returns the deployment whose hostname is exactly host and whose
	// applied release has header authentication enabled, or ok=false.
	eligible(ctx context.Context, host string) (app headerApp, ok bool, err error)
	// accessList returns a deployment's owner email and access list entries.
	accessList(ctx context.Context, deploymentID string) (accessList, error)
	// bindEntry ties an unbound entry to subject, and reports whether this
	// call did.
	bindEntry(ctx context.Context, entryID, subject, name string) (bool, error)
	hasConsent(ctx context.Context, subject, deploymentID string, claims []string) (bool, error)
	recordConsent(ctx context.Context, subject, deploymentID string, claims []string) error
	insertCode(ctx context.Context, codeHash []byte, c codeRecord) error
	// redeemCode deletes the code whatever happens next and reports whether it
	// existed and had not yet expired.
	redeemCode(ctx context.Context, codeHash []byte) (c codeRecord, fresh bool, found bool, err error)
	// ssoClient returns the deployment with this ID when it is an OIDC client
	// (D2), or ok=false.
	ssoClient(ctx context.Context, deploymentID string) (c ssoClient, ok bool, err error)
	insertOIDCCode(ctx context.Context, codeHash []byte, c oidcCode) error
	// redeemOIDCCode deletes the code whatever happens next, as redeemCode does.
	redeemOIDCCode(ctx context.Context, codeHash []byte) (c oidcCode, fresh bool, found bool, err error)
	// purgeExpiredCodes removes expired codes of both kinds.
	purgeExpiredCodes(ctx context.Context) (int64, error)
}

// pgStore hardwires its queries against the platform schema, as ssh-auth does;
// the role in tf/app/caelus/app-auth-bootstrap.sql grants exactly the columns
// named here and nothing else.
type pgStore struct {
	pool *pgxpool.Pool
}

func openPool(ctx context.Context, dsn string, maxConns int32) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, fmt.Errorf("database url: %w", err)
	}
	cfg.MaxConns = maxConns
	cfg.ConnConfig.RuntimeParams["application_name"] = "app-auth"
	cfg.ConnConfig.RuntimeParams["statement_timeout"] = "3000"
	return pgxpool.NewWithConfig(ctx, cfg)
}

// The timestamp columns are naive UTC, as everywhere in the platform schema,
// so every time is computed in SQL rather than sent from here.
const nowUTC = `(now() AT TIME ZONE 'utc')`

// effective reads one `auth` key as the reconciler merges it for Helm: the
// release's user value over the template's system value, which is only a
// default, over the contract's default (D2). That is what the applied release
// rendered, so it is what the edge enforces, for any product. A template that
// must not be overridden leaves the key out of its user schema.
func effective(key, fallback string) string {
	return `coalesce(r.values_json::jsonb #>> '{auth,` + key + `}',
	                 t.system_values_json::jsonb #>> '{auth,` + key + `}', '` + fallback + `')`
}

var (
	authEnabled  = `(` + effective("enabled", "false") + `)::boolean`
	authProtocol = effective("protocol", "header")
	authAccess   = effective("access", "anyone")
)

func (s *pgStore) eligible(ctx context.Context, host string) (headerApp, bool, error) {
	var app headerApp
	var access string
	err := s.pool.QueryRow(ctx, `
		SELECT d.id::text, `+authAccess+`
		  FROM deployment d
		  JOIN deployment_release r        ON r.id = d.applied_release_id
		  JOIN product_template_version t  ON t.id = r.template_id
		 WHERE lower(d.hostname) = lower($1)
		   AND d.status <> 'deleted'
		   AND `+authEnabled+`
		   AND `+authProtocol+` = 'header'
		 LIMIT 1`, host).Scan(&app.ID, &access)
	if errors.Is(err, pgx.ErrNoRows) {
		return headerApp{}, false, nil
	}
	if err != nil {
		return headerApp{}, false, err
	}
	app.Listed = access != "anyone"
	return app, true, nil
}

func (s *pgStore) accessList(ctx context.Context, deploymentID string) (accessList, error) {
	var l accessList
	if err := s.pool.QueryRow(ctx, `
		SELECT u.email FROM deployment d JOIN "user" u ON u.id = d.user_id WHERE d.id = $1::uuid`,
		deploymentID).Scan(&l.OwnerEmail); err != nil {
		return accessList{}, err
	}
	rows, err := s.pool.Query(ctx, `
		SELECT id::text, email, coalesce(subject, '') FROM app_access_entry WHERE deployment_id = $1::uuid`,
		deploymentID)
	if err != nil {
		return accessList{}, err
	}
	l.Entries, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (accessEntry, error) {
		var e accessEntry
		return e, row.Scan(&e.ID, &e.Email, &e.Subject)
	})
	return l, err
}

func (s *pgStore) bindEntry(ctx context.Context, entryID, subject, name string) (bool, error) {
	tag, err := s.pool.Exec(ctx, `
		UPDATE app_access_entry SET subject = $2, name = $3, bound_at = `+nowUTC+`
		 WHERE id = $1::uuid AND subject IS NULL`, entryID, subject, nullable(name))
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == "23505" {
		// Another entry of the deployment holds this subject already.
		return false, nil
	}
	return err == nil && tag.RowsAffected() == 1, err
}

func (s *pgStore) hasConsent(ctx context.Context, subject, deploymentID string, claims []string) (bool, error) {
	var ok bool
	err := s.pool.QueryRow(ctx, `
		SELECT EXISTS (
		  SELECT 1 FROM app_auth_consent
		   WHERE subject = $1 AND deployment_id = $2::uuid AND claims @> $3::text[])`,
		subject, deploymentID, claims).Scan(&ok)
	return ok, err
}

// recordConsent replaces rather than upserts: the role has no UPDATE, on
// purpose, and a delete and insert in one transaction is the same thing.
func (s *pgStore) recordConsent(ctx context.Context, subject, deploymentID string, claims []string) error {
	return pgx.BeginFunc(ctx, s.pool, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx,
			`DELETE FROM app_auth_consent WHERE subject = $1 AND deployment_id = $2::uuid`,
			subject, deploymentID); err != nil {
			return err
		}
		_, err := tx.Exec(ctx, `
			INSERT INTO app_auth_consent (subject, deployment_id, claims, granted_at)
			VALUES ($1, $2::uuid, $3::text[], `+nowUTC+`)`,
			subject, deploymentID, claims)
		return err
	})
}

func (s *pgStore) insertCode(ctx context.Context, codeHash []byte, c codeRecord) error {
	_, err := s.pool.Exec(ctx, `
		INSERT INTO app_auth_code
		  (code_hash, host, subject, email, name, return_path, nonce_hash, expires_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, `+nowUTC+` + make_interval(secs => $8))`,
		codeHash, c.Host, c.Subject, c.Email, c.Name, c.ReturnPath, c.NonceHash, codeTTL.Seconds())
	return err
}

func (s *pgStore) redeemCode(ctx context.Context, codeHash []byte) (codeRecord, bool, bool, error) {
	var c codeRecord
	var fresh bool
	err := s.pool.QueryRow(ctx, `
		DELETE FROM app_auth_code WHERE code_hash = $1
		RETURNING host, subject, email, name, return_path, nonce_hash, expires_at > `+nowUTC,
		codeHash).Scan(&c.Host, &c.Subject, &c.Email, &c.Name, &c.ReturnPath, &c.NonceHash, &fresh)
	if errors.Is(err, pgx.ErrNoRows) {
		return codeRecord{}, false, false, nil
	}
	if err != nil {
		return codeRecord{}, false, false, err
	}
	return c, fresh, true, nil
}

func (s *pgStore) purgeExpiredCodes(ctx context.Context) (int64, error) {
	var n int64
	for _, table := range []string{"app_auth_code", "app_auth_oidc_code"} {
		tag, err := s.pool.Exec(ctx, `DELETE FROM `+table+` WHERE expires_at < `+nowUTC)
		if err != nil {
			return n, err
		}
		n += tag.RowsAffected()
	}
	return n, nil
}

// ssoClient reads the switch as eligible does, but keyed by deployment ID, for
// `auth.protocol: oidc`, and only from a template that declares its callback
// paths. Everything under `auth.oidc` is read from system values alone (D1).
func (s *pgStore) ssoClient(ctx context.Context, deploymentID string) (ssoClient, bool, error) {
	if !clientIDPattern.MatchString(deploymentID) {
		return ssoClient{}, false, nil
	}
	var hostname, access string
	var paths, natives []byte
	var pkce bool
	err := s.pool.QueryRow(ctx, `
		SELECT d.hostname,
		       t.system_values_json::jsonb #> '{auth,oidc,redirectPaths}',
		       t.system_values_json::jsonb #> '{auth,oidc,nativeRedirectUris}',
		       coalesce(t.system_values_json::jsonb #>> '{auth,oidc,pkce}', '') <> 'false',
		       `+authAccess+`
		  FROM deployment d
		  JOIN deployment_release r        ON r.id = d.applied_release_id
		  JOIN product_template_version t  ON t.id = r.template_id
		 WHERE d.id = $1::uuid
		   AND d.status <> 'deleted'
		   AND d.hostname IS NOT NULL
		   AND `+authEnabled+`
		   AND `+authProtocol+` = 'oidc'`, deploymentID).Scan(&hostname, &paths, &natives, &pkce, &access)
	if errors.Is(err, pgx.ErrNoRows) {
		return ssoClient{}, false, nil
	}
	if err != nil {
		return ssoClient{}, false, err
	}
	c, ok := newSSOClient(deploymentID, hostname, json.RawMessage(paths), json.RawMessage(natives), pkce)
	c.Listed = access != "anyone"
	return c, ok, nil
}

func nullable(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func (s *pgStore) insertOIDCCode(ctx context.Context, codeHash []byte, c oidcCode) error {
	_, err := s.pool.Exec(ctx, `
		INSERT INTO app_auth_oidc_code
		  (code_hash, deployment_id, redirect_uri, subject, email, name, nonce, code_challenge, auth_time, expires_at)
		VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, `+nowUTC+` + make_interval(secs => $10))`,
		codeHash, c.DeploymentID, c.RedirectURI, c.Subject, c.Email, c.Name,
		nullable(c.Nonce), nullable(c.CodeChallenge), c.AuthTime.UTC(), codeTTL.Seconds())
	return err
}

func (s *pgStore) redeemOIDCCode(ctx context.Context, codeHash []byte) (oidcCode, bool, bool, error) {
	var c oidcCode
	var nonce, challenge *string
	var fresh bool
	err := s.pool.QueryRow(ctx, `
		DELETE FROM app_auth_oidc_code WHERE code_hash = $1
		RETURNING deployment_id::text, redirect_uri, subject, email, name, nonce, code_challenge, auth_time,
		          expires_at > `+nowUTC,
		codeHash).Scan(&c.DeploymentID, &c.RedirectURI, &c.Subject, &c.Email, &c.Name, &nonce, &challenge, &c.AuthTime, &fresh)
	if errors.Is(err, pgx.ErrNoRows) {
		return oidcCode{}, false, false, nil
	}
	if err != nil {
		return oidcCode{}, false, false, err
	}
	if nonce != nil {
		c.Nonce = *nonce
	}
	if challenge != nil {
		c.CodeChallenge = *challenge
	}
	return c, fresh, true, nil
}
