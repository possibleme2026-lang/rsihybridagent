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

"""Tests for the integration template.

The template is documentation that happens to be executable, and it is the file a reader
copies. That makes it worth testing on two grounds: it must keep running as the framework
changes, and the specific claims its comments make — that the policy is re-read per call,
that a policy failure leaves accuracy ``NOT_RUN`` — must stay true.

A template that silently rotted would be worse than no template, because the reader would
copy something that no longer reflects the framework.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from rsihybridagent.artifact import ArtifactError
from rsihybridagent.core import LayerStatus, ScenarioId, SurfaceKind
from rsihybridagent.ledger.memory import MemoryLedger
from rsihybridagent.ledger.policy import EvidenceAdmissionPolicy
from rsihybridagent.loop import RecursiveLoop
from rsihybridagent.surfaces.memory import MemoryArtifactRepository, MemorySurface

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "examples" / "custom_substrate.py"


def _load_template() -> object:
    """Import the template, which is an example rather than an installed module."""
    spec = importlib.util.spec_from_file_location("custom_substrate", TEMPLATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["custom_substrate"] = module
    spec.loader.exec_module(module)
    return module


template = _load_template()


class TestPolicyParsing:
    """The policy format is the substrate's contract, so its parser is tested directly."""

    def test_a_rendered_policy_round_trips(self) -> None:
        """Rendering then parsing must recover the value."""
        assert template.parse_threshold(template.render_policy(9)) == 9

    def test_a_negative_threshold_cannot_be_rendered(self) -> None:
        """Rendering refuses a value the parser would reject, so the two agree."""
        with pytest.raises(ArtifactError, match="negative"):
            template.render_policy(-1)

    def test_a_policy_with_no_threshold_is_refused(self) -> None:
        """A malformed policy fails loudly rather than defaulting.

        A silent default would produce labels under a policy nobody chose, and the ledger
        would attribute them to an artifact that was never live.
        """
        with pytest.raises(ArtifactError, match="no 'threshold' declaration"):
            template.parse_threshold("nothing useful\n")

    def test_a_non_integer_threshold_is_refused(self) -> None:
        """A value that is not an integer is reported as such, not silently coerced."""
        with pytest.raises(ArtifactError, match="not an integer"):
            template.parse_threshold("threshold: soon\n")

    def test_comment_lines_are_ignored(self) -> None:
        """A comment must not be mistaken for the declaration."""
        assert template.parse_threshold("# threshold: 99\nthreshold: 4\n") == 4


class TestSubstrate:
    """The substrate must read the live release, and report readiness per scenario."""

    def _rig(self, threshold: int = 9) -> tuple[MemorySurface, object]:
        surface = MemorySurface(SurfaceKind.HARNESS, MemoryArtifactRepository())
        head = surface.stage(
            scenario=ScenarioId("t"),
            files={template.POLICY_PATH: template.render_policy(threshold)},
        )
        surface.publish(head, scenario=ScenarioId("t"))
        return surface, template.ThresholdSubstrate(surface=surface)

    def test_execute_labels_using_the_released_threshold(self) -> None:
        """An input at or above the threshold is labelled high."""
        _, substrate = self._rig(threshold=9)
        _, high = substrate.execute({"value": 9}, scenario=ScenarioId("t"))
        _, low = substrate.execute({"value": 8}, scenario=ScenarioId("t"))
        assert high["label"] == "high"
        assert low["label"] == "low"

    def test_execute_reflects_a_new_release_without_reconstruction(self) -> None:
        """The policy is read per call, which is what the template's comment claims.

        This is the claim worth testing: a substrate that cached the policy would pass
        every other test here and never reflect an update in production.
        """
        surface, substrate = self._rig(threshold=9)
        _, before = substrate.execute({"value": 5}, scenario=ScenarioId("t"))
        assert before["label"] == "low"

        newer = surface.stage(
            scenario=ScenarioId("t"),
            files={template.POLICY_PATH: template.render_policy(3)},
        )
        surface.publish(newer, scenario=ScenarioId("t"))

        _, after = substrate.execute({"value": 5}, scenario=ScenarioId("t"))
        assert after["label"] == "high", "the substrate did not pick up the new release"

    def test_serving_without_a_release_is_refused(self) -> None:
        """A scenario with no released policy cannot be served."""
        surface = MemorySurface(SurfaceKind.HARNESS, MemoryArtifactRepository())
        substrate = template.ThresholdSubstrate(surface=surface)
        with pytest.raises(ArtifactError, match="no released policy"):
            substrate.execute({"value": 1}, scenario=ScenarioId("never-released"))

    def test_health_is_per_scenario(self) -> None:
        """Readiness is reported for the scenario asked about, not globally."""
        _, substrate = self._rig()
        assert substrate.health(scenario=ScenarioId("t"))["healthy"] is True
        assert substrate.health(scenario=ScenarioId("other"))["healthy"] is False

    def test_kind_is_digital(self) -> None:
        """The template's substrate declares itself digital, and that is what it is."""
        _, substrate = self._rig()
        assert substrate.kind().value == "digital"


