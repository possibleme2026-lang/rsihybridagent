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

"""How to attach the framework to your own environment: a complete template.

Run it with::

    PYTHONPATH=src python examples/custom_substrate.py

The task here is a threshold classifier, chosen because it is the smallest thing with a
real decision boundary. A policy file declares a threshold; the substrate labels an input
as ``high`` when it reaches that threshold. A wrong threshold produces wrong labels, so a
recipe has something real to fix and the ledger has something real to judge.

**Read this file as a template, not as a task.** Every place you would substitute your own
system is marked ``YOUR SYSTEM``. There are five of them, and the total is under sixty
lines of code:

1. the prompt/policy format the substrate reads,
2. ``execute`` — where you call your own system,
3. ``health`` — how you decide whether it is ready,
4. ``verifier`` — how you score a candidate,
5. ``recipe`` — how you propose the next candidate.

The framework supplies the rest: release chains, the artifact repository, the ledger, the
admission policy, the loop's ordering guarantees, and scenario isolation.

**What is deliberately not here.** No simulator, no model, no network. The point is the
seam, and a seam is easier to see when nothing else is moving.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rsihybridagent.artifact import ArtifactError
from rsihybridagent.core import (
    ArtifactRef,
    Feedback,
    LayerStatus,
    Receipt,
    ScenarioId,
    Substrate,
    SubstrateKind,
    Surface,
    SurfaceKind,
    Verdict,
)
from rsihybridagent.ledger.base import CaseOutcome, Evidence, LayerResult
from rsihybridagent.ledger.memory import MemoryLedger
from rsihybridagent.ledger.policy import EvidenceAdmissionPolicy
from rsihybridagent.loop import Recipe, RecursiveLoop, Verifier
from rsihybridagent.surfaces.memory import MemoryArtifactRepository, MemorySurface

SCENARIO = ScenarioId("threshold-demo")

#: YOUR SYSTEM (1/5): the policy file your substrate reads. It travels with the artifact,
#: so an accepted change is a change to this text.
POLICY_PATH = "policy.md"

LAYER_POLICY = "policy"
LAYER_ACCURACY = "accuracy"


@dataclass(frozen=True)
class Sample:
    """One labelled input. In a real deployment these come from your recorded traffic."""

    value: int
    label: str


#: The evaluation set. Fixed so a run is deterministic; a real deployment would draw these
#: from the scenario's own history, which is what makes the measurement meaningful.
SAMPLES: tuple[Sample, ...] = (
    Sample(1, "low"),
    Sample(2, "low"),
    Sample(3, "low"),
    Sample(9, "high"),
    Sample(10, "high"),
    Sample(11, "high"),
)


def render_policy(threshold: int) -> str:
    """Render the policy text declaring a threshold.

    Beside the parser, because the substrate owns this format. A recipe that rendered its
    own version could drift from what the parser accepts, and the failure would surface as
    a policy-layer failure blamed on the wrong party.
    """
    if threshold < 0:
        raise ArtifactError(f"a threshold must not be negative ({threshold})")
    return (
        "# Classification policy\n"
        "#\n"
        "# threshold: an input at or above this value is labelled 'high'.\n"
        f"threshold: {threshold}\n"
    )


def parse_threshold(policy: str) -> int:
    """Read ``threshold: N`` out of the policy, refusing anything unparseable.

    The policy is a file an evolution step may rewrite, so it is untrusted input at this
    boundary. Parsing strictly means a malformed edit fails here with a clear message,
    rather than producing silently wrong labels the ledger would attribute to the wrong
    layer.
    """
    for raw in policy.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if sep and key.strip() == "threshold":
            try:
                return int(value.strip())
            except ValueError as exc:
                raise ArtifactError(f"policy declares threshold as {value.strip()!r}, not an integer") from exc
    raise ArtifactError(
        f"policy has no 'threshold' declaration, so there is nothing to follow; "
        f"expected a line like 'threshold: 5' in {POLICY_PATH}"
    )


# --------------------------------------------------------------------------------------
# YOUR SYSTEM (2/5 and 3/5): the substrate. Replace the body of ``execute`` with a call to
# whatever you actually run, and the body of ``health`` with your readiness check.
# --------------------------------------------------------------------------------------
class ThresholdSubstrate(Substrate):
    """Labels inputs using the threshold currently released for the scenario.

    It reads the surface on every call rather than caching the policy at construction.
    That is what makes an accepted improvement take effect immediately; a substrate that
    cached it would pass every test and never reflect an update in production.
    """

    def __init__(self, *, surface: Surface) -> None:
        self._surface = surface
        self._served = 0

    def kind(self) -> SubstrateKind:
        """A digital substrate: no simulator, no robot."""
        return SubstrateKind.DIGITAL

    def execute(self, request: Mapping[str, Any], *, scenario: ScenarioId) -> tuple[Receipt, Mapping[str, Any]]:
        """Label one input.

        YOUR SYSTEM (2/5): everything above the marked line is the framework's; the call
        itself is where your system goes. If your system is a separate process, this is
        where the RPC happens — the rest of the file does not change.
        """
        value = int(request.get("value", 0))
        threshold = self._threshold(scenario)

        label = "high" if value >= threshold else "low"  # <-- replace with your call

        self._served += 1
        receipt = Receipt(value=f"{scenario.name}-{self._served:04d}", scenario=scenario)
        return receipt, {"value": value, "label": label, "threshold": threshold}

    def health(self, *, scenario: ScenarioId) -> Mapping[str, Any]:
        """Report readiness for one scenario.

        YOUR SYSTEM (3/5): replace this with your own readiness check — a ping, a
        connection test, a device enumeration. It takes a scenario because readiness is
        per scenario: a substrate whose policy was never released for a scenario cannot
        serve it, and a global answer would call that state healthy.
        """
        problem = None if self._surface.current(scenario=scenario) is not None else "no policy released"
        return {"healthy": problem is None, "problem": problem, "served": self._served}

    def _threshold(self, scenario: ScenarioId) -> int:
        """Read the released policy and parse its threshold."""
        head = self._surface.current(scenario=scenario)
        if head is None:
            raise ArtifactError(
                f"scenario {scenario.name!r} has no released policy; publish a baseline first"
            )
        body = self._surface.repository().materialize(head, scenario=scenario)
        return parse_threshold(body.text(POLICY_PATH))


# --------------------------------------------------------------------------------------
# YOUR SYSTEM (4/5): the verifier. Replace ``_layers_for`` with your own scoring.
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ThresholdVerifier(Verifier):
    """Scores a candidate on labelled samples, and measures the baseline itself.

    Declaring layers up front is what lets the ledger notice a layer that never ran. The
    verifier measures the baseline through the same code path as the candidate, because
    measuring them differently would make any difference between the paths
    indistinguishable from the improvement being measured.
    """

    surface: Surface
    samples: Sequence[Sample] = SAMPLES

    def declared_layers(self) -> tuple[str, ...]:
        """The layers this verifier will run, named before any run starts."""
        return (LAYER_POLICY, LAYER_ACCURACY)

    def verify(self, candidate: ArtifactRef, *, scenario: ScenarioId) -> Evidence:
        """Score the candidate and its baseline, returning complete evidence."""
        cases = self._score(candidate, scenario=scenario)
        baseline = self.surface.current(scenario=scenario)
        baseline_rate = None if baseline is None else _rate(self._score(baseline, scenario=scenario))

        return Evidence(
            scenario=scenario,
            candidate=candidate,
            baseline=baseline,
            cases=cases,
            declared_layers=self.declared_layers(),
            attribution=LAYER_ACCURACY,
            notes=(
                f"candidate {_rate(cases):.3f} against baseline "
                f"{'unmeasured' if baseline_rate is None else f'{baseline_rate:.3f}'}"
            ),
        )

    def baseline_pass_rate(self, *, scenario: ScenarioId) -> float | None:
        """The current release's measured accuracy, or ``None`` when nothing is released."""
        head = self.surface.current(scenario=scenario)
        return None if head is None else _rate(self._score(head, scenario=scenario))

    def _score(self, artifact: ArtifactRef, *, scenario: ScenarioId) -> tuple[CaseOutcome, ...]:
        """Score one artifact over every sample."""
        return tuple(
            CaseOutcome(
                case_id=f"value={sample.value}",
                seed=0,
                layers=self._layers_for(artifact, sample, scenario=scenario),
            )
            for sample in self.samples
        )

    def _layers_for(
        self,
        artifact: ArtifactRef,
        sample: Sample,
        *,
        scenario: ScenarioId,
    ) -> tuple[LayerResult, ...]:
        """YOUR SYSTEM (4/5): replace the two layers with your own scoring.

        A policy failure short-circuits the accuracy layer, and accuracy is then reported
        as ``NOT_RUN`` rather than ``FAILED``. Reporting it as failed would blame a layer
        that never executed, which is the misattribution this whole design exists to
        prevent.
        """
        body = self.surface.repository().materialize(artifact, scenario=scenario)

        try:
            threshold = parse_threshold(body.text(POLICY_PATH))
        except ArtifactError as exc:
            return (
                LayerResult(layer=LAYER_POLICY, status=LayerStatus.FAILED, detail={"error": str(exc)}),
                LayerResult(
                    layer=LAYER_ACCURACY,
                    status=LayerStatus.NOT_RUN,
                    detail={"reason": "the policy layer failed, so accuracy was never exercised"},
                ),
            )

        predicted = "high" if sample.value >= threshold else "low"
        return (
            LayerResult(layer=LAYER_POLICY, status=LayerStatus.PASSED, detail={"threshold": threshold}),
            LayerResult(
                layer=LAYER_ACCURACY,
                status=LayerStatus.PASSED if predicted == sample.label else LayerStatus.FAILED,
                detail={"value": sample.value, "expected": sample.label, "predicted": predicted},
            ),
        )


