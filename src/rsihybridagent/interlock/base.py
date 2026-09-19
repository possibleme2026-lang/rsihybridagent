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

"""The interlock layer: four channels that let digital and physical experience feed each other.

"Hybrid" here is not "an agent that also has a robot". Two loops running side by side
are merely co-located. The claim of this framework is that the loops are *coupled*:
progress on one side is a first-class input to the other, in both directions, across
both evolvable surfaces.

Four channels, each a separate direction and surface pairing:

===========================  ==================  ==================
Channel                      Direction           Target surface
===========================  ==================  ==================
``SKILL_TRANSFER``           digital → physical  harness
``FAILURE_BACKPROP``         physical → digital  harness
``TRAJECTORY_DISTILLATION``  physical → digital  weights
``PRIMITIVE_DECOMPOSITION``  digital → physical  weights
===========================  ==================  ==================

Why four and not one: a single channel makes the system a pipeline, and a pipeline
cannot recover from a regression on the side that only receives. Each channel
carries its own evidence obligation, because a claim that travels between substrates
is exactly where an unverified gain is most likely to be believed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from rsihybridagent.core import ArtifactRef, ScenarioId, SubstrateKind, SurfaceKind
from rsihybridagent.ledger.base import Evidence


class Channel(StrEnum):
    """One directional coupling between the two substrates."""

    SKILL_TRANSFER = "skill_transfer"
    FAILURE_BACKPROP = "failure_backprop"
    TRAJECTORY_DISTILLATION = "trajectory_distillation"
    PRIMITIVE_DECOMPOSITION = "primitive_decomposition"

    @property
    def source(self) -> SubstrateKind:
        """The substrate this channel carries experience out of."""
        return _CHANNEL_SPEC[self].source

    @property
    def target(self) -> SubstrateKind:
        """The substrate this channel carries experience into."""
        return _CHANNEL_SPEC[self].target

    @property
    def surface(self) -> SurfaceKind:
        """The evolvable surface this channel updates."""
        return _CHANNEL_SPEC[self].surface


@dataclass(frozen=True)
class ChannelSpec:
    """Static description of one channel's direction and target surface."""

    source: SubstrateKind
    target: SubstrateKind
    surface: SurfaceKind


_CHANNEL_SPEC: Mapping[Channel, ChannelSpec] = {
    Channel.SKILL_TRANSFER: ChannelSpec(
        source=SubstrateKind.DIGITAL,
        target=SubstrateKind.PHYSICAL,
        surface=SurfaceKind.HARNESS,
    ),
    Channel.FAILURE_BACKPROP: ChannelSpec(
        source=SubstrateKind.PHYSICAL,
        target=SubstrateKind.DIGITAL,
        surface=SurfaceKind.HARNESS,
    ),
    Channel.TRAJECTORY_DISTILLATION: ChannelSpec(
        source=SubstrateKind.PHYSICAL,
        target=SubstrateKind.DIGITAL,
        surface=SurfaceKind.WEIGHTS,
    ),
    Channel.PRIMITIVE_DECOMPOSITION: ChannelSpec(
        source=SubstrateKind.DIGITAL,
        target=SubstrateKind.PHYSICAL,
        surface=SurfaceKind.WEIGHTS,
    ),
}


@dataclass(frozen=True)
class Crossing:
    """One proposed movement of experience across substrates.

    ``payload`` is channel-specific: a distilled skill for ``SKILL_TRANSFER``, a
    failure pattern for ``FAILURE_BACKPROP``, an exported trajectory set for
    ``TRAJECTORY_DISTILLATION``, a primitive decomposition for
    ``PRIMITIVE_DECOMPOSITION``.

    ``evidence`` is required. A crossing without evidence is a guess, and a guess
    that reaches the other substrate cannot be distinguished from a gain after the
    fact, which is precisely the failure this framework exists to avoid.
    """

    channel: Channel
    scenario: ScenarioId
    source_artifact: ArtifactRef
    payload: Mapping[str, Any]
    evidence: Evidence = field(kw_only=True)


class InterlockError(Exception):
    """A crossing violates its channel's contract."""


class InterlockPort(ABC):
    """Produces or consumes crossings for one channel.

    A port is deliberately narrow: it either reads experience out of a substrate or
    writes a change into one. A port that did both would blur which side owns the
    verification, and the ledger could no longer attribute a regression.
    """

    @abstractmethod
    def channel(self) -> Channel:
        """The channel this port serves."""

    @abstractmethod
    def health(self, *, scenario: ScenarioId) -> Mapping[str, Any]:
        """Report readiness of the substrate this port touches, for one scenario.

        Scoped per scenario because readiness is: a port whose substrate has loaded a
        model for one scenario has not thereby loaded it for another.
        """


class CrossingProducer(InterlockPort):
    """Reads experience out of the source substrate and proposes a crossing."""

    @abstractmethod
    def produce(self, *, scenario: ScenarioId) -> tuple[Crossing, ...]:
        """Propose zero or more crossings from the source substrate's records.

        Returning nothing is a valid outcome and must not be reported as a failure:
        a substrate that has not yet produced transferable experience is simply not
        ready, which is different from having tried and failed.
        """


class CrossingConsumer(InterlockPort):
    """Applies a verified crossing to the target substrate's surface."""

    @abstractmethod
    def consume(self, crossing: Crossing, *, scenario: ScenarioId) -> ArtifactRef:
        """Materialize a candidate artifact from a crossing, without publishing it.

        Publishing is the loop's decision, not the port's. The returned reference is
        a candidate: it still has to pass the ledger before it becomes live.
        """


def validate_crossing(crossing: Crossing) -> None:
    """Check a crossing against its channel's declared direction and surface.

    This runs at the boundary that owns the operation, so an internal caller can
    rely on the contract instead of re-checking it.
    """
    spec = _CHANNEL_SPEC[crossing.channel]
    if crossing.source_artifact.substrate is not spec.source:
        raise InterlockError(
            f"{crossing.channel.value} carries {spec.source.value} experience, "
            f"but the source artifact belongs to {crossing.source_artifact.substrate.value}"
        )
    if crossing.source_artifact.surface is not spec.surface:
        raise InterlockError(
            f"{crossing.channel.value} updates the {spec.surface.value} surface, "
            f"but the source artifact belongs to {crossing.source_artifact.surface.value}"
        )
    if not crossing.payload:
        raise InterlockError(f"{crossing.channel.value} crossing carries no payload")
    if crossing.evidence.scenario != crossing.scenario:
        raise InterlockError(
            f"crossing scenario {crossing.scenario.name!r} does not match "
            f"its evidence scenario {crossing.evidence.scenario.name!r}"
        )
