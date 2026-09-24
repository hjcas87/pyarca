# 4. Voucher authorization is never retried blindly

- Status: accepted
- Date: 2026-09-24

## Context

`FECAESolicitar` asks ARCA to authorize a voucher and returns its CAE. Vouchers are numbered per
point of sale and voucher type, and ARCA only accepts number N when it is exactly the last
authorized number plus one. Each authorized number is final.

That rule makes the voucher number an idempotency key: sending the same request with the same N
twice can never authorize two vouchers, because the second one is rejected with error 10016. The
real danger is renumbering. When the call times out or the connection drops after the request was
sent, the caller cannot know whether N was authorized. Asking for the last number again and
issuing with N+1 produces two authorized vouchers for one sale if the first call did succeed: a
fiscal error that has to be undone with a credit note.

Error 10016 means the voucher does not match the next one ARCA expects: either the number is not
the last authorized plus one, or the date is outside the allowed window or earlier than the last
authorized voucher's date. Two processes issuing for the same point of sale at the same time
trigger it, and so does an ambiguous call that did succeed.

## Decision

- **No automatic retry after the request may have been sent.** The transport retries only when
  the connection could not be established, including a connect timeout. Read timeouts, dropped
  connections after sending and 5xx responses are never retried.
- **An ambiguous authorization is resolved by asking, not by renumbering.** The client queries
  `FECompConsultar` for the same point of sale, type and number N:
  - N exists and matches the request (voucher date, receiver document, total): that is the
    authorization, and it is returned.
  - N exists with different data: another issuer took the number. This is a typed conflict error.
  - N does not exist: the voucher was not authorized. This is reported as such; sending again with
    the same N is safe, and pyarca never moves to N+1 on its own.
- **Deciding the outcome is a pure core function** that takes the original request and the
  consultation response; the shell only performs the calls.
- **Error 10016 becomes a typed error** carrying ARCA's message and the last authorized number from
  `FECompUltimoAutorizado`. pyarca does not renumber and resend on its own, because the caller may
  already have stored or printed the number.

## Alternatives considered

- **Retry with backoff on timeouts and 5xx**, the default in many HTTP clients. Rejected: after
  ARCA answers 10016 to the retry, the natural next step is to renumber, which is how duplicate
  vouchers happen.
- **Return the timeout to the caller and let them decide.** Rejected: every caller would have to
  know and implement the consultation step, and the ones who do not would renumber.
- **Treat any voucher found at number N as ours.** Rejected: with concurrent issuers, it would
  return another sale's CAE as this sale's authorization.
- **Renumber automatically on error 10016.** Rejected: the number is part of the caller's record,
  and changing it silently breaks that record.

## Consequences

- A sale gets at most one authorized voucher, whatever the network does, as long as the caller
  does not renumber after an ambiguous failure.
- After an ambiguous failure, the caller gets a definite answer at the cost of one extra request.
- Callers that issue concurrently from several processes still handle 10016 themselves, with the
  number they need to do it.
- Other non-idempotent calls, such as the WSAA login, get their own rules with the code that makes
  them.
