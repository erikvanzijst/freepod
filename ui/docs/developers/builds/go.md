---
sidebar_position: 3
title: Go
---

# Go

A project with `go.mod` in its root is built as Go. Railpack takes the Go version from `go.mod`, builds a static binary and starts it; see [Railpack: Go](https://railpack.com/languages/golang) for which package it builds in multi-package layouts. For layouts Railpack does not handle, use a [`Dockerfile`](index.md#dockerfile).

## Example

```go title="main.go"
package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
)

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintln(w, "Hello from Freepod")
	})
	log.Fatal(http.ListenAndServe("0.0.0.0:"+port, nil))
}
```

```text title="go.mod"
module example.com/hello

go 1.25
```
