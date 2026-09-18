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

"""End-to-end tests for the reference loop.

These exercise the four steps together, because the interesting failures are not in
any single step. A recipe that stages correctly, a verifier that scores correctly, and
a policy that decides correctly can still produce a wrong system if the loop publishes
before verifying or if the baseline is measured through a different path than the
candidate.

Each test names the failure it prevents, so a future change that breaks the guarantee
fails a test whose name says what was lost.
"""

from __future__ import annotations

import pytest

from rsihybridagent.artifact import ArtifactError, ArtifactNotFound
from rsihybridagent.core import Feedback, LayerStatus, ScenarioId, SurfaceKind, Verdict
from rsihybridagent.ledger.memory import MemoryLedger
from rsihybridagent.ledger.policy import EvidenceAdmissionPolicy
from rsihybridagent.loop import RecursiveLoop
from rsihybridagent.recipes.harness_hint import (
    LAYER_BEHAVIOR,
    LAYER_CONTRACT,
    ArithmeticVerifier,
    HarnessHintRecipe,
    render_prompt,
)
from rsihybridagent.substrate.arithmetic import PROMPT_PATH, ArithmeticSubstrate
from rsihybridagent.surfaces.memory import MemoryArtifactRepository, MemorySurface

SCENARIO = ScenarioId("demo")


@pytest.fixture
def rig() -> tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger]:
    """A released baseline prompt plus the substrate and ledger that read it."""
    repository = MemoryArtifactRepository()
    surface = MemorySurface(SurfaceKind.HARNESS, repository)
    baseline = surface.stage(scenario=SCENARIO, files={PROMPT_PATH: render_prompt(1)})
    surface.publish(baseline, scenario=SCENARIO)
    return surface, ArithmeticSubstrate(surface=surface), MemoryLedger()


def _loop(
    surface: MemorySurface,
    substrate: ArithmeticSubstrate,
    ledger: MemoryLedger,
    *,
    step: int = 2,
    min_improvement: float = 0.0,
) -> tuple[RecursiveLoop, ArithmeticVerifier]:
    """Build a loop whose policy uses the baseline the verifier actually measured."""
    recipe = HarnessHintRecipe(surface=surface, step=step)
    verifier = ArithmeticVerifier(surface=surface)
    baseline = verifier.baseline_pass_rate(scenario=SCENARIO)
    policy = EvidenceAdmissionPolicy(
        min_pass_rate=0.95,
        min_improvement=min_improvement,
        baseline_pass_rate=baseline,
    )
    loop = RecursiveLoop(
        substrate=substrate,
        recipe=recipe,
        verifier=verifier,
        policy=policy,
        ledger=ledger,
    )
    return loop, verifier


def test_full_turn_improves_and_publishes(rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger]) -> None:
    """One turn raises the hint, verifies it, and makes it live."""
    surface, substrate, ledger = rig
    loop, verifier = _loop(surface, substrate, ledger)

    before = verifier.baseline_pass_rate(scenario=SCENARIO)
    assert before is not None
    assert before < 0.5, "the baseline must be weak, or the improvement under test is invisible"

    receipt, body = loop.serve({"expression": "12*12", "expected": 144}, scenario=SCENARIO)
    assert body["correct"] is False
    assert loop.observe(Feedback(receipts=(receipt,), score=0.0), scenario=SCENARIO) is True

    candidate = loop.grow(scenario=SCENARIO)
    assert candidate is not None
    entry = loop.commit(candidate, scenario=SCENARIO)
    assert entry is not None

    assert entry.verdict is Verdict.ACCEPTED
    assert surface.current(scenario=SCENARIO) == candidate

    after = verifier.baseline_pass_rate(scenario=SCENARIO)
    assert after is not None
    assert after > before, "an accepted candidate must actually be live and better"


def test_serving_reflects_the_new_release_without_reconstruction(
    rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger],
) -> None:
    """A published release takes effect on the next request, with no restart.

    This is the property that makes the loop meaningful. A substrate that cached the
    prompt at construction would pass every other test here and still never reflect an
    update in production, so this failure mode gets its own test.
    """
    surface, substrate, ledger = rig
    loop, _ = _loop(surface, substrate, ledger)

    _, before = loop.serve({"expression": "12*12", "expected": 144}, scenario=SCENARIO)
    assert before["correct"] is False

    candidate = loop.grow(scenario=SCENARIO)
    assert candidate is not None
    loop.commit(candidate, scenario=SCENARIO)

    _, after = loop.serve({"expression": "12*12", "expected": 144}, scenario=SCENARIO)
    assert after["hint_length"] > before["hint_length"], "the substrate did not pick up the new release"


