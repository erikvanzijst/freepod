package main

import (
	"context"
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

type store interface {
	// eligible returns the deployment serving host with authentication enabled
	// in its applied release, or ok=false.
	eligible(ctx context.Context, host string) (deploymentID string, ok bool, err error)
	hasConsent(ctx context.Context, subject, deploymentID string, claims []string) (bool, error)
	recordConsent(ctx context.Context, subject, deploymentID string, claims []string) error
	insertCode(ctx context.Context, codeHash []byte, c codeRecord) error
	// redeemCode deletes the code whatever happens next and reports whether it
	// existed and had not yet expired.
	redeemCode(ctx context.Context, codeHash []byte) (c codeRecord, fresh bool, found bool, err error)
	purgeExpiredCodes(ctx context.Context) (int64, error)
}

// pgStore hardwires its queries against the platform schema, as ssh-auth does;
// the role in tf/app/caelus/app-auth-bootstrap.sql grants exactly the columns
// named here and nothing else.
type pgStore struct {
	pool *pgxpool.Pool
	// productSlug is `custom` everywhere but in tests, which cannot own that
	// slug in a database the API suite shares.
	productSlug string
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

func (s *pgStore) eligible(ctx context.Context, host string) (string, bool, error) {
	var id string
	err := s.pool.QueryRow(ctx, `
		SELECT d.id::text
		  FROM deployment d
		  JOIN deployment_release r        ON r.id = d.applied_release_id
		  JOIN product_template_version t  ON t.id = r.template_id
		  JOIN product p                   ON p.id = t.product_id
		 WHERE lower(d.hostname) = lower($1)
		   AND d.status <> 'deleted'
		   AND p.slug = $2
		   AND coalesce((r.values_json::jsonb -> 'auth' ->> 'enabled')::boolean, false)
		 LIMIT 1`, host, s.productSlug).Scan(&id)
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
	tag, err := s.pool.Exec(ctx, `DELETE FROM app_auth_code WHERE expires_at < `+nowUTC)
	return tag.RowsAffected(), err
}
