---
sidebar_position: 1
title: Node.js
---

# Node.js

A project with `package.json` in its root is built as Node.js. Railpack picks the Node.js version, package manager, build step and start command from the project's files; see [Railpack: Node](https://railpack.com/languages/node). Commit the lockfile, and set `engines.node` in `package.json` to pin the version.

## Example

```js title="server.js"
const http = require('node:http')

const port = process.env.PORT || 8080

http
  .createServer((req, res) => {
    res.end('Hello from Freepod\n')
  })
  .listen(port, '0.0.0.0')
```

```json title="package.json"
{
  "name": "hello",
  "engines": { "node": "24" },
  "scripts": { "start": "node server.js" }
}
```

## Listening on `$PORT`

`next start` reads `PORT` and listens on all interfaces. Express listens on all interfaces when `app.listen` gets no host argument. Fastify listens on `localhost` by default; pass the host explicitly:

```js
await app.listen({ port: Number(process.env.PORT), host: '0.0.0.0' })
```