def test_nothing_publishes_without_evidence() -> None:
    """A candidate that passes every layer but has no baseline is inconclusive.

    The policy refuses rather than guessing, and the refusal is recorded, because a
    system that silently accepted here would have no way to explain the artifact later.

    The candidate must *pass* its layers for this test to isolate the missing baseline.
    A candidate that failed would be rejected on that ground first, which is a different
    and also correct verdict — the two are distinguished by which check fires.
    """
    repository = MemoryArtifactRepository()
    surface = MemorySurface(SurfaceKind.HARNESS, repository)
    strong = surface.stage(scenario=SCENARIO, files={PROMPT_PATH: render_prompt(2)})
    surface.publish(strong, scenario=SCENARIO)

    substrate = ArithmeticSubstrate(surface=surface)
    recipe = HarnessHintRecipe(surface=surface, step=1, max_hint=6)
    verifier = ArithmeticVerifier(surface=surface)
    ledger = MemoryLedger()
    loop = RecursiveLoop(
        substrate=substrate,
        recipe=recipe,
        verifier=verifier,
        policy=EvidenceAdmissionPolicy(baseline_pass_rate=None),
        ledger=ledger,
    )

    head = surface.current(scenario=SCENARIO)
    candidate = loop.grow(scenario=SCENARIO)
    assert candidate is not None
    entry = loop.commit(candidate, scenario=SCENARIO)

    assert entry is not None
    assert entry.verdict is Verdict.INCONCLUSIVE
    assert "baseline" in entry.reason
    assert surface.current(scenario=SCENARIO) == head, "an inconclusive candidate must not become live"
    assert len(ledger.entries(scenario=SCENARIO)) == 1, "the refusal must still be recorded"


def test_a_candidate_that_fails_its_layers_is_rejected_not_inconclusive() -> None:
    """A failing candidate is rejected on that ground, even with no baseline.

    Ordering matters here: completeness and failure are checked before performance,
    because a candidate that did not pass has no performance number worth comparing. A
    policy that asked for the baseline first would report INCONCLUSIVE and send an
    operator to re-run something that was already known to be broken.
    """
    repository = MemoryArtifactRepository()
    surface = MemorySurface(SurfaceKind.HARNESS, repository)
    weak = surface.stage(scenario=SCENARIO, files={PROMPT_PATH: render_prompt(0)})
    surface.publish(weak, scenario=SCENARIO)

    substrate = ArithmeticSubstrate(surface=surface)
    ledger = MemoryLedger()
    loop = RecursiveLoop(
        substrate=substrate,
        recipe=HarnessHintRecipe(surface=surface, step=1),
        verifier=ArithmeticVerifier(surface=surface),
        policy=EvidenceAdmissionPolicy(baseline_pass_rate=None),
        ledger=ledger,
    )

    candidate = loop.grow(scenario=SCENARIO)
    assert candidate is not None
    entry = loop.commit(candidate, scenario=SCENARIO)

    assert entry is not None
    assert entry.verdict is Verdict.REJECTED
    assert "failed at layers" in entry.reason


def test_a_rejected_candidate_leaves_the_live_artifact_untouched(
    rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger],
) -> None:
    """A candidate that fails is refused, and the release chain does not move.

    This is what makes a regression survivable: verification runs against a staged
    candidate, never against the live one.
    """
    surface, substrate, ledger = rig
    loop, verifier = _loop(surface, substrate, ledger, min_improvement=2.0)
    head = surface.current(scenario=SCENARIO)

    candidate = loop.grow(scenario=SCENARIO)
    assert candidate is not None
    entry = loop.commit(candidate, scenario=SCENARIO)

    assert entry is not None
    assert entry.verdict is Verdict.REJECTED
    assert surface.current(scenario=SCENARIO) == head
    assert verifier.baseline_pass_rate(scenario=SCENARIO) == verifier.baseline_pass_rate(scenario=SCENARIO)


