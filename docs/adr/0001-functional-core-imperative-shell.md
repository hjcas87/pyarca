# 1. Functional core, imperative shell

- Status: accepted
- Date: 2026-09-24

## Context

pyarca has to work from Django, FastAPI, Celery tasks and plain scripts, so it cannot depend on
any framework's models, settings or event loop.

Its hardest logic is building ARCA's SOAP requests, parsing the responses, mapping errors and
deciding how to recover from a failed call. When that logic is mixed with HTTP calls, the clock
and token storage, it can only be tested by patching the network and freezing time, and the tests
end up checking the patches instead of the rules.

## Decision

Split the package into a pure core and a thin shell.

- **Core**: builds request bytes from typed values and parses response bytes into typed values.
  It performs no I/O and imports no HTTP library.
- **The core is deterministic**: the same input always produces the same bytes. The current time
  and any unique identifier (such as the login ticket id) are arguments, never read or generated
  inside the core. Only the module implementing the system clock may read the time; ruff's
  banned-API rule rejects clock and randomness calls everywhere else.
- **Shell**: a `Client` that owns the I/O: sending bytes over HTTP, loading the certificate and
  key, storing access tokens, reading the time. It calls the core and holds no rules of its own.
- What the shell needs from the outside world is a `typing.Protocol` port (`Transport`, `Clock`,
  `TokenStore`, `Signer`), so callers and tests can substitute their own implementation.
- The layer direction (shell imports core, never the reverse) is enforced by an import-linter
  contract in the verification command once both layers exist.

## Alternatives considered

- **One client class that builds, sends and parses.** Rejected: every rule would need the network
  and the clock faked to be tested.
- **Classic hexagonal architecture with adapter classes per use case.** Rejected: more types than
  the problem has; a core of pure functions gives the same testability with less structure.
- **Freeze the clock in tests** (`freezegun`, `time-machine`) instead of passing the time in.
  Rejected: it hides the dependency instead of removing it, and callers could not build a request
  for a time of their choosing.

## Consequences

- Every rule in the core is tested with plain values and recorded XML fixtures, with no mocks,
  clock freezing or random seeds.
- The shell stays small enough that its tests only check wiring and I/O policies.
- A synchronous and an asynchronous client, another HTTP library or a different token store are
  each a new shell or port implementation, not a change to the core.
- Callers who want full control can call the core directly and do the I/O themselves.
