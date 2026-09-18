# Contributing to rsihybridagent

Thanks for considering a contribution. This document states how to work in this
repository and what a change is expected to carry.

## Project status

The project is at design stage. The architecture and the core abstractions are the
current deliverable; there is no end-to-end reference implementation yet. Changes
that complete a specified abstraction are more useful right now than changes that
add new abstractions.

## Development environment

Requires Python 3.12 or newer. The base install is CPU-only and must stay that way:
a GPU dependency belongs in an extra, and a physical-stack import belongs at its use
site so that importing the package never requires a simulator.

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
```

> **Windows note.** The full service depends on POSIX process-group semantics
> (`os.killpg`, `os.setsid`) and on `fcntl`, so it does not run on native Windows.
> The core abstractions and the test suite do run there. Use WSL2 or a Linux
> container for anything that starts a service.

## Running the checks

```bash
pytest -q
ruff check .
mypy
```

All three must pass before a change is ready. A change that weakens a test to make
it pass is not acceptable; fix the behavior or explain in the pull request why the
test's expectation was wrong.

## What a change should carry

**State the failure it prevents.** This project exists because a self-improving
system's dominant failure mode is believing it learned. A change that touches the
ledger, the policy, or the loop should say which misreport it makes impossible.

**Keep the three states distinct.** `NOT_RUN`, `SKIPPED`, and `FAILED` must stay
distinguishable at every point a decision is made. Using an enum is not sufficient:
if any aggregate boolean such as `all_layers_passed` feeds a branch, the three states
collapse back into two at that branch. When you add or review such a branch, check
that it does not need to tell an unrun layer from a failed one.

**Do not let a change verify itself.** The party that produces a candidate must not
also decide whether it worked. Keep `Recipe`, `Verifier`, and `AdmissionPolicy`
separate, and keep the ledger's attribution pointing at a layer that actually ran.

**Validate at the boundary that owns the operation.** Internal control flow should
rely on established contracts rather than re-checking them. Keep `try`/`except`
narrow and catch specific, expected failures.

**Prefer explicit interfaces over dynamic behavior.** No `getattr` probing for
capabilities, no callable-valued fields modeling long-lived behavior. Define an
`ABC` and inherit it.

## Style

- 119-column lines, Black and isort compatible; `ruff` and `mypy --strict` are the
  authorities.
- Type annotations on new or changed interfaces. No `Any` to silence a checker.
- Docstrings explain intent and constraints, not the mechanics a reader can see.
  Prose describes current behavior; history belongs in the changelog or the pull
  request.
- Name the actual quantity: `baseline_pass_rate`, not `threshold`; `timeout_seconds`,
  not `timeout`.
- Comments are welcome where a constraint is non-obvious. Avoid comments that restate
  the line below them.

## Tests

Add tests for observable behavior and for the failure modes the change addresses.
The existing suite in `tests/test_ledger.py` is organized by the misreport each test
guards against; follow that structure rather than grouping by class under test.

A test that only restates an implementation detail is not useful. A test that pins
one of the three states being distinguishable is.

## Attribution and licensing

This project is Apache-2.0. By contributing you agree your contribution is licensed
under the same terms.

If your change reuses code from another project, say so in the pull request, keep the
original copyright notice, and add the source to `NOTICE`. Architectural inspiration
does not require this, but direct code reuse does. The projects this work builds on
are listed in the README's References section.

## Pull requests

Include in the description:

- the problem, and what behavior changes
- which misreport the change prevents, when it touches verification
- what you actually ran, and what remains unverified
- any compatibility impact

Report what ran and what did not honestly. An untested claim is worse than a stated
gap: the whole point of the ledger is that unverified work is not counted as done,
and the same standard applies to the project's own changes.
