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

"""Surface implementations: the evolvable artifact families.

A surface owns version history and delivery. It does not own how a candidate is
produced, and it does not own whether the candidate is any good.

Storage lives behind an :class:`~rsihybridagent.artifact.ArtifactRepository`, so the
implementations here differ in what their bodies mean rather than in how a release
chain works.
"""

from rsihybridagent.surfaces.memory import MemoryArtifactRepository, MemorySurface

__all__ = [
    "MemoryArtifactRepository",
    "MemorySurface",
]
