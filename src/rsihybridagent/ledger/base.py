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

"""The evidence ledger: every evolution carries a checkable record and an attribution.

This module is the project's core claim. A self-improving system's dominant failure
mode is not failing to learn; it is *believing it learned*. Three concrete shapes:

1. A layer that never ran is counted as having passed (vacuous pass).
2. A layer that failed is recorded as skipped, hiding the failure.
3. A measured gain comes from noise, not capability, and is accepted as progress.

The ledger closes all three by making a layer's absence explicit, by refusing to
fold ``SKIPPED`` into ``FAILED``, and by requiring the verdict to name the layer it
attributes the outcome to. An attribution the evidence does not support is itself a
failure, not a lesser success.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from rsihybridagent.core import ArtifactRef, LayerStatus, ScenarioId, Verdict


class LedgerError(Exception):
    """A record is missing, malformed, or claims more than its evidence supports."""


@dataclass(frozen=True)
class LayerResult:
    """Outcome of one verification layer on one candidate.

    ``status`` must be set explicitly by the layer that ran. A layer with no
    result is not the same as a layer that passed, which is why nothing here
    defaults to ``PASSED``.
    """

    layer: str
    status: LayerStatus
    detail: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status is LayerStatus.SKIPPED and not self.detail.get("reason"):
            raise LedgerError(f"layer {self.layer!r} skipped without a reason; a skip must say why")

    @property
    def ran(self) -> bool:
        """Whether this layer actually executed."""
        return self.status is not LayerStatus.NOT_RUN

    @property
    def passed(self) -> bool:
        """Whether this layer executed and passed. A skip is never a pass."""
        return self.status is LayerStatus.PASSED


@dataclass(frozen=True)
class CaseOutcome:
    """One verified instance: which case, and how each layer scored it."""

    case_id: str
    seed: int
    layers: tuple[LayerResult, ...]

    @property
    def all_layers_ran(self) -> bool:
        """Whether every declared layer executed for this case."""
        return all(result.ran for result in self.layers)

    @property
    def all_layers_passed(self) -> bool:
        """Whether every layer executed and passed."""
        return all(result.passed for result in self.layers)

    def failing_layers(self) -> tuple[str, ...]:
        """Layers that executed and failed. Skips and unrun layers are excluded by design."""
        return tuple(r.layer for r in self.layers if r.status is LayerStatus.FAILED)

    def not_run_layers(self) -> tuple[str, ...]:
        """Layers declared for this case that never executed.

        This is the per-case counterpart of :meth:`Evidence.not_run_layers`. It exists
        so a caller can tell "the layer did not run" apart from "the layer ran and
        failed" without re-deriving it from statuses at each call site.
        """
        return tuple(r.layer for r in self.layers if r.status is LayerStatus.NOT_RUN)


@dataclass(frozen=True)
class Evidence:
    """The checkable record attached to one evolution candidate.

    ``attribution`` names the layer the verdict blames or credits. It must be a
    layer that actually ran; blaming a layer that never executed is the exact
    error this structure exists to prevent.
    """

    scenario: ScenarioId
    candidate: ArtifactRef
    baseline: ArtifactRef | None
    cases: tuple[CaseOutcome, ...]
    declared_layers: tuple[str, ...]
    attribution: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.declared_layers:
            raise LedgerError("evidence must declare the layers it intends to verify")
        if self.attribution is not None and self.attribution not in self.declared_layers:
            raise LedgerError(
                f"attribution {self.attribution!r} is not among the declared layers {self.declared_layers}"
            )

    def missing_layers(self) -> tuple[str, ...]:
        """Declared layers that produced no result on at least one case.

        A non-empty return means the run was incomplete. It can never be accepted.
        """
        missing: list[str] = []
        for layer in self.declared_layers:
            for case in self.cases:
                if not any(r.layer == layer for r in case.layers):
                    missing.append(layer)
                    break
        return tuple(missing)

    def not_run_layers(self) -> tuple[str, ...]:
        """Declared layers reported as ``NOT_RUN`` on at least one case.

        Distinct from :meth:`missing_layers`, which covers a layer with no result at
        all. A verifier that explicitly reports ``NOT_RUN`` is being honest, and the
        two cases must be reported separately so the operator knows which happened.
        """
        unrun: list[str] = []
        for layer in self.declared_layers:
            if any(r.layer == layer and r.status is LayerStatus.NOT_RUN for case in self.cases for r in case.layers):
                unrun.append(layer)
        return tuple(unrun)

    def skipped_layers(self) -> tuple[str, ...]:
        """Declared layers that reported a skip, kept separate from failures."""
        skipped: list[str] = []
        for layer in self.declared_layers:
            if any(r.layer == layer and r.status is LayerStatus.SKIPPED for case in self.cases for r in case.layers):
                skipped.append(layer)
        return tuple(skipped)

    def pass_rate(self) -> float:
        """Fraction of cases where every declared layer ran and passed."""
        if not self.cases:
            return 0.0
        return sum(1 for case in self.cases if case.all_layers_passed) / len(self.cases)


@dataclass(frozen=True)
class LedgerEntry:
    """One accepted or rejected evolution, with the evidence that decided it."""

    entry_id: str
    evidence: Evidence
    verdict: Verdict
    reason: str


class Ledger(ABC):
    """Append-only store of evolution records.

    The ledger is append-only because a self-improving system must be able to
    explain any past decision. Rewriting a verdict would erase the only account of
    why an artifact is live.
    """

    @abstractmethod
    def append(self, entry: LedgerEntry) -> None:
        """Record one decision. Implementations must not overwrite prior entries."""

    @abstractmethod
    def entries(self, *, scenario: ScenarioId) -> Sequence[LedgerEntry]:
        """Every decision recorded for a scenario, oldest first."""

    @abstractmethod
    def accepted_chain(self, *, scenario: ScenarioId) -> Sequence[ArtifactRef]:
        """The artifacts accepted for a scenario, in commit order."""


class AdmissionPolicy(ABC):
    """Decides whether an evolution candidate is accepted.

    The policy owns the verdict; the ledger owns the record. Keeping them apart
    lets a deployment change its bar without changing how evidence is stored.
    """

    @abstractmethod
    def decide(self, evidence: Evidence) -> tuple[Verdict, str]:
        """Return the verdict and the human-readable reason for it."""
