package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
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

type store interface {
	// eligible returns the deployment whose hostname is exactly host and whose
	// applied release has authentication enabled, or ok=false.
	eligible(ctx context.Context, host string) (deploymentID string, ok bool, err error)
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

// Whether authentication is enabled is read as the reconciler merges it for
// Helm: the release's user value over the template's system value, which is
// only a default. That is what the applied release rendered, so it is what the
// edge enforces, for any product. A template that must not be overridden
// leaves the key out of its user schema.
func (s *pgStore) eligible(ctx context.Context, host string) (string, bool, error) {
	var id string
	err := s.pool.QueryRow(ctx, `
		SELECT d.id::text
		  FROM deployment d
		  JOIN deployment_release r        ON r.id = d.applied_release_id
		  JOIN product_template_version t  ON t.id = r.template_id
		 WHERE lower(d.hostname) = lower($1)
		   AND d.status <> 'deleted'
		   AND coalesce((r.values_json::jsonb #>> '{auth,enabled}')::boolean,
		                (t.system_values_json::jsonb #>> '{auth,enabled}')::boolean,
		                false)
		 LIMIT 1`, host).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	return id, true, nil
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

// ssoClient reads `sso.enabled` as eligible reads `auth.enabled`, but keyed by
// deployment ID, and only from a template that declares its callback paths.
// Unlike the switch, the paths and native URIs are never read from user values
// (D2, D4).
func (s *pgStore) ssoClient(ctx context.Context, deploymentID string) (ssoClient, bool, error) {
	if !clientIDPattern.MatchString(deploymentID) {
		return ssoClient{}, false, nil
	}
	var hostname string
	var paths, natives []byte
	var pkce bool
	err := s.pool.QueryRow(ctx, `
		SELECT d.hostname,
		       t.system_values_json::jsonb #> '{sso,redirectPaths}',
		       t.system_values_json::jsonb #> '{sso,nativeRedirectUris}',
		       coalesce(t.system_values_json::jsonb #>> '{sso,pkce}', '') <> 'false'
		  FROM deployment d
		  JOIN deployment_release r        ON r.id = d.applied_release_id
		  JOIN product_template_version t  ON t.id = r.template_id
		 WHERE d.id = $1::uuid
		   AND d.status <> 'deleted'
		   AND d.hostname IS NOT NULL
		   AND coalesce((r.values_json::jsonb #>> '{sso,enabled}')::boolean,
		                (t.system_values_json::jsonb #>> '{sso,enabled}')::boolean,
		                false)`, deploymentID).Scan(&hostname, &paths, &natives, &pkce)
	if errors.Is(err, pgx.ErrNoRows) {
		return ssoClient{}, false, nil
	}
	if err != nil {
		return ssoClient{}, false, err
	}
	c, ok := newSSOClient(deploymentID, hostname, json.RawMessage(paths), json.RawMessage(natives), pkce)
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
