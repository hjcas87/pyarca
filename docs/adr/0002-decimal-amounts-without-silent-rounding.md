# 2. Decimal amounts without silent rounding

- Status: accepted
- Date: 2026-09-24

## Context

ARCA's WSDL declares invoice amounts as `double`, but its developer manual specifies them as 13
integer digits and 2 decimal places, and ARCA rejects a voucher whose totals do not match the sum
of their parts beyond a documented margin: a relative error of at most 0.01% or an absolute error
of at most 0.01. ARCA's own calculations round half to even.

Binary floating point cannot represent most of these values exactly: `0.1 + 0.2` is not `0.3`.
A float amount has already lost precision before any library sees it, and comparing tax amounts
as floats produces rejections that depend on the order of the operations.

Rounding is a business rule of the issuer (per line or per total, which mode), not something a
transport library can decide for them.

## Decision

- Every amount in the public API is a `Decimal`. A `float` passed as an amount is rejected with a
  typed error, not converted.
- pyarca never rounds an amount. An amount with more decimal places than ARCA accepts is rejected
  with a typed error.
- Checks that compare amounts (for example, a total against the sum of its parts) are done in
  `Decimal`, with ARCA's documented margin as named constants.
- Currency and exchange rate are fields of the invoice, because ARCA sets one currency per
  voucher. There is no per-amount money type.

## Alternatives considered

- **Accept `float` and convert with `Decimal(str(value))`.** Rejected: the precision is already
  lost, and accepting floats tells callers they are safe.
- **Round to two decimals when serializing.** Rejected: it silently changes the amount the caller
  computed, and a total that ARCA then rejects looks like pyarca's fault.
- **A `Money` type carrying amount and currency.** Rejected for now: with one currency per voucher,
  it would repeat the same currency on every amount.

## Consequences

- Callers pass `Decimal` amounts already rounded to ARCA's precision, and get an explicit error
  when they do not.
- Amount checks give the same result regardless of the order of the operations.
- If ARCA allows several currencies in one voucher, the money type is revisited in a new ADR.
