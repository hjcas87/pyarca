# Architecture decision records

Each file records one structural decision: its context, the decision, the alternatives and the
consequences.

- Files are numbered in order and never renumbered.
- The body of an accepted ADR is frozen. Reversing a decision takes a new ADR that supersedes it;
  the old one keeps its text and only its status line changes.
- Status is one of `accepted`, `amended` or `superseded`.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-functional-core-imperative-shell.md) | Functional core, imperative shell | accepted |
| [0002](0002-decimal-amounts-without-silent-rounding.md) | Decimal amounts without silent rounding | accepted |
| [0003](0003-soap-without-zeep.md) | SOAP without zeep | accepted |