def test_an_unrun_layer_is_not_reported_as_failed(
    rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger],
) -> None:
    """A contract failure leaves the behavior layer NOT_RUN, never FAILED.

    This is the misreport the ledger exists to prevent. Blaming a layer that never
    executed makes the attribution wrong, and a wrong attribution corrupts every later
    decision that reads the entry.
    """
    surface, substrate, _ = rig
    verifier = ArithmeticVerifier(surface=surface)

    broken = surface.stage(scenario=SCENARIO, files={PROMPT_PATH: "no hint declared here\n"})
    evidence = verifier.verify(broken, scenario=SCENARIO)

    by_layer = {result.layer: result.status for case in evidence.cases for result in case.layers}
    assert by_layer[LAYER_CONTRACT] is LayerStatus.FAILED
    assert by_layer[LAYER_BEHAVIOR] is LayerStatus.NOT_RUN
    assert LAYER_BEHAVIOR in evidence.not_run_layers()
    assert evidence.skipped_layers() == (), "a layer that did not run was not skipped; the two are distinct"


def test_a_malformed_prompt_is_refused_at_the_boundary(
    rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger],
) -> None:
    """A prompt with no parseable policy raises rather than defaulting.

    A silent default would let a run produce numbers under a policy nobody chose, and
    the ledger would then attribute them to an artifact that was never live.
    """
    surface, substrate, _ = rig
    broken = surface.stage(scenario=SCENARIO, files={PROMPT_PATH: "nothing useful\n"})
    surface.publish(broken, scenario=SCENARIO)

    with pytest.raises(ArtifactError, match="hint_length"):
        substrate.execute({"expression": "1+1", "expected": 2}, scenario=SCENARIO)


def test_serving_without_a_release_is_a_configuration_error() -> None:
    """A scenario with no released prompt cannot be served, and says so."""
    surface = MemorySurface(SurfaceKind.HARNESS, MemoryArtifactRepository())
    substrate = ArithmeticSubstrate(surface=surface)

    with pytest.raises(ArtifactError, match="no released prompt"):
        substrate.execute({"expression": "1+1", "expected": 2}, scenario=ScenarioId("never-released"))

    health = substrate.health(scenario=ScenarioId("never-released"))
    assert health["healthy"] is False
    assert "no released prompt" in str(health["problem"])


def test_health_is_per_scenario(rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger]) -> None:
    """Readiness is reported for the scenario asked about, not globally."""
    _, substrate, _ = rig
    assert substrate.health(scenario=SCENARIO)["healthy"] is True
    assert substrate.health(scenario=ScenarioId("other"))["healthy"] is False


def test_identical_content_still_produces_two_releases(
    rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger],
) -> None:
    """Proposing the same body twice yields two releases sharing one content id.

    *Proposed again* and *proposed once* are different histories. A repository that
    deduplicated them would make the ledger unable to tell a repeated attempt from a
    single one, which is exactly the record an operator needs when a change keeps
    being rejected.
    """
    surface, _, _ = rig
    files = {PROMPT_PATH: render_prompt(4)}

    first = surface.stage(scenario=SCENARIO, files=files)
    second = surface.stage(scenario=SCENARIO, files=files)

    assert first.content_id == second.content_id
    assert first.release_id != second.release_id


def test_release_chain_links_each_candidate_to_its_predecessor(
    rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger],
) -> None:
    """A staged candidate records the release it would replace, so rollback has a target."""
    surface, substrate, ledger = rig
    loop, _ = _loop(surface, substrate, ledger)
    head = surface.current(scenario=SCENARIO)
    assert head is not None

    candidate = loop.grow(scenario=SCENARIO)
    assert candidate is not None
    assert candidate.parent == head.release_id

    loop.commit(candidate, scenario=SCENARIO)
    rolled_back = surface.rollback(scenario=SCENARIO)
    assert rolled_back is not None
    assert rolled_back.release_id == head.release_id


def test_publishing_a_never_staged_reference_is_refused(
    rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger],
) -> None:
    """Publishing is only valid for a candidate that was actually stored.

    Without this check a fabricated reference could enter the release chain, and the
    ledger would record an accepted artifact whose body does not exist.
    """
    surface, _, _ = rig
    head = surface.current(scenario=SCENARIO)
    assert head is not None
    fabricated = surface.stage(scenario=SCENARIO, files={PROMPT_PATH: render_prompt(2)})

    other = MemorySurface(SurfaceKind.HARNESS, MemoryArtifactRepository())
    with pytest.raises(ArtifactError, match="never staged"):
        other.publish(fabricated, scenario=SCENARIO)


