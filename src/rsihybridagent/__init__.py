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

"""rsihybridagent: recursive self-improvement for hybrid agents.

Digital and physical experience improving each other, with an evidence ledger that
refuses to call unverified progress progress.

The package layout follows the five architectural layers:

- :mod:`rsihybridagent.core` — shared value types, identities, and the two base
  abstractions (``Substrate``, ``Surface``) every layer speaks.
- :mod:`rsihybridagent.artifact` — artifact bodies, and the repository that resolves
  a reference into one.
- :mod:`rsihybridagent.ledger` — the evidence ledger and admission policies.
- :mod:`rsihybridagent.interlock` — the four channels between the two substrates.
- :mod:`rsihybridagent.registry` — how a third-party implementation is discovered.
- :mod:`rsihybridagent.substrate` — execution base implementations.
- :mod:`rsihybridagent.surfaces` — evolvable artifact family implementations.
- :mod:`rsihybridagent.recipes` — recipe and verifier implementations.
- :mod:`rsihybridagent.loop` — the recursive loop and its collaborator contracts.

Importing this package must stay cheap and must not require a GPU stack: the
physical substrate is an extra, and its dependencies load only at their use sites.
"""

from rsihybridagent.artifact import Artifact, ArtifactError, ArtifactNotFound, ArtifactRepository
from rsihybridagent.core import (
    ArtifactRef,
    ContentId,
    Feedback,
    LayerStatus,
    Receipt,
    ReleaseId,
    RuntimeLoadId,
    ScenarioId,
    Substrate,
    SubstrateKind,
    Surface,
    SurfaceKind,
    Verdict,
)
from rsihybridagent.registry import ExtensionPoint, RegistryError, available, load, register, unregister

__version__ = "0.0.1"

__all__ = [
    "Artifact",
    "ArtifactError",
    "ArtifactNotFound",
    "ArtifactRef",
    "ArtifactRepository",
    "ContentId",
    "ExtensionPoint",
    "Feedback",
    "LayerStatus",
    "Receipt",
    "RegistryError",
    "ReleaseId",
    "RuntimeLoadId",
    "ScenarioId",
    "Substrate",
    "SubstrateKind",
    "Surface",
    "SurfaceKind",
    "Verdict",
    "__version__",
    "available",
    "load",
    "register",
    "unregister",
]
