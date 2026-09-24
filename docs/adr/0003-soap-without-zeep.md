# 3. SOAP without zeep

- Status: accepted
- Date: 2026-09-24

## Context

ARCA's web services (WSAA, WSFEv1, the taxpayer registry) are SOAP services described by WSDL.
pyarca uses a handful of operations per service, each with a fixed request shape.

The usual Python SOAP library, zeep, reads the WSDL at runtime and builds request and response
objects dynamically from it. That has two costs here:

- The objects have no static types, so mypy cannot check how pyarca builds requests or reads
  responses, which is where most of its rules live.
- Every client has to load and parse the WSDL, from the network or from a bundled copy, before
  the first call, for a handful of operations whose shape is already known.

## Decision

- Each operation has an explicit request builder that produces the SOAP envelope with lxml, and
  an explicit parser that turns the response into frozen dataclasses.
- WSDLs are never fetched or read at runtime. Endpoint URLs are named constants per environment
  (homologation and production).
- Response XML is parsed with a hardened lxml parser: no network access, no entity resolution.
- Every builder and parser is tested against recorded XML from ARCA: the built request must match
  a recorded request, and each recorded response (success, observation, error) must parse into the
  expected values.

## Alternatives considered

- **zeep.** Rejected for the reasons in the context.
- **Classes generated from the WSDL** (xsdata). Rejected: thousands of generated lines for a few
  operations, which nobody reviews and which still need a mapping layer to typed domain values.
- **String templates for the envelope.** Rejected: values have to be escaped by hand, and a
  missing escape produces invalid XML that only fails at ARCA.

## Consequences

- Requests and responses are fully typed and deterministic; the core returns bytes and tests
  compare bytes.
- Supporting a new operation means writing its builder, parser and fixtures by hand.
- If ARCA changes a service contract, pyarca needs a release; nothing adapts automatically. ARCA
  changes WSFEv1 in place rather than publishing a new version (in 2025 it added
  `CondicionIVAReceptorId` to the existing request), so each revision of ARCA's developer manual
  has to be checked against the builders.
- lxml is a runtime dependency.
- If pyarca grows to cover many services, hand-written builders stop paying off, and zeep or
  generated code should be reconsidered in a new ADR.