def test_a_reference_from_another_scenario_is_refused_by_name(
    rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger],
) -> None:
    """Cross-scenario reads report the isolation breach, not a missing artifact.

    The failure mode is worth naming precisely: a foreign reference looks valid, so
    without this check the symptom would be a confusing "not found" and the real problem
    — a broken isolation boundary — would go unnoticed.
    """
    surface, _, _ = rig
    repository = surface.repository()
    foreign = ScenarioId("other")

    ref = surface.stage(scenario=SCENARIO, files={PROMPT_PATH: render_prompt(2)})
    with pytest.raises(ArtifactError, match="belongs to scenario"):
        repository.materialize(ref, scenario=foreign)


def test_feedback_from_another_scenario_is_refused(
    rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger],
) -> None:
    """Feedback whose receipt belongs elsewhere is rejected, not applied.

    Accepting it would let one scenario's outcome move another's artifact, breaking
    isolation in a way that is very hard to notice after the fact.
    """
    surface, substrate, ledger = rig
    loop, _ = _loop(surface, substrate, ledger)
    receipt, _ = loop.serve({"expression": "1+1", "expected": 2}, scenario=SCENARIO)

    with pytest.raises(ValueError, match="belongs to scenario"):
        loop.observe(Feedback(receipts=(receipt,), score=0.0), scenario=ScenarioId("other"))


def test_a_recipe_that_exhausted_its_search_returns_none() -> None:
    """``None`` is an ordinary outcome, distinguishable from a failed attempt.

    The loop must be able to tell "nothing to propose" from "proposal failed": the first
    needs no ledger entry and the second does. The search space is exhausted by starting
    from a prompt that already reveals every digit of the widest expected answer.
    """
    repository = MemoryArtifactRepository()
    surface = MemorySurface(SurfaceKind.HARNESS, repository)
    widest = max(len(str(case.expected)) for case in ArithmeticVerifier(surface=surface).cases)
    maxed = surface.stage(scenario=SCENARIO, files={PROMPT_PATH: render_prompt(widest)})
    surface.publish(maxed, scenario=SCENARIO)

    ledger = MemoryLedger()
    loop, _ = _loop(surface, ArithmeticSubstrate(surface=surface), ledger)

    candidate = loop.grow(scenario=SCENARIO)
    assert candidate is None, "a recipe at the top of its range must report nothing to propose"
    assert loop.commit(candidate, scenario=SCENARIO) is None
    assert ledger.entries(scenario=SCENARIO) == ()


def test_delivering_twice_mints_two_runtime_loads(
    rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger],
) -> None:
    """Re-loading a release produces a new runtime identity, not the old one.

    The three artifact identities are separate for this reason: a restart must be
    visible, and reporting the previous load id would hide it.
    """
    surface, _, _ = rig
    head = surface.current(scenario=SCENARIO)
    assert head is not None

    first = surface.deliver(head, scenario=SCENARIO)
    second = surface.deliver(head, scenario=SCENARIO)
    assert first != second
    assert first.value.startswith(head.release_id.value)


def test_an_artifact_with_no_body_is_refused(rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger]) -> None:
    """A release with no body cannot be staged or verified, so it is refused on creation."""
    surface, _, _ = rig
    with pytest.raises(ArtifactError, match="files or payload"):
        surface.stage(scenario=SCENARIO)


def test_missing_artifact_reports_what_is_stored(
    rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger],
) -> None:
    """Reading an absent path names the paths that do exist."""
    surface, _, _ = rig
    repository = surface.repository()
    head = surface.current(scenario=SCENARIO)
    assert head is not None

    body = repository.materialize(head, scenario=SCENARIO)
    with pytest.raises(ArtifactError, match="no file"):
        body.text("does-not-exist.md")


def test_an_unknown_release_is_not_found(rig: tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger]) -> None:
    """A reference for a release that was never stored raises the specific error."""
    surface, _, _ = rig
    repository = surface.repository()
    head = surface.current(scenario=SCENARIO)
    assert head is not None

    from dataclasses import replace

    from rsihybridagent.core import ReleaseId

    ghost = replace(head, release_id=ReleaseId("harness-r999999"))
    with pytest.raises(ArtifactNotFound):
        repository.materialize(ghost, scenario=SCENARIO)