class TestVerifier:
    """The verifier must measure the baseline itself and keep NOT_RUN distinct."""

    def _rig(self, threshold: int = 1) -> tuple[MemorySurface, object]:
        surface = MemorySurface(SurfaceKind.HARNESS, MemoryArtifactRepository())
        head = surface.stage(
            scenario=ScenarioId("t"),
            files={template.POLICY_PATH: template.render_policy(threshold)},
        )
        surface.publish(head, scenario=ScenarioId("t"))
        return surface, template.ThresholdVerifier(surface=surface)

    def test_declared_layers_are_named_before_any_run(self) -> None:
        """Layers are declared up front, which is what lets the ledger spot a missing one."""
        _, verifier = self._rig()
        assert verifier.declared_layers() == (template.LAYER_POLICY, template.LAYER_ACCURACY)

    def test_a_correct_threshold_passes_every_case(self) -> None:
        """A threshold on the real boundary scores perfectly."""
        surface, verifier = self._rig(threshold=9)
        candidate = surface.stage(
            scenario=ScenarioId("t"),
            files={template.POLICY_PATH: template.render_policy(9)},
        )
        evidence = verifier.verify(candidate, scenario=ScenarioId("t"))
        assert evidence.pass_rate() == 1.0

    def test_a_wrong_threshold_fails_cases(self) -> None:
        """A threshold that mislabels samples is scored as failing."""
        surface, verifier = self._rig(threshold=1)
        candidate = surface.stage(
            scenario=ScenarioId("t"),
            files={template.POLICY_PATH: template.render_policy(1)},
        )
        evidence = verifier.verify(candidate, scenario=ScenarioId("t"))
        assert evidence.pass_rate() < 1.0

    def test_a_policy_failure_leaves_accuracy_not_run(self) -> None:
        """A malformed policy fails the policy layer and leaves accuracy NOT_RUN.

        Reporting accuracy as FAILED would blame a layer that never executed, and a wrong
        attribution corrupts every later decision that reads the entry.
        """
        surface, verifier = self._rig(threshold=9)
        broken = surface.stage(
            scenario=ScenarioId("t"),
            files={template.POLICY_PATH: "no threshold here\n"},
        )
        evidence = verifier.verify(broken, scenario=ScenarioId("t"))

        statuses = {result.layer: result.status for case in evidence.cases for result in case.layers}
        assert statuses[template.LAYER_POLICY] is LayerStatus.FAILED
        assert statuses[template.LAYER_ACCURACY] is LayerStatus.NOT_RUN
        assert template.LAYER_ACCURACY in evidence.not_run_layers()
        assert evidence.skipped_layers() == ()

    def test_the_baseline_is_measured_not_supplied(self) -> None:
        """The verifier reads the baseline from the surface rather than taking a number."""
        _, verifier = self._rig(threshold=9)
        assert verifier.baseline_pass_rate(scenario=ScenarioId("t")) == 1.0

    def test_no_baseline_when_nothing_is_released(self) -> None:
        """With no release there is nothing to measure, and that is reported as None."""
        surface = MemorySurface(SurfaceKind.HARNESS, MemoryArtifactRepository())
        verifier = template.ThresholdVerifier(surface=surface)
        assert verifier.baseline_pass_rate(scenario=ScenarioId("t")) is None


