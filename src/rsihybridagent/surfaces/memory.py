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

"""An in-memory artifact repository, and the reference release-chain discipline.

Durable storage belongs to a deployment. This implementation exists for three
reasons, in order of importance:

1. It makes the loop runnable end to end, so the interfaces can be exercised rather
   than merely declared.
2. It pins down what the three artifact identities mean in practice, which is the
   part of the design most likely to be misread.
3. It gives the append-only and release-chain contracts a reference implementation
   that is obviously correct.

**The identity discipline, concretely.** Storing identical content twice produces
two different ``release_id`` values sharing one ``content_id``. That is not an
implementation quirk; it is the point. "The same prompt was proposed again in a later
turn" and "the prompt was proposed once" are different histories, and a repository
that deduplicated them would make the ledger unable to tell them apart.
"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from rsihybridagent.artifact import Artifact, ArtifactError, ArtifactNotFound, ArtifactRepository
from rsihybridagent.core import (
    ArtifactRef,
    ContentId,
    ReleaseId,
    RuntimeLoadId,
    ScenarioId,
    SubstrateKind,
    Surface,
    SurfaceKind,
)


@dataclass(frozen=True)
class _Stored:
    """One stored body, with the metadata a reader may ask for."""

    files: Mapping[str, str]
    payload: bytes | None
    parent: ReleaseId | None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class MemoryArtifactRepository(ArtifactRepository):
    """Content-addressed artifact storage held in process memory.

    Bodies are stored per scenario, so isolation is a property of the storage shape
    rather than a check every caller has to remember to perform.
    """

    def __init__(self) -> None:
        self._bodies: dict[str, dict[ReleaseId, _Stored]] = {}
        self._counter = itertools.count(1)

    def store(
        self,
        *,
        scenario: ScenarioId,
        surface: ArtifactRef,
        files: Mapping[str, str] | None = None,
        payload: bytes | None = None,
    ) -> ArtifactRef:
        """Persist a body under a fresh release, linked to ``surface.parent``.

        The release number is monotonic within a scenario and independent of content,
        which is what keeps two identical bodies distinguishable.
        """
        if files is None and payload is None:
            raise ArtifactError(
                "store() needs either files or payload; a release with no body could be "
                "neither staged nor verified, and would make the ledger record a fiction"
            )
        if files is not None and payload is not None:
            raise ArtifactError("store() takes files or payload, not both")

        content = ContentId.of(_fingerprint(files, payload))
        release = ReleaseId(f"{surface.surface.value}-r{next(self._counter):06d}")
        stored = _Stored(
            files=dict(files) if files else {},
            payload=payload,
            parent=surface.parent,
            metadata=dict(surface.metadata),
        )
        self._bodies.setdefault(scenario.name, {})[release] = stored

        return ArtifactRef(
            surface=surface.surface,
            substrate=surface.substrate,
            content_id=content,
            release_id=release,
            parent=surface.parent,
            metadata=dict(surface.metadata),
        )

    def materialize(self, ref: ArtifactRef, *, scenario: ScenarioId) -> Artifact:
        """Read a body back, refusing a reference this scenario never stored."""
        stored = self._lookup(ref, scenario=scenario)
        return Artifact(ref=ref, files=stored.files, payload=stored.payload)

    def exists(self, ref: ArtifactRef, *, scenario: ScenarioId) -> bool:
        """Whether a body is stored for this reference in this scenario."""
        return ref.release_id in self._bodies.get(scenario.name, {})

    def metadata(self, ref: ArtifactRef, *, scenario: ScenarioId) -> Mapping[str, Any]:
        """Non-content facts, plus the parent link that makes the chain walkable."""
        stored = self._lookup(ref, scenario=scenario)
        return {**stored.metadata, "parent": stored.parent.value if stored.parent else None}

    def _lookup(self, ref: ArtifactRef, *, scenario: ScenarioId) -> _Stored:
        """Find a stored body, naming the scenario in the failure.

        Cross-scenario reads are the mistake most worth reporting clearly: a reference
        from another scenario looks valid, and the failure would otherwise appear as a
        missing artifact rather than as a broken isolation boundary.
        """
        bucket = self._bodies.get(scenario.name, {})
        if ref.release_id not in bucket:
            elsewhere = [name for name, bodies in self._bodies.items() if ref.release_id in bodies]
            if elsewhere:
                raise ArtifactError(
                    f"release {ref.release_id.value!r} belongs to scenario {elsewhere[0]!r}, "
                    f"not {scenario.name!r}; scenarios never share a release chain"
                )
            raise ArtifactNotFound(
                f"no artifact stored for release {ref.release_id.value!r} in scenario {scenario.name!r}"
            )
        return bucket[ref.release_id]


def _fingerprint(files: Mapping[str, str] | None, payload: bytes | None) -> bytes:
    """Derive a stable content fingerprint from either body shape.

    File paths are included in the hash and sorted first, so renaming a file changes
    the fingerprint while reordering the mapping does not. Hashing only the values
    would make two different file trees collide.
    """
    if payload is not None:
        return payload
    assert files is not None
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[path].encode("utf-8"))
        digest.update(b"\0")
    return digest.digest()


class MemorySurface(Surface):
    """A surface over an in-memory repository, usable for any artifact family.

    This is deliberately *not* one ABC implementation per family. A harness surface and
    a memory surface differ in what their bodies mean, not in how a release chain
    works, so one implementation serves both and the difference lives in the recipes
    that write the bodies.

    It inherits :class:`~rsihybridagent.core.Surface` rather than merely matching its
    shape. A duck-typed implementation satisfies the runtime checks and is invisible to
    a type checker, which is how it was first written: the example failed ``mypy`` while
    passing every test, because nothing had ever asked the type system to confirm the
    contract. Inheriting makes the base class a real constraint instead of a convention.
    """

    def __init__(self, kind: SurfaceKind, repository: MemoryArtifactRepository) -> None:
        self._kind = kind
        self._repository = repository
        self._current: dict[str, ArtifactRef] = {}
        self._loaded: dict[str, list[ReleaseId]] = {}

    def kind(self) -> SurfaceKind:
        """Which artifact family this surface serves."""
        return self._kind

    def repository(self) -> MemoryArtifactRepository:
        """Where this surface's bodies live."""
        return self._repository

    def current(self, *, scenario: ScenarioId) -> ArtifactRef | None:
        """The released artifact, or ``None`` before the first commit."""
        return self._current.get(scenario.name)

    def stage(
        self,
        *,
        scenario: ScenarioId,
        files: Mapping[str, str] | None = None,
        payload: bytes | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRef:
        """Store a candidate body, linked to the current release as its parent."""
        head = self._current.get(scenario.name)
        seed = ArtifactRef(
            surface=self._kind,
            substrate=head.substrate if head else _default_substrate(self._kind),
            content_id=ContentId(""),
            release_id=ReleaseId(""),
            parent=head.release_id if head else None,
            metadata=dict(metadata or {}),
        )
        return self._repository.store(scenario=scenario, surface=seed, files=files, payload=payload)

    def publish(self, candidate: ArtifactRef, *, scenario: ScenarioId) -> ArtifactRef:
        """Advance the release chain, refusing a candidate this scenario never staged."""
        if not self._repository.exists(candidate, scenario=scenario):
            raise ArtifactError(
                f"cannot publish release {candidate.release_id.value!r}: it was never staged "
                f"in scenario {scenario.name!r}. Publishing is only valid for a stored candidate."
            )
        self._current[scenario.name] = candidate
        return candidate

    def rollback(self, *, scenario: ScenarioId) -> ArtifactRef | None:
        """Return to the parent release, or clear the head at the root."""
        head = self._current.get(scenario.name)
        if head is None or head.parent is None:
            self._current.pop(scenario.name, None)
            return None
        parent = ArtifactRef(
            surface=head.surface,
            substrate=head.substrate,
            content_id=head.content_id,
            release_id=head.parent,
        )
        self._current[scenario.name] = parent
        return parent

    def deliver(self, artifact: ArtifactRef, *, scenario: ScenarioId) -> RuntimeLoadId:
        """Mark a release live and mint a load identity distinct from the release.

        A new identity is minted on every delivery, including a re-delivery of the same
        release. Re-loading a release into a service produces a new runtime instance,
        and reporting the old identity would hide that the service was restarted.
        """
        self._loaded.setdefault(scenario.name, []).append(artifact.release_id)
        count = len(self._loaded[scenario.name])
        return RuntimeLoadId(f"{artifact.release_id.value}+load{count}")


def _default_substrate(kind: SurfaceKind) -> SubstrateKind:
    """Pick the substrate a surface defaults to when it has no predecessor.

    A weights surface is updated by training runs, which are digital. A harness or
    memory surface is written by whichever side produced the change, so it also starts
    digital and the interlock layer moves it. The value only has to be a sensible
    starting point; the caller overrides it whenever the change originated physically.
    """
    del kind
    return SubstrateKind.DIGITAL
