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

"""A complete, runnable turn of the loop, on CPU, in under a second.

Run it with::

    PYTHONPATH=src python examples/arithmetic_loop.py

It prints one turn end to end: a weak baseline, a rejected candidate, then an accepted
one. The rejection is the point. A demo that only showed an acceptance would suggest the
ledger is a formality; the second turn is where it does its job.

Nothing here needs a GPU, a simulator, or a network. That is deliberate: the evidence
ledger is the project's central claim, and a claim that can only be exercised on a
machine nobody has is a claim nobody has tested.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rsihybridagent.core import Feedback, ScenarioId, SurfaceKind, Verdict
from rsihybridagent.ledger.memory import MemoryLedger
from rsihybridagent.ledger.policy import EvidenceAdmissionPolicy
from rsihybridagent.loop import RecursiveLoop
from rsihybridagent.recipes.harness_hint import ArithmeticVerifier, HarnessHintRecipe
from rsihybridagent.substrate.arithmetic import PROMPT_PATH, ArithmeticSubstrate, render_prompt
from rsihybridagent.surfaces.memory import MemoryArtifactRepository, MemorySurface

SCENARIO = ScenarioId("arithmetic-demo")
WIDTH = 44


def rule(title: str) -> None:
    """Print a section heading."""
    print(f"\n{title}\n{'-' * WIDTH}")


def build() -> tuple[MemorySurface, ArithmeticSubstrate, MemoryLedger]:
    """Release a deliberately weak baseline and wire the collaborators."""
    repository = MemoryArtifactRepository()
    surface = MemorySurface(SurfaceKind.HARNESS, repository)

    baseline = surface.stage(scenario=SCENARIO, files={PROMPT_PATH: render_prompt(1)})
    surface.publish(baseline, scenario=SCENARIO)

    return surface, ArithmeticSubstrate(surface=surface), MemoryLedger()


def loop_for(
    surface: MemorySurface,
    substrate: ArithmeticSubstrate,
    ledger: MemoryLedger,
    *,
    step: int,
    min_improvement: float,
) -> tuple[RecursiveLoop, ArithmeticVerifier]:
    """Build a loop whose policy uses the baseline the verifier actually measured."""
    verifier = ArithmeticVerifier(surface=surface)
    baseline = verifier.baseline_pass_rate(scenario=SCENARIO)
    policy = EvidenceAdmissionPolicy(
        min_pass_rate=0.95,
        min_improvement=min_improvement,
        baseline_pass_rate=baseline,
    )
    return (
        RecursiveLoop(
            substrate=substrate,
            recipe=HarnessHintRecipe(surface=surface, step=step),
            verifier=verifier,
            policy=policy,
            ledger=ledger,
        ),
        verifier,
    )


def turn(loop: RecursiveLoop, surface: MemorySurface, label: str) -> None:
    """Run one full turn and report what each step did."""
    rule(f"{label}: serve, observe, grow, commit")

    receipt, body = loop.serve({"expression": "12*12", "expected": 144}, scenario=SCENARIO)
    print(f"serve    expression=12*12 answer={body['answer']} correct={body['correct']}")

    eligible = loop.observe(Feedback(receipts=(receipt,), score=0.0), scenario=SCENARIO)
    print(f"observe  eligible={eligible}")

    candidate = loop.grow(scenario=SCENARIO)
    if candidate is None:
        print("grow     nothing to propose")
        return
    meta = dict(candidate.metadata)
    print(f"grow     {candidate.release_id.value}  hint {meta.get('from_hint')} -> {meta.get('to_hint')}")

    entry = loop.commit(candidate, scenario=SCENARIO)
    assert entry is not None
    print(f"commit   verdict={entry.verdict.value}")
    print(f"         reason: {entry.reason}")

    live = surface.current(scenario=SCENARIO)
    assert live is not None
    print(f"live     {live.release_id.value}")

    _, after = loop.serve({"expression": "12*12", "expected": 144}, scenario=SCENARIO)
    print(f"serve    answer={after['answer']} correct={after['correct']}  (no restart needed)")


def main() -> int:
    """Run two turns: one the policy rejects, one it accepts."""
    surface, substrate, ledger = build()

    print("rsihybridagent — one complete turn of the recursive loop")
    print(f"scenario {SCENARIO.name!r}, {len(ArithmeticVerifier(surface=surface).cases)} verification cases")

    loop, verifier = loop_for(surface, substrate, ledger, step=2, min_improvement=2.0)
    baseline = verifier.baseline_pass_rate(scenario=SCENARIO)
    print(f"baseline pass rate = {baseline:.3f}")
    turn(loop, surface, "turn 1 — an implausible bar")

    rule("the ledger after turn 1")
    for entry in ledger.entries(scenario=SCENARIO):
        print(f"{entry.entry_id}  {entry.verdict.value}")

    loop, verifier = loop_for(surface, substrate, ledger, step=2, min_improvement=0.0)
    turn(loop, surface, "turn 2 — a bar the gain can clear")

    rule("the ledger after turn 2")
    for entry in ledger.entries(scenario=SCENARIO):
        marker = "accepted" if entry.verdict is Verdict.ACCEPTED else entry.verdict.value
        print(f"{entry.entry_id}  {marker}")

    accepted = ledger.accepted_chain(scenario=SCENARIO)
    print(f"\nrelease chain: {' -> '.join(ref.release_id.value for ref in accepted)}")
    print(f"entries: {len(ledger.entries(scenario=SCENARIO))}  (a rejection is recorded too)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
