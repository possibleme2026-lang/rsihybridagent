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

"""Artifact storage: the other half of the reference/body split.

:class:`~rsihybridagent.core.ArtifactRef` is a *pointer*. It says which artifact is
meant without carrying it. A surface that only ever saw references could not stage a
candidate, because staging is the act of putting bytes somewhere — and the loop could
not verify one, for the same reason.

This module supplies the missing half: a repository that turns a reference into a
body, and stores a body as a new reference.

**Why this is a separate abstraction rather than methods on ``Surface``.** Storage
and version history are different concerns with different implementations. A harness
surface keeps a file tree and wants content-addressed storage; a weight surface keeps
a checkpoint and wants a blob store with a release chain. Sharing one ``Surface`` base
for both would force one of them to carry the other's storage assumptions, which is
exactly the boundary discipline the architecture document asks for. The surface asks
the repository for bytes; it does not know how they are kept.

**Why materialization returns a new object rather than a path.** A path would leak the
storage layout into every caller, and a caller that joined its own path segments would
break the moment the layout changed. ``Artifact`` is the read interface: content, plus
the identities, plus the parent link.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from rsihybridagent.core import ArtifactRef, ContentId, ReleaseId, ScenarioId


class ArtifactError(Exception):
    """An artifact is missing, already exists, or cannot be materialized."""


class ArtifactNotFound(ArtifactError):
    """No artifact is stored under the requested reference."""


@dataclass(frozen=True)
class Artifact:
    """A concrete artifact: its bytes, its identities, and where it came from.

    ``files`` holds text content keyed by relative path, which covers the harness and
    memory surfaces (a prompt, a rule set, a memory tree). A weights surface stores an
    opaque payload instead and leaves ``files`` empty; the two are not unified because
    a checkpoint has no meaningful per-file interface and pretending otherwise would
    force every weight reader through a mapping it does not want.

    ``payload`` is the binary body, present for surfaces that have one. Exactly one of
    the two is populated for a well-formed artifact; an artifact with neither is a
    reference to nothing and is refused at construction.
    """

    ref: ArtifactRef
    files: Mapping[str, str] = field(default_factory=dict)
    payload: bytes | None = None

    def __post_init__(self) -> None:
        if not self.files and self.payload is None:
            raise ArtifactError(
                f"artifact {self.ref.release_id.value!r} carries neither files nor a payload; "
                "an artifact with no body cannot be staged or verified"
            )
        if self.files and self.payload is not None:
            raise ArtifactError(
                f"artifact {self.ref.release_id.value!r} carries both files and a payload; "
                "a surface stores one or the other, and a mixed artifact has no defined reader"
            )

    @property
    def content_id(self) -> ContentId:
        """The fingerprint of this artifact's body."""
        return self.ref.content_id

    @property
    def release_id(self) -> ReleaseId:
        """The release this body was published or staged under."""
        return self.ref.release_id

    def text(self, path: str) -> str:
        """Read one file, failing loudly rather than returning a default."""
        try:
            return self.files[path]
        except KeyError as exc:
            raise ArtifactError(
                f"artifact {self.ref.release_id.value!r} has no file {path!r}; "
                f"it holds {sorted(self.files)}"
            ) from exc


class ArtifactRepository(ABC):
    """Stores artifact bodies and resolves references back to them.

    The repository owns the three-identity discipline. ``store`` mints a release;
    ``materialize`` reads one back. A repository that returned the same release for
    identical content would erase the distinction between *published twice* and
    *published once*, so ``store`` takes the parent explicitly rather than inferring it.
    """

    @abstractmethod
    def store(
        self,
        *,
        scenario: ScenarioId,
        surface: ArtifactRef,
        files: Mapping[str, str] | None = None,
        payload: bytes | None = None,
    ) -> ArtifactRef:
        """Persist a body and return its reference.

        ``surface`` supplies the identity fields (which surface, which substrate) and
        the ``parent`` link; its own content and release identities are ignored and
        replaced by ones derived from the body actually stored. Passing the previous
        reference here is how a release chain is built.
        """

    @abstractmethod
    def materialize(self, ref: ArtifactRef, *, scenario: ScenarioId) -> Artifact:
        """Read a body back, raising :class:`ArtifactNotFound` when it is absent."""

    @abstractmethod
    def exists(self, ref: ArtifactRef, *, scenario: ScenarioId) -> bool:
        """Whether a body is stored for this reference."""

    @abstractmethod
    def metadata(self, ref: ArtifactRef, *, scenario: ScenarioId) -> Mapping[str, Any]:
        """Non-content facts about a stored artifact, for the ledger and for operators."""
