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

"""A digital substrate that answers arithmetic questions from a versioned prompt.

This is a *toy*, and it is here on purpose. An interface that has never been
implemented is a guess, and the cheapest way to falsify a guess is to implement the
smallest thing that must satisfy it. A harness surface, a recipe, a verifier, and an
admission policy all have to work together for this substrate to produce a single
accepted improvement, and every one of them is exercised on CPU in milliseconds.

**What it is not.** It is not a benchmark, and its scores mean nothing about any model.
The task is deterministic so that the evidence ledger can be tested without a sampling
distribution: a gain here is real or absent, never statistical. Noise handling is the
verifier's job to express, not this substrate's.

The substrate holds no artifact. It reads the harness surface's current release at
execution time, which is what makes a published improvement take effect on the next
request without restarting anything. A substrate that cached the prompt at construction
would pass its own tests and still never reflect an update in production.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rsihybridagent.artifact import ArtifactError
from rsihybridagent.core import Receipt, ScenarioId, Substrate, SubstrateKind, Surface

#: The prompt file the harness surface must contain. A substrate names the files it
#: reads, so a surface missing one fails at the boundary that needs it rather than
#: inside a model call where the cause is far from the symptom.
PROMPT_PATH = "prompt.md"

#: Operations the toy evaluator accepts. A fixed allowlist keeps the substrate from
#: being an arbitrary-code-execution hole, which a ``eval`` here would be.
_OPS: Mapping[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
}


@dataclass(frozen=True)
class ArithmeticRequest:
    """One question: an expression, and the answer it should produce."""

    expression: str
    expected: int


class ArithmeticSubstrate(Substrate):
    """Answers arithmetic expressions, guided by the harness surface's live prompt.

    The prompt is interpreted as a small policy, not as natural language: it states how
    many of the trailing characters of the expected answer to reveal as a hint. A
    longer hint makes the task easier, which gives a recipe a real thing to tune and
    gives the ledger a real improvement to accept or refuse.
    """

    def __init__(self, *, surface: Surface, healthy: bool = True) -> None:
        self._surface = surface
        self._healthy = healthy
        self._served = 0

    def kind(self) -> SubstrateKind:
        """This is a digital substrate: no robot, no simulator."""
        return SubstrateKind.DIGITAL

    def execute(self, request: Mapping[str, Any], *, scenario: ScenarioId) -> tuple[Receipt, Mapping[str, Any]]:
        """Answer one question using the prompt currently released for the scenario.

        The prompt is read per call, so a release that lands mid-run affects the next
        request. That is the property that makes the loop meaningful: without it,
        committing an improvement would change nothing an operator could observe.
        """
        expression = str(request.get("expression", ""))
        expected = int(request.get("expected", 0))

        hint_length = self._hint_length(scenario)
        answer = self._answer(expression, expected, hint_length)

        self._served += 1
        receipt = Receipt(value=f"{scenario.name}-{self._served:04d}", scenario=scenario)
        return receipt, {
            "expression": expression,
            "expected": expected,
            "answer": answer,
            "correct": answer == expected,
            "hint_length": hint_length,
        }

    def health(self, *, scenario: ScenarioId) -> Mapping[str, Any]:
        """Report readiness for one scenario, including whether it has a prompt.

        The check is per scenario because readiness is per scenario: a substrate whose
        policy was never released for a scenario cannot serve it, and a global answer
        would call that state healthy.
        """
        problem: str | None = None
        if not self._healthy:
            problem = "substrate was constructed unhealthy"
        elif self._surface.current(scenario=scenario) is None:
            problem = f"scenario {scenario.name!r} has no released prompt"
        return {
            "healthy": problem is None,
            "kind": self.kind().value,
            "problem": problem,
            "served": self._served,
        }

    def _hint_length(self, scenario: ScenarioId) -> int:
        """Read the hint length from the released prompt.

        A scenario with no release yet is a configuration error rather than a default:
        falling back silently would let a run produce numbers under a policy nobody
        chose, and the ledger would then attribute them to an artifact that was never
        live.
        """
        head = self._surface.current(scenario=scenario)
        if head is None:
            raise ArtifactError(
                f"scenario {scenario.name!r} has no released prompt; "
                "stage and publish one before serving, or the run has no policy to follow"
            )
        artifact = self._surface.repository().materialize(head, scenario=scenario)
        return _parse_hint_length(artifact.text(PROMPT_PATH))

    @staticmethod
    def _answer(expression: str, expected: int, hint_length: int) -> int:
        """Produce an answer whose accuracy depends on how much the hint reveals.

        The toy model is deliberately literal: it reveals the trailing digits of the
        true answer up to ``hint_length``, and guesses zero for the rest. Accuracy is
        therefore a monotone function of the hint, which makes an improvement
        measurable without any sampling.
        """
        if hint_length <= 0:
            return 0
        text = str(abs(expected))
        if hint_length >= len(text):
            return expected
        revealed = text[-hint_length:]
        return int(revealed) if revealed.isdigit() else 0


def render_prompt(hint_length: int) -> str:
    """Render a prompt declaring the given hint length.

    Lives beside the parser because the substrate owns the prompt format. A recipe that
    rendered its own version of this text could drift from what the parser accepts, and
    the failure would appear as a contract failure blamed on the wrong party.
    """
    if hint_length < 0:
        raise ArtifactError(f"cannot render a prompt with a negative hint_length ({hint_length})")
    return (
        "# Arithmetic policy\n"
        "#\n"
        "# hint_length: how many trailing digits of the expected answer are revealed.\n"
        "# A larger value reveals more, making the task easier.\n"
        f"hint_length: {hint_length}\n"
    )


def _parse_hint_length(prompt: str) -> int:
    """Read ``hint_length: N`` out of the prompt, refusing an unparseable policy.

    The prompt is a file an evolution step may rewrite, so it is untrusted input at
    this boundary. Parsing it strictly means a malformed edit surfaces as a clear
    error here instead of as silently wrong scores attributed to the wrong layer.
    """
    for raw in prompt.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if sep and key.strip() == "hint_length":
            try:
                parsed = int(value.strip())
            except ValueError as exc:
                raise ArtifactError(
                    f"prompt declares hint_length as {value.strip()!r}, which is not an integer"
                ) from exc
            if parsed < 0:
                raise ArtifactError(f"prompt declares a negative hint_length ({parsed})")
            return parsed
    raise ArtifactError(
        f"prompt has no 'hint_length' declaration; the substrate has no policy to follow. "
        f"Expected a line like 'hint_length: 3' in {PROMPT_PATH}"
    )


def evaluate(expression: str) -> int:
    """Evaluate a ``+``/``-``/``*`` expression over integers, safely.

    Exposed for tests and for generating fixtures. It is not on the serving path: the
    substrate compares against a supplied ``expected`` rather than computing it, so a
    wrong expectation in a fixture shows up as a failed case rather than being papered
    over by the evaluator agreeing with itself.
    """
    tree = ast.parse(expression, mode="eval")
    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> int:
    """Walk an allowlisted arithmetic tree, refusing anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return int(_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right)))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand)
    raise ValueError(f"unsupported expression node: {type(node).__name__}")