class TestRecipe:
    """The recipe must move toward the boundary and stop rather than overshoot."""

    def _rig(self, threshold: int = 1) -> tuple[MemorySurface, object]:
        surface = MemorySurface(SurfaceKind.HARNESS, MemoryArtifactRepository())
        head = surface.stage(
            scenario=ScenarioId("t"),
            files={template.POLICY_PATH: template.render_policy(threshold)},
        )
        surface.publish(head, scenario=ScenarioId("t"))
        return surface, template.ThresholdRecipe(surface=surface, step=4, max_threshold=9)

    def test_propose_raises_the_threshold_by_the_step(self) -> None:
        """A proposal moves the threshold toward the ceiling."""
        _, recipe = self._rig(threshold=1)
        candidate = recipe.propose(scenario=ScenarioId("t"))
        assert candidate is not None
        assert candidate.metadata["to_threshold"] == 5

    def test_propose_clamps_at_the_ceiling(self) -> None:
        """A step that would overshoot is clamped, not applied literally."""
        _, recipe = self._rig(threshold=8)
        candidate = recipe.propose(scenario=ScenarioId("t"))
        assert candidate is not None
        assert candidate.metadata["to_threshold"] == 9

    def test_propose_returns_none_at_the_ceiling(self) -> None:
        """``None`` is an ordinary outcome, distinguishable from a failed attempt."""
        _, recipe = self._rig(threshold=9)
        assert recipe.propose(scenario=ScenarioId("t")) is None

    def test_eligible_is_false_when_the_target_is_met(self) -> None:
        """Proposing with no reason would spend a budget the ledger cannot justify."""
        from rsihybridagent.core import Feedback, Receipt

        _, recipe = self._rig()
        scenario = ScenarioId("t")
        receipt = Receipt(value="r", scenario=scenario)

        met = Feedback(receipts=(receipt,), score=0.99)
        unmet = Feedback(receipts=(receipt,), score=0.5)
        assert recipe.eligible((receipt,), met, scenario=scenario) is False
        assert recipe.eligible((receipt,), unmet, scenario=scenario) is True


class TestTheTemplateRuns:
    """The template's ``main`` must complete, since the README tells readers to run it."""

    def test_main_completes_successfully(self) -> None:
        """A failing template would make the README's instruction wrong."""
        assert template.main() == 0

    def test_a_full_turn_improves_the_live_artifact(self) -> None:
        """Wiring the five pieces must actually produce an accepted improvement."""
        surface = MemorySurface(SurfaceKind.HARNESS, MemoryArtifactRepository())
        scenario = ScenarioId("turn")
        baseline = surface.stage(
            scenario=scenario,
            files={template.POLICY_PATH: template.render_policy(1)},
        )
        surface.publish(baseline, scenario=scenario)

        substrate = template.ThresholdSubstrate(surface=surface)
        verifier = template.ThresholdVerifier(surface=surface)
        ledger = MemoryLedger()
        before = verifier.baseline_pass_rate(scenario=scenario)
        assert before is not None and before < 1.0

        loop = RecursiveLoop(
            substrate=substrate,
            recipe=template.ThresholdRecipe(surface=surface, step=4, max_threshold=9),
            verifier=verifier,
            policy=EvidenceAdmissionPolicy(
                min_pass_rate=0.95,
                min_improvement=0.1,
                baseline_pass_rate=before,
            ),
            ledger=ledger,
        )

        from rsihybridagent.core import Feedback, Verdict

        receipt, _ = loop.serve({"value": 2}, scenario=scenario)
        assert loop.observe(Feedback(receipts=(receipt,), score=0.0), scenario=scenario) is True
        candidate = loop.grow(scenario=scenario)
        assert candidate is not None
        entry = loop.commit(candidate, scenario=scenario)

        assert entry is not None
        assert entry.verdict is Verdict.ACCEPTED
        assert verifier.baseline_pass_rate(scenario=scenario) == 1.0
        assert len(ledger.entries(scenario=scenario)) == 1