# --------------------------------------------------------------------------------------
# YOUR SYSTEM (5/5): the recipe. Replace ``propose`` with how you generate the next
# candidate — a prompt edit, a fine-tune, a memory merge, anything.
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ThresholdRecipe(Recipe):
    """Raises the threshold by a fixed step until the samples are satisfied.

    A recipe is where method-specific policy lives: how much to move, and how much signal
    is enough to try. The loop never inspects any of this.
    """

    surface: Surface
    step: int = 4
    max_threshold: int = 16

    def target_surface(self) -> Surface:
        """The surface this recipe writes candidates into."""
        return self.surface

    def eligible(self, receipts: tuple[Receipt, ...], feedback: Feedback, *, scenario: ScenarioId) -> bool:
        """Whether there is enough signal to attempt an update.

        Below target accuracy is the only reason to grow. Returning ``False`` when the
        target is already met is the correct outcome: proposing a change with no reason
        would spend a verification budget on an entry the ledger cannot justify.
        """
        return bool(receipts) and feedback.score is not None and feedback.score < 0.95

    def propose(self, *, scenario: ScenarioId) -> ArtifactRef | None:
        """Stage a policy with a higher threshold, or ``None`` at the ceiling.

        YOUR SYSTEM (5/5): replace this with your own generation step. ``None`` is an
        ordinary outcome — a recipe that has exhausted its range must be distinguishable
        from one that tried and failed, so this returns rather than raising.
        """
        head = self.surface.current(scenario=scenario)
        if head is None:
            raise ArtifactError(f"scenario {scenario.name!r} has no released policy to improve")

        body = self.surface.repository().materialize(head, scenario=scenario)
        current = parse_threshold(body.text(POLICY_PATH))
        if current >= self.max_threshold:
            return None

        target = min(current + self.step, self.max_threshold)
        return self.surface.stage(
            scenario=scenario,
            files={POLICY_PATH: render_policy(target)},
            metadata={"from_threshold": current, "to_threshold": target},
        )


