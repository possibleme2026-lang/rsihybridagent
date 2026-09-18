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

"""Tests for the ledger's central invariant: unverified work is never accepted.

These tests exist because the first version of the admission policy had exactly the
bug this module guards against. A layer reported as ``NOT_RUN`` was folded into the
failed set, producing a rejection with an empty list of blamed layers. The verdict
was wrong in two ways at once: it rejected rather than deferring, and its reason
named no layer, so an operator could not act on it.

Every test below states one way the system could lie about its own progress.
"""

from __future__ import annotations

import pytest

from rsihybridagent.core import (
    ArtifactRef,
    ContentId,
    LayerStatus,
    ReleaseId,
    ScenarioId,
    SubstrateKind,
    SurfaceKind,
    Verdict,
)
from rsihybridagent.ledger import (
    CaseOutcome,
    Evidence,
    EvidenceAdmissionPolicy,
    LayerResult,
    LedgerEntry,
    LedgerError,
    MemoryLedger,
)


def make_candidate() -> ArtifactRef:
    """A candidate artifact to hang evidence on."""
    return ArtifactRef(
        surface=SurfaceKind.HARNESS,
        substrate=SubstrateKind.PHYSICAL,
        content_id=ContentId.of(b"candidate"),
        release_id=ReleaseId("r1"),
    )


def make_evidence(
    *,
    layers: tuple[LayerResult, ...],
    declared: tuple[str, ...] = ("data", "controller"),
    attribution: str | None = "data",
    case_count: int = 1,
) -> Evidence:
    """Build evidence with the same layer results on every case."""
    cases = tuple(CaseOutcome(f"case_{i}", seed=i, layers=layers) for i in range(case_count))
    return Evidence(
        scenario=ScenarioId("demo"),
        candidate=make_candidate(),
        baseline=None,
        cases=cases,
        declared_layers=declared,
        attribution=attribution,
    )


class TestUnverifiedWorkIsNotAccepted:
    """A candidate with incomplete evidence must be deferred, never accepted."""

    def test_layer_reported_not_run_is_inconclusive_not_rejected(self) -> None:
        """A layer that did not execute must not be counted as a failure."""
        evidence = make_evidence(
            layers=(
                LayerResult("data", LayerStatus.PASSED),
                LayerResult("controller", LayerStatus.NOT_RUN),
            )
        )
        verdict, reason = EvidenceAdmissionPolicy().decide(evidence)
        assert verdict is Verdict.INCONCLUSIVE
        assert "controller" in reason

    def test_layer_with_no_result_at_all_is_inconclusive(self) -> None:
        """A layer that never reported anything is also incomplete, not failed."""
        evidence = make_evidence(layers=(LayerResult("data", LayerStatus.PASSED),))
        verdict, reason = EvidenceAdmissionPolicy().decide(evidence)
        assert verdict is Verdict.INCONCLUSIVE
        assert "controller" in reason

    def test_skipped_layer_is_inconclusive_and_not_a_pass(self) -> None:
        """A skip is neither a pass nor a failure, and cannot be admitted."""
        evidence = make_evidence(
            layers=(
                LayerResult("data", LayerStatus.PASSED),
                LayerResult("controller", LayerStatus.SKIPPED, {"reason": "no simulator available"}),
            )
        )
        verdict, reason = EvidenceAdmissionPolicy().decide(evidence)
        assert verdict is Verdict.INCONCLUSIVE
        assert "skipped" in reason

    def test_skip_without_a_reason_is_refused_at_construction(self) -> None:
        """A skip must say why, so an operator can tell it from an oversight."""
        with pytest.raises(LedgerError, match="without a reason"):
            LayerResult("controller", LayerStatus.SKIPPED)

    def test_case_with_no_layers_cannot_pass_vacuously(self) -> None:
        """A case carrying no results must not read as a clean pass."""
        evidence = make_evidence(layers=())
        verdict, _ = EvidenceAdmissionPolicy().decide(evidence)
        assert verdict is Verdict.INCONCLUSIVE

    def test_no_cases_is_inconclusive(self) -> None:
        """Evidence with no instances cannot support any claim."""
        evidence = make_evidence(layers=(LayerResult("data", LayerStatus.PASSED),), case_count=0)
        verdict, reason = EvidenceAdmissionPolicy().decide(evidence)
        assert verdict is Verdict.INCONCLUSIVE
        assert "no cases" in reason


