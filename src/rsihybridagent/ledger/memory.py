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

"""An in-memory ledger, for tests and for a single-process run.

Durable storage belongs to a deployment, not to this package. This implementation
exists so the loop and the policy can be exercised without a database, and so the
append-only contract has a reference implementation that is obviously correct.
"""

from __future__ import annotations

from collections.abc import Sequence

from rsihybridagent.core import ArtifactRef, ScenarioId, Verdict
from rsihybridagent.ledger.base import Ledger, LedgerEntry, LedgerError


class MemoryLedger(Ledger):
    """Append-only ledger held in process memory.

    Entries are stored per scenario so that isolation is a property of the storage
    shape rather than a check a caller has to remember to perform.
    """

    def __init__(self) -> None:
        self._entries: dict[str, list[LedgerEntry]] = {}

    def append(self, entry: LedgerEntry) -> None:
        """Record one decision, refusing to replace an entry that already exists."""
        name = entry.evidence.scenario.name
        bucket = self._entries.setdefault(name, [])
        if any(existing.entry_id == entry.entry_id for existing in bucket):
            raise LedgerError(
                f"entry {entry.entry_id!r} is already recorded; the ledger is append-only "
                "and a decision cannot be rewritten"
            )
        bucket.append(entry)

    def entries(self, *, scenario: ScenarioId) -> Sequence[LedgerEntry]:
        """Every decision recorded for a scenario, oldest first."""
        return tuple(self._entries.get(scenario.name, ()))

    def accepted_chain(self, *, scenario: ScenarioId) -> Sequence[ArtifactRef]:
        """The artifacts accepted for a scenario, in commit order."""
        return tuple(
            entry.evidence.candidate
            for entry in self._entries.get(scenario.name, ())
            if entry.verdict is Verdict.ACCEPTED
        )