def _rate(cases: tuple[CaseOutcome, ...]) -> float:
    """Fraction of cases where every declared layer ran and passed."""
    if not cases:
        return 0.0
    return sum(1 for case in cases if case.all_layers_passed) / len(cases)


def main() -> int:
    """Wire the five pieces together and run one turn."""
    repository = MemoryArtifactRepository()
    surface = MemorySurface(SurfaceKind.HARNESS, repository)
    ledger = MemoryLedger()

    # A baseline that is deliberately wrong, so the turn has something to fix. A threshold
    # of 1 labels every sample 'high', which is wrong for the three that should be 'low';
    # the correct boundary is 9, and the recipe raises the threshold toward it.
    baseline = surface.stage(scenario=SCENARIO, files={POLICY_PATH: render_policy(1)})
    surface.publish(baseline, scenario=SCENARIO)

    substrate = ThresholdSubstrate(surface=surface)
    verifier = ThresholdVerifier(surface=surface)

    print("Attaching a custom substrate — five extension points, one turn\n" + "-" * 58)

    before = verifier.baseline_pass_rate(scenario=SCENARIO)
    print(f"1. baseline accuracy      {before:.3f}  (threshold 1, released as {baseline.release_id.value})")

    health = substrate.health(scenario=SCENARIO)
    print(f"2. substrate health       healthy={health['healthy']}")

    loop = RecursiveLoop(
        substrate=substrate,
        recipe=ThresholdRecipe(surface=surface, step=4, max_threshold=9),
        verifier=verifier,
        policy=EvidenceAdmissionPolicy(
            min_pass_rate=0.95,
            min_improvement=0.1,
            baseline_pass_rate=before,
        ),
        ledger=ledger,
    )

    receipt, body = loop.serve({"value": 2}, scenario=SCENARIO)
    print(f"3. serve                  value=2 -> {body['label']!r} (expected 'low')")

    eligible = loop.observe(Feedback(receipts=(receipt,), score=0.0), scenario=SCENARIO)
    print(f"4. observe                eligible={eligible}")

    candidate = loop.grow(scenario=SCENARIO)
    assert candidate is not None
    meta = dict(candidate.metadata)
    print(f"5. grow                   threshold {meta['from_threshold']} -> {meta['to_threshold']}")

    entry = loop.commit(candidate, scenario=SCENARIO)
    assert entry is not None
    print(f"6. commit                 verdict={entry.verdict.value}")
    print(f"                          {entry.reason}")

    live = surface.current(scenario=SCENARIO)
    assert live is not None
    _, after = loop.serve({"value": 2}, scenario=SCENARIO)
    print(f"7. serve again            value=2 -> {after['label']!r} (no restart needed)")

    print(f"\nledger entries: {len(ledger.entries(scenario=SCENARIO))}")
    for recorded in ledger.entries(scenario=SCENARIO):
        marker = "accepted" if recorded.verdict is Verdict.ACCEPTED else recorded.verdict.value
        print(f"  {recorded.entry_id}  {marker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
