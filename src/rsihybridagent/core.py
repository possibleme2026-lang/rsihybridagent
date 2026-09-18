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

"""Shared value types: identity, provenance, and the wire contracts every layer speaks.

Three artifact identities are kept separate on purpose. Mixing them is the hardest
bug class in a self-improving system: the same content can be published twice, and
a published release can be loaded into more than one runtime instance.

- ``content_id`` is a fingerprint of the bytes. Identical content always shares one.
- ``release_id`` is one accepted commit. A later commit of identical content gets a new one.
- ``runtime_load_id`` is one loaded instance. A hot swap makes it differ from the release.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SubstrateKind(StrEnum):
    """Which execution substrate a record or artifact belongs to."""

    DIGITAL = "digital"
    PHYSICAL = "physical"


class SurfaceKind(StrEnum):
    """Which evolvable artifact family a change targets."""

    WEIGHTS = "weights"
    HARNESS = "harness"
    MEMORY = "memory"


class LayerStatus(StrEnum):
    """Outcome of one verification layer.

    ``NOT_RUN`` and ``FAILED`` are deliberately distinct. Collapsing them is how a
    self-improving system reports a vacuous pass, or hides a failure as a skip.
    A layer that did not run can never contribute to an accepted verdict.
    """

    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Verdict(StrEnum):
    """Decision on one evolution candidate."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class ContentId:
    """Fingerprint of an artifact's bytes."""

    value: str

    @classmethod
    def of(cls, payload: bytes) -> ContentId:
        """Derive the content identity from the artifact bytes."""
        return cls(hashlib.sha256(payload).hexdigest())


@dataclass(frozen=True)
class ReleaseId:
    """Identity of one accepted commit in a surface's release history."""

    value: str


@dataclass(frozen=True)
class RuntimeLoadId:
    """Identity of one artifact instance actually loaded by a running service."""

    value: str


@dataclass(frozen=True)
class ArtifactRef:
    """A reference to one versioned artifact, carrying all three identities.

    ``parent`` links the release history so a rollback has a target. A root
    artifact has ``parent=None``.
    """

    surface: SurfaceKind
    substrate: SubstrateKind
    content_id: ContentId
    release_id: ReleaseId
    parent: ReleaseId | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenarioId:
    """One isolated learning context: its own records, artifacts, and release chain.

    Scenario isolation is a preserved contract, not an optimization. Two scenarios
    never share a release chain, so one cannot silently inherit another's progress.
    """

    name: str


@dataclass(frozen=True)
class Receipt:
    """Opaque handle returned to a caller, used later to attach feedback.

    A receipt is the only link between an interaction and its feedback. Feedback
    that arrives without a valid receipt is unlinkable and must be rejected rather
    than guessed at.
    """

    value: str
    scenario: ScenarioId


@dataclass(frozen=True)
class Feedback:
    """Signal about a recorded interaction.

    ``score`` is the cheap scalar a recipe may train on; ``detail`` carries the
    richer structured or textual signal a recipe may read instead of, or beside,
    the score. Both may be absent for feedback that only marks an interaction.
    """

    receipts: tuple[Receipt, ...]
    score: float | None = None
    detail: Mapping[str, Any] | None = None


class Substrate(ABC):
    """An execution base that produces records and consumes delivered artifacts.

    A substrate owns the boundary with the outside world. It validates its own
    inputs at that boundary and reports failures in its own vocabulary, so the
    layers above never parse substrate-specific errors.

    Implementations must not require the agent process to import the physical
    stack. A physical substrate runs as a separate process and is reached over
    RPC, which is what lets the agent side stay on CPU.
    """

    @property
    @abstractmethod
    def kind(self) -> SubstrateKind:
        """Which substrate family this instance belongs to."""

    @abstractmethod
    def execute(self, request: Mapping[str, Any], *, scenario: ScenarioId) -> tuple[Receipt, Mapping[str, Any]]:
        """Run one interaction and return its receipt and result body.

        The receipt identifies this interaction for later feedback. The result
        body is substrate-specific and is not interpreted by this layer.
        """

    @abstractmethod
    def health(self) -> Mapping[str, Any]:
        """Report readiness. An unhealthy substrate must not accept work."""


class Surface(ABC):
    """A family of evolvable artifacts with a version history.

    A surface answers two questions only: what the current artifact is, and how a
    candidate replaces it. How a candidate is produced belongs to a recipe, and
    how it is verified belongs to the ledger.
    """

    @property
    @abstractmethod
    def kind(self) -> SurfaceKind:
        """Which artifact family this surface serves."""

    @abstractmethod
    def current(self, *, scenario: ScenarioId) -> ArtifactRef | None:
        """The artifact currently released for the scenario, or ``None`` before any commit."""

    @abstractmethod
    def stage(self, candidate: ArtifactRef, *, scenario: ScenarioId) -> ArtifactRef:
        """Place a candidate beside the current release without serving it yet."""

    @abstractmethod
    def publish(self, candidate: ArtifactRef, *, scenario: ScenarioId) -> ArtifactRef:
        """Advance the release chain to the candidate and return its published reference."""

    @abstractmethod
    def rollback(self, *, scenario: ScenarioId) -> ArtifactRef | None:
        """Return the release chain to the candidate's parent, or ``None`` at the root."""

    @abstractmethod
    def deliver(self, artifact: ArtifactRef, *, scenario: ScenarioId) -> RuntimeLoadId:
        """Make a published artifact live for consumers and report the loaded instance."""
