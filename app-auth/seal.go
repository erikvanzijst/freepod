package main

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
)

// A keyring seals small JSON values into cookie-safe strings with AES-256-GCM.
//
// Every value is sealed for a purpose ("session", "flow", "consent"), which is
// both mixed into the key and passed as additional data, so a value sealed for
// one purpose never opens as another -- a broker flow cookie cannot be replayed
// as an app session. The first key seals; every key opens, which is what lets a
// key be rotated without logging everyone out at once.
type keyring struct {
	keys []sealKey
}

type sealKey struct {
	id     string
	secret []byte
}

var errUnsealable = errors.New("unsealable")

// parseKeyring reads `id:base64key[,id:base64key...]`, current key first.
func parseKeyring(spec string) (*keyring, error) {
	kr := &keyring{}
	seen := map[string]bool{}
	for _, part := range strings.Split(spec, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		id, b64, ok := strings.Cut(part, ":")
		if !ok || id == "" || strings.Contains(id, ".") {
			return nil, fmt.Errorf("key %q: want id:base64", part)
		}
		secret, err := base64.StdEncoding.DecodeString(b64)
		if err != nil {
			return nil, fmt.Errorf("key %q: %w", id, err)
		}
		if len(secret) < 32 {
			return nil, fmt.Errorf("key %q: need at least 32 bytes, got %d", id, len(secret))
		}
		if seen[id] {
			return nil, fmt.Errorf("key %q appears twice", id)
		}
		seen[id] = true
		kr.keys = append(kr.keys, sealKey{id: id, secret: secret})
	}
	if len(kr.keys) == 0 {
		return nil, errors.New("no keys")
	}
	return kr, nil
}

func (k sealKey) aead(purpose string) cipher.AEAD {
	mac := hmac.New(sha256.New, k.secret)
	mac.Write([]byte("app-auth/" + purpose))
	block, err := aes.NewCipher(mac.Sum(nil))
	if err != nil {
		panic(err) // a 32-byte key always makes a cipher
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		panic(err)
	}
	return gcm
}

// sealed values carry their own expiry, so a cookie's Max-Age is a courtesy to
// the browser rather than the thing that enforces it.
type envelope struct {
	Exp  int64           `json:"exp"`
	Body json.RawMessage `json:"b"`
}

func (kr *keyring) seal(purpose string, v any, ttl time.Duration, now time.Time) (string, error) {
	body, err := json.Marshal(v)
	if err != nil {
		return "", err
	}
	plain, err := json.Marshal(envelope{Exp: now.Add(ttl).Unix(), Body: body})
	if err != nil {
		return "", err
	}
	key := kr.keys[0]
	gcm := key.aead(purpose)
	nonce := make([]byte, gcm.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return "", err
	}
	sealed := gcm.Seal(nonce, nonce, plain, []byte(purpose))
	return key.id + "." + base64.RawURLEncoding.EncodeToString(sealed), nil
}

// open fails the same way for every reason -- unknown key, tampering, wrong
// purpose, expiry -- because none of them is something the caller can act on
// differently.
func (kr *keyring) open(purpose, token string, v any, now time.Time) error {
	id, b64, ok := strings.Cut(token, ".")
	if !ok {
		return errUnsealable
	}
	raw, err := base64.RawURLEncoding.DecodeString(b64)
	if err != nil {
		return errUnsealable
	}
	for _, key := range kr.keys {
		if key.id != id {
			continue
		}
		gcm := key.aead(purpose)
		if len(raw) < gcm.NonceSize() {
			return errUnsealable
		}
		plain, err := gcm.Open(nil, raw[:gcm.NonceSize()], raw[gcm.NonceSize():], []byte(purpose))
		if err != nil {
			return errUnsealable
		}
		var env envelope
		if err := json.Unmarshal(plain, &env); err != nil {
			return errUnsealable
		}
		if now.Unix() >= env.Exp {
			return errUnsealable
		}
		if err := json.Unmarshal(env.Body, v); err != nil {
			return errUnsealable
		}
		return nil
	}
	return errUnsealable
}
