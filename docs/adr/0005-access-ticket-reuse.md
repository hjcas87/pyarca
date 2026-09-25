# 5. The access ticket is reused until ARCA says it expires

- Status: accepted
- Date: 2026-09-24

## Context

Every ARCA business service call carries an access ticket (TA): a token and a sign issued by WSAA.
To get one, the caller signs a login ticket request with its certificate and sends it to
`loginCms`. The WSAA specification sets the rules for that exchange:

- A ticket is valid for 12 hours from issue, and the response states its `expirationTime`. The
  developer manual says to use that field to know how long the ticket lasts.
- The caller must reuse a valid ticket instead of asking for another. WSAA rejects a new login
  for the same certificate and service during a short window after the previous one, with
  `coe.alreadyAuthenticated`. The manual documents that window as 10 minutes in homologation and
  2 minutes in production, and warns that ARCA changes it without notice.
- After any error other than `wsaa.*` or `wsn.unavailable`, the caller must not ask again until the
  cause is fixed. After those two, it must wait 60 seconds.

The login is also non-idempotent. When the connection drops after the request was sent, WSAA may
have issued a ticket the caller never received, and the next login inside the window is rejected.

## Decision

- **The expiration comes from ARCA.** The ticket's lifetime is the `expirationTime` in the
  response, never a duration computed by pyarca.
- **A ticket is reused while it is valid.** Before logging in, the client asks the `TokenStore` for
  a ticket for the same certificate and service, and uses it when it expires more than a safety
  margin after the current time. The margin is a named constant, so a ticket does not expire
  while a request is in flight.
- **The store is keyed by certificate and service**, the same scope WSAA uses to reject a login.
- **`TokenStore` has two operations: read a ticket and save a ticket.** pyarca ships an in-memory
  store. Sharing tickets between processes is the job of the caller's store (a database, a cache),
  and the port takes no lock.
- **`coe.alreadyAuthenticated` reads the store once more.** Another process may have saved the
  ticket in the meantime; if it is there and valid, it is used. Otherwise the client raises a typed
  error.
- **The login is never retried automatically.** Every WSAA fault becomes a typed error carrying
  its code, and a timeout after sending is reported as such. Deciding when to try again is the
  caller's.

## Alternatives considered

- **A fixed local lifetime**, as in code that caches the ticket for a set number of hours.
  Rejected: it either throws away valid tickets or keeps expired ones, and ARCA already states
  the real expiration.
- **A lock in the `TokenStore` port** so that only one process logs in at a time. Rejected for now:
  WSAA's rejection window is minutes, the re-read after `coe.alreadyAuthenticated` resolves the
  common race, and a lock would force every store to implement a distributed lock. Revisit if
  callers report repeated login failures under concurrency.
- **Retry the login after a timeout or fault.** Rejected: the retry lands inside WSAA's rejection
  window, and the specification asks callers not to repeat a login after most errors.

## Consequences

- One ticket serves a process for about 12 hours; logins happen twice a day per certificate and
  service in steady state.
- Callers running several processes must provide a shared `TokenStore`, or each process logs in
  on its own and some of them hit `coe.alreadyAuthenticated`.
- After a lost login response, the caller gets a typed error and can only try again after WSAA's
  window, which pyarca does not know in advance.
