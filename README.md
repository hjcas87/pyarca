# pyarca

Framework-agnostic Python client for ARCA (ex AFIP) electronic invoicing in Argentina.

**Status: pre-alpha.** The package exists but exposes no functionality yet. Nothing here is ready
for use.

## Scope

pyarca talks to ARCA's SOAP web services from any Python 3.12+ code (Django, FastAPI, scripts)
without depending on a web framework. Features are listed here as they ship.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pre-commit install
```

See [AGENTS.md](AGENTS.md) for the verification command and repository conventions.

## License

[MIT](LICENSE)
