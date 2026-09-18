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

"""A harness recipe and its verifier: the smallest honest improvement loop.

The recipe raises the prompt's hint length when the observed accuracy is low. The
verifier runs the declared layers against both the candidate and the current release,
because a candidate's pass rate alone cannot distinguish an improvement from a
regression: without the baseline measurement, the admission policy has nothing to
compare against and must return ``INCONCLUSIVE``.

**Why the verifier measures the baseline itself.** The alternative is to accept a
baseline figure from the recipe, which would let the party that produced the change
also supply the number used to judge it. The architecture document forbids that, and
this implementation is where the rule stops being a sentence in a document.

**The layers, and why each one is separate.** ``contract`` checks the prompt parses.
``behavior`` checks the substrate answers correctly under it. They are declared
separately so that a malformed prompt is reported as a contract failure rather than
as a behavior failure, which would blame the wrong layer and make the ledger's
attribution wrong. That distinction is the whole reason the ledger exists.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from rsihybridagent.artifact import ArtifactError
from rsihybridagent.core import ArtifactRef, Feedback, LayerStatus, Receipt, ScenarioId, Surface
from rsihybridagent.ledger.base import CaseOutcome, Evidence, LayerResult
from rsihybridagent.loop import Recipe, Verifier
from rsihybridagent.substrate.arithmetic import (
    PROMPT_PATH,
    ArithmeticRequest,
    ArithmeticSubstrate,
    _parse_hint_length,
    render_prompt,
)

#: Layer names, declared once so the verifier and any operator reading a ledger entry
#: refer to the same strings. A typo here would make a layer look unrun.
LAYER_CONTRACT = "contract"
LAYER_BEHAVIOR = "behavior"


@dataclass(frozen=True)
class HarnessHintRecipe(Recipe):
    """Raises the prompt's hint length when accuracy is below target.

    The recipe is where method-specific policy lives: how much to raise the hint, and
    how much evidence is enough to try. The loop never inspects any of this.
    """

    surface: Surface
    target_accuracy: float = 0.95
    step: int = 1
    min_observations: int = 1
    max_hint: int | None = None
    _observed: list[tuple[Receipt, bool]] = field(default_factory=list, init=False, repr=False)

    def target_surface(self) -> Surface:
        """The harness surface this recipe writes candidates into."""
        return self.surface

    def observe(self, receipt: Receipt, result: Mapping[str, Any]) -> None:
        """Record one interaction's outcome for a later proposal.

        Not part of the :class:`~rsihybridagent.loop.Recipe` contract, because how a
        recipe collects signal is method-specific. The loop hands feedback to
        :meth:`eligible`; a deployment wires this in wherever its substrate reports.
        """
        self._observed.append((receipt, bool(result.get("correct"))))

    def eligible(self, receipts: tuple[Receipt, ...], feedback: Feedback, *, scenario: ScenarioId) -> bool:
        """Whether there is enough signal to attempt an update.

        A score below target is the only reason to grow. When accuracy already meets the
        target, returning ``False`` is the correct outcome: proposing a change with no
        reason would spend a verification budget and add an entry the ledger cannot
        justify.
        """
        if len(receipts) < self.min_observations:
            return False
        if feedback.score is None:
            return False
        return feedback.score < self.target_accuracy

    def propose(self, *, scenario: ScenarioId) -> ArtifactRef | None:
        """Stage a prompt with a higher hint length, or ``None`` when already maximal.

        ``None`` is an ordinary outcome, not an error. A recipe that had exhausted its
        search space must be distinguishable from one that tried and failed, so this
        returns rather than raising.

        ``max_hint`` is a field rather than a constant read from :data:`_CASES`, because
        the recipe's search range and the verifier's case set are independent inputs. An
        earlier version derived the range from the module's default cases, so a verifier
        given a different set would silently cap the recipe at the wrong value — and the
        mismatch would look like "the recipe stopped improving" rather than a
        configuration error. A recipe that reaches a ceiling it cannot justify is worse
        than one that stops and says so.
        """
        head = self.surface.current(scenario=scenario)
        if head is None:
            raise ArtifactError(
                f"scenario {scenario.name!r} has no released prompt to improve; "
                "the loop must publish a baseline before a recipe can grow from it"
            )
        artifact = self.surface.repository().materialize(head, scenario=scenario)
        current_hint = _parse_hint_length(artifact.text(PROMPT_PATH))

        ceiling = self.max_hint if self.max_hint is not None else max(len(str(c.expected)) for c in _CASES)
        if current_hint >= ceiling:
            return None

        target = min(current_hint + self.step, ceiling)
        return self.surface.stage(
            scenario=scenario,
            files={PROMPT_PATH: render_prompt(target)},
            metadata={"recipe": "harness_hint", "from_hint": current_hint, "to_hint": target},
        )

#: The verification set. Fixed and small so a run is deterministic and fast; a real
#: deployment would draw these from a scenario's recorded interactions instead.
_CASES: tuple[ArithmeticRequest, ...] = (
    ArithmeticRequest("2+3", 5),
    ArithmeticRequest("7*6", 42),
    ArithmeticRequest("100-37", 63),
    ArithmeticRequest("9+9+9", 27),
    ArithmeticRequest("12*12", 144),
    ArithmeticRequest("1000-1", 999),
)


@dataclass(frozen=True)
class ArithmeticVerifier(Verifier):
    """Runs the declared layers against a candidate and against the current release.

    The baseline is measured through the same code path as the candidate. Measuring it
    differently would make any difference between the two paths indistinguishable from
    the improvement being measured, which is the classic way a benchmark lies.
    """

    surface: Surface
    cases: Sequence[ArithmeticRequest] = _CASES
    seed: int = 0

    def declared_layers(self) -> tuple[str, ...]:
        """The layers this verifier will run, named before any run starts.

        Declaring up front is what lets the ledger notice a layer that never ran. A
        verifier that reported only the layers it happened to execute could not
        distinguish an omitted check from a passed one.
        """
        return (LAYER_CONTRACT, LAYER_BEHAVIOR)

    def verify(self, candidate: ArtifactRef, *, scenario: ScenarioId) -> Evidence:
        """Score the candidate and its baseline, returning complete evidence.

        The candidate is scored first and the baseline second, because the candidate's
        rate is the one the ledger records. An earlier version measured the baseline into
        the same variable and overwrote the candidate's rate with it, which produced
        evidence that looked complete while reporting the wrong artifact's performance.
        """
        candidate_outcomes = self._run(candidate, scenario=scenario)
        candidate_rate = _rate(candidate_outcomes)

        baseline = self.surface.current(scenario=scenario)
        baseline_rate = self._rate_of(baseline, scenario=scenario) if baseline is not None else None

        return Evidence(
            scenario=scenario,
            candidate=candidate,
            baseline=baseline,
            cases=candidate_outcomes,
            declared_layers=self.declared_layers(),
            attribution=LAYER_BEHAVIOR,
            notes=(
                f"candidate pass rate {candidate_rate:.3f} against baseline "
                f"{'unmeasured' if baseline_rate is None else f'{baseline_rate:.3f}'}; "
                f"{len(candidate_outcomes)} cases at seed {self.seed}"
            ),
        )

    def baseline_pass_rate(self, *, scenario: ScenarioId) -> float | None:
        """The current release's measured rate, or ``None`` when nothing is released."""
        return self._rate_of(self.surface.current(scenario=scenario), scenario=scenario)

    def _rate_of(self, artifact: ArtifactRef | None, *, scenario: ScenarioId) -> float | None:
        """Measure one artifact over every case. ``None`` when there is nothing to measure."""
        if artifact is None:
            return None
        return _rate(self._run(artifact, scenario=scenario))

    def _run(self, artifact: ArtifactRef, *, scenario: ScenarioId) -> tuple[CaseOutcome, ...]:
        """Evaluate one artifact over every case, in case order.

        Both the candidate and the baseline go through this one method, so the two
        measurements cannot differ by anything except the artifact. Measuring them on
        separate code paths would make any difference between those paths
        indistinguishable from the improvement being measured.
        """
        return tuple(
            CaseOutcome(
                case_id=case.expression,
                seed=self.seed,
                layers=self._layers_for(artifact, case, scenario=scenario),
            )
            for case in self.cases
        )

    def _layers_for(
        self,
        artifact: ArtifactRef,
        case: ArithmeticRequest,
        *,
        scenario: ScenarioId,
    ) -> tuple[LayerResult, ...]:
        """Run both declared layers for one case, reporting each separately.

        A contract failure short-circuits the behavior layer, and the behavior layer is
        then reported as ``NOT_RUN`` rather than ``FAILED``. Reporting it as failed would
        blame a layer that never executed, which is the misattribution the ledger is
        built to prevent.
        """
        body = self.surface.repository().materialize(artifact, scenario=scenario)

        try:
            hint_length = _parse_hint_length(body.text(PROMPT_PATH))
        except ArtifactError as exc:
            return (
                LayerResult(layer=LAYER_CONTRACT, status=LayerStatus.FAILED, detail={"error": str(exc)}),
                LayerResult(
                    layer=LAYER_BEHAVIOR,
                    status=LayerStatus.NOT_RUN,
                    detail={"reason": "contract layer failed, so behavior was never exercised"},
                ),
            )

        contract = LayerResult(
            layer=LAYER_CONTRACT,
            status=LayerStatus.PASSED,
            detail={"hint_length": hint_length},
        )

        answer = ArithmeticSubstrate._answer(case.expression, case.expected, hint_length)
        behavior = LayerResult(
            layer=LAYER_BEHAVIOR,
            status=LayerStatus.PASSED if answer == case.expected else LayerStatus.FAILED,
            detail={
                "expression": case.expression,
                "expected": case.expected,
                "answer": answer,
                "hint_length": hint_length,
            },
        )
        return (contract, behavior)


def _rate(outcomes: tuple[CaseOutcome, ...]) -> float:
    """Fraction of cases where every declared layer ran and passed."""
    if not outcomes:
        return 0.0
    return sum(1 for case in outcomes if case.all_layers_passed) / len(outcomes)
