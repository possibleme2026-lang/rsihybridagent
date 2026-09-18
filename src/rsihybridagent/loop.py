# Copyright 2026 The rsihybridagent Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The recursive loop: serve, observe, grow, commit.

The loop is the same shape on both substrates and for all three surfaces. What
changes between a weight update and a memory edit is the recipe, not the loop.

Two properties the loop must preserve:

- **Nothing serves before it is published.** A candidate is staged beside the live
  artifact, never in front of it. A rejected candidate leaves the live artifact
  untouched, which is what makes a regression survivable.
- **Nothing publishes without evidence.** ``commit`` consults the ledger's admission
  policy. A candidate whose evidence is incomplete is ``INCONCLUSIVE``, not accepted
  and not rejected: it must be re-run, and the ledger records that it was not decided.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from rsihybridagent.core import (
    ArtifactRef,
    Feedback,
    Receipt,
    ScenarioId,
    Substrate,
    Surface,
    Verdict,
)
from rsihybridagent.ledger.base import AdmissionPolicy, Evidence, Ledger, LedgerEntry


class Phase(StrEnum):
    """Where a scenario is in one turn of the loop."""

    IDLE = "idle"
    SERVING = "serving"
    OBSERVING = "observing"
    GROWING = "growing"
    COMMITTING = "committing"


@dataclass(frozen=True)
class TurnRecord:
    """What one turn of the loop did, for the ledger and for operators."""

    scenario: ScenarioId
    phase_reached: Phase
    receipts: tuple[Receipt, ...] = ()
    candidate: ArtifactRef | None = None
    verdict: Verdict | None = None
    reason: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)


class Recipe(ABC):
    """Turns recorded interactions plus feedback into an evolution candidate.

    A recipe is where method-specific policy lives: which records are eligible, how
    a batch is cut, what objective is trained, or how a harness is edited. The loop
    never inspects this; it only asks for a candidate.

    ``propose`` may return ``None``. Insufficient or ineligible data is an ordinary
    outcome, not an error, and must be distinguishable from a failed attempt.
    """

    @property
    @abstractmethod
    def surface(self) -> Surface:
        """The surface this recipe produces candidates for."""

    @abstractmethod
    def eligible(self, receipts: tuple[Receipt, ...], feedback: Feedback, *, scenario: ScenarioId) -> bool:
        """Whether the observed signal is enough to attempt an update."""

    @abstractmethod
    def propose(self, *, scenario: ScenarioId) -> ArtifactRef | None:
        """Stage and return a candidate, or ``None`` when there is nothing to propose."""


class Verifier(ABC):
    """Produces the evidence for one candidate.

    The verifier is separate from both the recipe and the admission policy because
    the party that produces a change must not also decide whether it worked. Keeping
    them apart is what makes the ledger's attribution meaningful.
    """

    @abstractmethod
    def declared_layers(self) -> tuple[str, ...]:
        """The layers this verifier will run, named before any run starts.

        Declaring layers up front is what lets the ledger detect a layer that never
        ran. A verifier that only reports the layers it happened to execute cannot
        distinguish an omitted check from a passed one.
        """

    @abstractmethod
    def verify(self, candidate: ArtifactRef, *, scenario: ScenarioId) -> Evidence:
        """Run the declared layers and return the evidence, complete or not."""


class RecursiveLoop:
    """Drives one scenario through repeated turns of serve, observe, grow, commit.

    The loop holds no method knowledge and no substrate knowledge. It sequences the
    four steps, enforces the two ordering invariants, and delegates every decision
    that needs domain judgment to a collaborator.
    """

    def __init__(
        self,
        *,
        substrate: Substrate,
        recipe: Recipe,
        verifier: Verifier,
        policy: AdmissionPolicy,
        ledger: Ledger,
    ) -> None:
        self._substrate = substrate
        self._recipe = recipe
        self._verifier = verifier
        self._policy = policy
        self._ledger = ledger

    def serve(self, request: Mapping[str, Any], *, scenario: ScenarioId) -> tuple[Receipt, Mapping[str, Any]]:
        """Step 1. Run one interaction and return its receipt and result."""
        return self._substrate.execute(request, scenario=scenario)

    def observe(self, feedback: Feedback, *, scenario: ScenarioId) -> bool:
        """Step 2. Report whether the feedback is enough to attempt an update.

        Feedback whose receipts do not belong to this scenario is refused rather
        than applied: accepting it would let one scenario's outcome move another's
        artifact, breaking isolation in a way that is very hard to notice later.
        """
        for receipt in feedback.receipts:
            if receipt.scenario != scenario:
                raise ValueError(
                    f"feedback receipt belongs to scenario {receipt.scenario.name!r}, not {scenario.name!r}"
                )
        return self._recipe.eligible(feedback.receipts, feedback, scenario=scenario)

    def grow(self, *, scenario: ScenarioId) -> ArtifactRef | None:
        """Step 3. Produce a staged candidate, or ``None`` when there is nothing to do."""
        return self._recipe.propose(scenario=scenario)

    def commit(self, candidate: ArtifactRef | None, *, scenario: ScenarioId) -> LedgerEntry | None:
        """Step 4. Verify the candidate, decide on it, and publish only if accepted.

        Returns ``None`` when there was no candidate. Otherwise the returned entry is
        appended to the ledger whatever the verdict, so a rejection is as auditable
        as an acceptance.
        """
        if candidate is None:
            return None
        evidence = self._verifier.verify(candidate, scenario=scenario)
        verdict, reason = self._policy.decide(evidence)
        entry = LedgerEntry(
            entry_id=f"{scenario.name}:{candidate.release_id.value}",
            evidence=evidence,
            verdict=verdict,
            reason=reason,
        )
        self._ledger.append(entry)
        if verdict is Verdict.ACCEPTED:
            published = self._recipe.surface.publish(candidate, scenario=scenario)
            self._recipe.surface.deliver(published, scenario=scenario)
        return entry
