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

"""The default admission policy, and the reasoning behind each of its checks.

The policy is the enforcement point for the project's central claim. It is written
as a sequence of named checks so a rejection can always cite one, and so an operator
can see exactly which bar a candidate missed.

Order matters. Completeness is checked before performance, because a candidate that
did not run every layer has no performance number worth comparing. Attribution is
checked before acceptance, because a correct-looking gain credited to the wrong layer
would corrupt every later decision that reads this entry.
"""

from __future__ import annotations

from dataclasses import dataclass

from rsihybridagent.core import Verdict
from rsihybridagent.ledger.base import AdmissionPolicy, Evidence


@dataclass(frozen=True)
class EvidenceAdmissionPolicy(AdmissionPolicy):
    """Accepts a candidate only when its evidence is complete, honest, and supportive.

    ``min_pass_rate`` is the fraction of cases that must pass every declared layer.
    ``min_improvement`` is how much better the candidate must be than its baseline
    before the gain is treated as real rather than noise. ``baseline_pass_rate`` is
    the measured rate of the artifact the candidate would replace; it is supplied by
    the verifier rather than assumed, so a candidate is never compared against a
    figure nobody measured.
    """

    min_pass_rate: float = 0.95
    min_improvement: float = 0.0
    baseline_pass_rate: float | None = None
    require_attribution: bool = True

    def decide(self, evidence: Evidence) -> tuple[Verdict, str]:
        """Return the verdict and the reason, in the order the checks are meaningful."""
        if not evidence.cases:
            return Verdict.INCONCLUSIVE, "no cases were verified; a candidate cannot be judged without instances"

        missing = evidence.missing_layers()
        if missing:
            return (
                Verdict.INCONCLUSIVE,
                f"declared layers produced no result: {', '.join(missing)}; "
                "an unrun layer is not a passed layer, so this run must be repeated",
            )

        unrun = evidence.not_run_layers()
        if unrun:
            return (
                Verdict.INCONCLUSIVE,
                f"declared layers reported no execution: {', '.join(unrun)}; "
                "an unrun layer is not a passed layer, so this run must be repeated",
            )

        skipped = evidence.skipped_layers()
        if skipped:
            return (
                Verdict.INCONCLUSIVE,
                f"declared layers were skipped: {', '.join(skipped)}; "
                "a skip must be resolved before the candidate is judged",
            )

        failed_cases = [case for case in evidence.cases if not case.all_layers_passed]
        if failed_cases:
            blamed = sorted({layer for case in failed_cases for layer in case.failing_layers()})
            return (
                Verdict.REJECTED,
                f"{len(failed_cases)}/{len(evidence.cases)} cases failed at layers: {', '.join(blamed)}",
            )

        if self.require_attribution and evidence.attribution is None:
            return (
                Verdict.INCONCLUSIVE,
                "the evidence records no attribution; without it a later regression cannot be traced "
                "to the layer that caused it",
            )

        pass_rate = evidence.pass_rate()
        if pass_rate < self.min_pass_rate:
            return (
                Verdict.REJECTED,
                f"pass rate {pass_rate:.3f} is below the required {self.min_pass_rate:.3f}",
            )

        if self.baseline_pass_rate is None:
            return (
                Verdict.INCONCLUSIVE,
                "no baseline was measured, so the candidate's gain cannot be separated from noise",
            )

        improvement = pass_rate - self.baseline_pass_rate
        if improvement < self.min_improvement:
            return (
                Verdict.REJECTED,
                f"improvement {improvement:+.3f} is below the required {self.min_improvement:+.3f}; "
                "a gain this small is not distinguishable from noise",
            )

        return (
            Verdict.ACCEPTED,
            f"all {len(evidence.cases)} cases passed every declared layer, "
            f"improvement {improvement:+.3f} over baseline, attributed to {evidence.attribution!r}",
        )
