# NeuroBiz

Agent layer that reads pharma procurement emails, extracts NDC, lot and expiry with evidence,
validates them, and drafts replies for a human to approve.

## Run

```sh
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Health check: `GET http://127.0.0.1:8000/health` returns `{"status": "ok"}`.

## Test

```sh
uv run pytest
```

## Installs

Dependency installs (`uv lock`, `uv sync`, `pre-commit install`, adding packages) are done by humans
only. Agents must not install or add dependencies; see CLAUDE.md.
