# AGENTS.md

Project facts for anyone (human or agent) changing this repository.

## Verification

Run before every commit. CI runs the same steps, plus `uv sync --locked` and a check that the
wheel ships `py.typed`.

```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy && uv build
```

## Layout

| Path | Contents |
|---|---|
| `src/pyarca/` | The published package |
| `docs/adr/` | Architecture decision records |
| `.github/workflows/ci.yml` | CI, mirroring the verification command |

## Architecture

Functional core, imperative shell ([ADR 0001](docs/adr/0001-functional-core-imperative-shell.md)):

- The core builds request bytes and parses response bytes into typed values. It performs no I/O
  and reads no clock.
- The shell (the client) owns I/O: HTTP, signing keys, token storage, time.
- The core takes plain values. What the shell needs from outside (HTTP, clock, token storage,
  signing) arrives through `typing.Protocol` ports.

## Conventions

- Code, docs, commits and exception messages are in English.
- Messages meant for end users are in Spanish and live in a message catalog, never inline.
- ARCA codes and other closed sets are enums, never bare literals.
- Commits follow Conventional Commits; the `commit-msg` hook enforces it.
