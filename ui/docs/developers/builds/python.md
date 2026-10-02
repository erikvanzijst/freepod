---
sidebar_position: 2
title: Python
---

# Python

A project with `requirements.txt`, `pyproject.toml` or `Pipfile` in its root is built as Python. Railpack picks the Python version, package manager and start command from the project's files; see [Railpack: Python](https://railpack.com/languages/python). Add a `.python-version` file to pin the version.

## Example

```python title="main.py"
from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def index():
    return {"hello": "freepod"}
```

```text title="requirements.txt"
fastapi
uvicorn
```

Railpack starts this example with `uvicorn main:app` on `$PORT`.

## Start command

If Railpack does not detect the start command, or detects the wrong one, set it in a `Procfile`. Bind to `0.0.0.0:$PORT`:

```procfile title="Procfile"
web: gunicorn --bind 0.0.0.0:$PORT app:app
```

## Migrations

Run migrations in the start command, before the server starts:

```procfile title="Procfile"
web: sh -c 'alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT'
```