class TestFailuresAreBlamedCorrectly:
    """A rejection must name the layer that actually failed."""

    def test_real_failure_is_rejected_and_blames_the_layer(self) -> None:
        """A layer that ran and failed produces a rejection naming it."""
        evidence = make_evidence(
            layers=(
                LayerResult("data", LayerStatus.PASSED),
                LayerResult("controller", LayerStatus.FAILED, {"detail": "orientation 18mm off"}),
            )
        )
        verdict, reason = EvidenceAdmissionPolicy().decide(evidence)
        assert verdict is Verdict.REJECTED
        assert "controller" in reason

    def test_partial_case_failure_is_rejected(self) -> None:
        """One failing case among passing ones is still a rejection."""
        cases = (
            CaseOutcome("c1", 0, (LayerResult("data", LayerStatus.PASSED),)),
            CaseOutcome("c2", 1, (LayerResult("data", LayerStatus.FAILED),)),
        )
        evidence = Evidence(
            scenario=ScenarioId("demo"),
            candidate=make_candidate(),
            baseline=None,
            cases=cases,
            declared_layers=("data",),
            attribution="data",
        )
        verdict, reason = EvidenceAdmissionPolicy().decide(evidence)
        assert verdict is Verdict.REJECTED
        assert "1/2" in reason


class TestAttributionIsRequired:
    """Acceptance requires naming the layer the outcome is credited to."""

    def test_missing_attribution_is_inconclusive(self) -> None:
        """A clean pass with no attribution cannot be accepted."""
        evidence = make_evidence(
            layers=(LayerResult("data", LayerStatus.PASSED),),
            declared=("data",),
            attribution=None,
        )
        verdict, reason = EvidenceAdmissionPolicy(baseline_pass_rate=0.5).decide(evidence)
        assert verdict is Verdict.INCONCLUSIVE
        assert "attribution" in reason

    def test_attribution_outside_declared_layers_is_refused(self) -> None:
        """Blaming a layer that was never declared is not evidence, it is a guess."""
        with pytest.raises(LedgerError, match="not among the declared layers"):
            make_evidence(
                layers=(LayerResult("data", LayerStatus.PASSED),),
                declared=("data",),
                attribution="controller",
            )


class TestBaselineIsRequired:
    """A gain cannot be claimed without a measured baseline to compare against."""

    def test_missing_baseline_is_inconclusive(self) -> None:
        """Without a baseline the improvement is indistinguishable from noise."""
        evidence = make_evidence(layers=(LayerResult("data", LayerStatus.PASSED),), declared=("data",))
        verdict, reason = EvidenceAdmissionPolicy().decide(evidence)
        assert verdict is Verdict.INCONCLUSIVE
        assert "baseline" in reason

    def test_insufficient_improvement_is_rejected(self) -> None:
        """A gain below the required margin is treated as noise."""
        evidence = make_evidence(layers=(LayerResult("data", LayerStatus.PASSED),), declared=("data",))
        verdict, reason = EvidenceAdmissionPolicy(
            baseline_pass_rate=1.0,
            min_improvement=0.05,
        ).decide(evidence)
        assert verdict is Verdict.REJECTED
        assert "improvement" in reason

    def test_complete_evidence_with_a_real_gain_is_accepted(self) -> None:
        """The happy path: every layer ran, passed, and beat a measured baseline."""
        evidence = make_evidence(layers=(LayerResult("data", LayerStatus.PASSED),), declared=("data",))
        verdict, reason = EvidenceAdmissionPolicy(baseline_pass_rate=0.5).decide(evidence)
        assert verdict is Verdict.ACCEPTED
        assert "data" in reason


class TestLedgerIsAppendOnly:
    """A recorded decision can never be rewritten."""

    def test_duplicate_entry_is_refused(self) -> None:
        """Re-recording the same entry id is refused rather than overwriting."""
        ledger = MemoryLedger()
        evidence = make_evidence(layers=(LayerResult("data", LayerStatus.PASSED),), declared=("data",))
        entry = LedgerEntry("e1", evidence, Verdict.ACCEPTED, "ok")
        ledger.append(entry)
        with pytest.raises(LedgerError, match="append-only"):
            ledger.append(entry)

    def test_accepted_chain_tracks_only_accepted_entries(self) -> None:
        """The accepted chain excludes rejections and deferrals."""
        ledger = MemoryLedger()
        evidence = make_evidence(layers=(LayerResult("data", LayerStatus.PASSED),), declared=("data",))
        ledger.append(LedgerEntry("e1", evidence, Verdict.REJECTED, "no"))
        ledger.append(LedgerEntry("e2", evidence, Verdict.ACCEPTED, "yes"))
        ledger.append(LedgerEntry("e3", evidence, Verdict.INCONCLUSIVE, "later"))
        chain = ledger.accepted_chain(scenario=ScenarioId("demo"))
        assert len(chain) == 1

    def test_entries_are_isolated_per_scenario(self) -> None:
        """One scenario's decisions never appear in another's history."""
        ledger = MemoryLedger()
        evidence = make_evidence(layers=(LayerResult("data", LayerStatus.PASSED),), declared=("data",))
        ledger.append(LedgerEntry("e1", evidence, Verdict.ACCEPTED, "ok"))
        assert len(ledger.entries(scenario=ScenarioId("demo"))) == 1
        assert len(ledger.entries(scenario=ScenarioId("other"))) == 0
