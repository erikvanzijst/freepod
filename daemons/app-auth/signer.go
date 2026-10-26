package main

import (
	"crypto"
	"crypto/rsa"
	"crypto/x509"
	"encoding/base64"
	"encoding/pem"
	"errors"
	"fmt"
	"time"

	jose "github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"
)

const (
	idTokenTTL     = 300 * time.Second
	accessTokenTTL = 10 * time.Minute
)

// signer holds the provider's ID token keys, current first (D6). The first
// signs; the JWKS publishes every key, so tokens signed just before a rotation
// still verify.
type signer struct {
	keys []signingKey
	jwks jose.JSONWebKeySet
}

type signingKey struct {
	kid  string
	priv *rsa.PrivateKey
}

// parseSigningKeys reads concatenated PEM RSA private keys, PKCS#1 or PKCS#8.
func parseSigningKeys(spec string) (*signer, error) {
	s := &signer{}
	rest := []byte(spec)
	seen := map[string]bool{}
	for {
		var block *pem.Block
		block, rest = pem.Decode(rest)
		if block == nil {
			break
		}
		var key any
		var err error
		switch block.Type {
		case "RSA PRIVATE KEY":
			key, err = x509.ParsePKCS1PrivateKey(block.Bytes)
		case "PRIVATE KEY":
			key, err = x509.ParsePKCS8PrivateKey(block.Bytes)
		default:
			return nil, fmt.Errorf("unexpected PEM block %q", block.Type)
		}
		if err != nil {
			return nil, err
		}
		priv, ok := key.(*rsa.PrivateKey)
		if !ok {
			return nil, errors.New("not an RSA key")
		}
		if priv.N.BitLen() < 2048 {
			return nil, fmt.Errorf("RSA key of %d bits; need at least 2048", priv.N.BitLen())
		}
		pub := jose.JSONWebKey{Key: &priv.PublicKey, Algorithm: string(jose.RS256), Use: "sig"}
		thumb, err := pub.Thumbprint(crypto.SHA256)
		if err != nil {
			return nil, err
		}
		pub.KeyID = base64.RawURLEncoding.EncodeToString(thumb)
		if seen[pub.KeyID] {
			return nil, errors.New("the same key appears twice")
		}
		seen[pub.KeyID] = true
		s.keys = append(s.keys, signingKey{kid: pub.KeyID, priv: priv})
		s.jwks.Keys = append(s.jwks.Keys, pub)
	}
	if len(s.keys) == 0 {
		return nil, errors.New("no PEM keys")
	}
	return s, nil
}

func (s *signer) sign(claims any) (string, error) {
	k := s.keys[0]
	sig, err := jose.NewSigner(jose.SigningKey{Algorithm: jose.RS256, Key: k.priv},
		(&jose.SignerOptions{}).WithType("JWT").WithHeader("kid", k.kid))
	if err != nil {
		return "", err
	}
	return jwt.Signed(sig).Claims(claims).Serialize()
}

type idTokenClaims struct {
	Issuer        string `json:"iss"`
	Audience      string `json:"aud"`
	AZP           string `json:"azp"`
	Subject       string `json:"sub"`
	Email         string `json:"email"`
	EmailVerified bool   `json:"email_verified"`
	Name          string `json:"name"`
	IssuedAt      int64  `json:"iat"`
	Expiry        int64  `json:"exp"`
	AuthTime      int64  `json:"auth_time"`
	Nonce         string `json:"nonce,omitempty"`
}

func (s *signer) idToken(issuer string, c oidcCode, now time.Time) (string, error) {
	return s.sign(idTokenClaims{
		Issuer: issuer, Audience: c.DeploymentID, AZP: c.DeploymentID,
		Subject: c.Subject, Email: c.Email, EmailVerified: true, Name: c.Name,
		IssuedAt: now.Unix(), Expiry: now.Add(idTokenTTL).Unix(), AuthTime: c.AuthTime.Unix(),
		Nonce: c.Nonce,
	})
}

// verifyHint checks that an id_token_hint is an ID token this provider signed
// for issuer, and returns its audience. Expiry is not checked: a hint names
// whose session is ending, and is routinely sent long after it expired (D9).
func (s *signer) verifyHint(issuer, raw string) (string, bool) {
	tok, err := jwt.ParseSigned(raw, []jose.SignatureAlgorithm{jose.RS256})
	if err != nil || len(tok.Headers) != 1 {
		return "", false
	}
	keys := s.jwks.Key(tok.Headers[0].KeyID)
	if len(keys) != 1 {
		return "", false
	}
	var c idTokenClaims
	if err := tok.Claims(keys[0].Key, &c); err != nil || c.Issuer != issuer || c.Audience == "" {
		return "", false
	}
	return c.Audience, true
}

// accessGrant is the access token's content, sealed under its own purpose so
// it opens nowhere but userinfo (D6).
type accessGrant struct {
	ClientID string `json:"cid"`
	Sub      string `json:"sub"`
	Email    string `json:"email"`
	Name     string `json:"name"`
}

const accessPurpose = "oidc-access"
