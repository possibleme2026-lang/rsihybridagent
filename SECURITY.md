# Security Policy

## Reporting a vulnerability

Report suspected vulnerabilities privately through GitHub's
[private vulnerability reporting](https://github.com/possibleme2026-lang/rsihybridagent/security/advisories/new)
rather than in a public issue.

Please include what the issue is, how to reproduce it, and what an attacker could
achieve. You will get an acknowledgement, and credit in the advisory unless you ask
otherwise.

## Scope

The project is at design stage: the core abstractions are in place and there is no
service deployment yet. Areas worth reporting now:

- **Ledger integrity.** Any way to rewrite, delete, or bypass an entry in a `Ledger`
  implementation, or to have a verdict recorded that its evidence does not support.
- **Attribution soundness.** Any way for a verdict to credit or blame a layer that
  did not run, or for a `NOT_RUN` or `SKIPPED` layer to contribute to an accepted
  verdict.
- **Scenario isolation.** Any way for one scenario's feedback, records, or artifacts
  to affect another scenario's release chain.
- **Boundary validation.** Any way to make a substrate or surface accept input it
  should reject, or to make a crossing violate its channel's declared direction.

## Design commitments that are not vulnerabilities

Two properties are intentional and should not be reported as bugs:

- **The ledger is append-only by design.** A deployment that needs to correct a
  mistaken verdict must record a new entry; overwriting is refused on purpose.
- **Unverified work is never accepted.** A candidate with an unrun, skipped, or
  unattributed layer is `INCONCLUSIVE`, not accepted. This is the project's central
  claim, and a report that it refuses to accept incomplete evidence is a report that
  it works.
