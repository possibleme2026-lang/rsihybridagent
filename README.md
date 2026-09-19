<div align="center">

# rsihybridagent

**Recursive Self-Improvement for Hybrid Agents**

Digital and physical experience improving each other · every self-improvement must leave checkable evidence

[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB)](pyproject.toml)
[![Status](https://img.shields.io/badge/status-design--stage-orange)]()
[![CI](https://github.com/possibleme2026-lang/rsihybridagent/actions/workflows/ci.yml/badge.svg)](https://github.com/possibleme2026-lang/rsihybridagent/actions/workflows/ci.yml)

English | [简体中文](README.zh-CN.md)

</div>

---

## In one sentence

**rsihybridagent is a self-improvement framework in which a digital agent and a physical robot feed experience to each other — and it refuses to call any improvement successful without evidence that can be checked.**

---

## Why it is needed

Existing work is split in two, and each half is incomplete:

| Current form | Examples | Has | Missing |
|---|---|---|---|
| Digital self-improvement infrastructure | reef, cordis | A complete inference → feedback → learning → versioned-delivery loop | **No body.** No physical-side concept at all |
| Physical agentic frameworks | RPent, openpi | An LLM planner plus frozen-VLA manipulation | **No learning loop.** No gradient update anywhere in the repository |
| Embodied RL training | RLinf, slime | The ability to train VLA weights | **No harness evolution surface**, and no hybrid tasks |

The claim of rsihybridagent is that **these halves cannot be independent. They must interlock.**

Concretely, four points of engagement (see the [architecture document](docs/architecture.md)):

1. **Digital → physical**: a skill evolved on the digital side raises physical task success without retraining the VLA
2. **Physical → digital**: a failure pattern observed on the physical side becomes a constraint the planner reads, changing its decisions
3. **Physical → weights**: successful physical trajectories become VLA training data
4. **Digital → weights**: a stronger digital world model produces better primitive decompositions, yielding cleaner data

---

## Three principles we do not compromise on

### 1. Evidence Ledger — no self-improvement without checkable evidence

This is the project's **central differentiator**, and it comes from a hard lesson learned in embodied benchmark work.

The dominant failure mode of a self-improving system is not failing to learn. It is **believing it learned**:

- A layer that never ran is recorded as having passed → vacuous pass
- A layer that failed is recorded as skipped → the failure is hidden
- A measured gain comes from noise rather than capability → false progress

rsihybridagent requires **every improvement to carry a checkable evidence record**:

```
one improvement = one change + one piece of evidence + one attribution
```

- **Change**: which surface was modified (weights / harness / memory)
- **Evidence**: which instances, which seeds, verified at which layers — **with each layer's status recorded explicitly**
- **Attribution**: which layer this gain or regression is **attributed to**. A misattributed record is a failure

An improvement without evidence is not allowed to commit. **A layer that did not run and a layer that ran and failed must be recorded separately** — this is a hard constraint.

### 2. Substrate Separation — the physical side does not depend on the agent side's GPU

The digital and physical sides are **separate processes** communicating over RPC. The agent process does not import torch.

The reason is practical: on an 8 GB laptop GPU, agent inference and physical simulation running together will OOM. Separating them means:

- The agent side runs on CPU
- The physical side runs on a GPU machine or a remote cluster
- One side crashing does not compromise the other's record integrity

### 3. Version Everything — rollback, A/B comparison, reproducibility

The object of self-improvement is a **versioned artifact**, not "the current state". Every artifact has three identities that must be tracked separately:

- `content_id`: a fingerprint of the content (identical content always shares one)
- `release_id`: one published version (one commit produces one)
- `runtime_load_id`: the instance actually loaded by a running service (differs from the release after a hot swap)

Conflating these three is the hardest bug class to diagnose in a self-improving system.

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│  Interlock Layer    Four points of engagement: digital ↔      │
│                     physical ↔ weights, feeding both ways     │
├─────────────────────────────────────────────────────────────┤
│  Recursive Loop     Serve → Observe → Grow → Commit          │
├─────────────────────────────────────────────────────────────┤
│  Surfaces           weights · harness · memory               │
├─────────────────────────────────────────────────────────────┤
│  Substrate          Digital Substrate │ Physical Substrate    │
├─────────────────────────────────────────────────────────────┤
│  Evidence Ledger    Evidence and attribution across all four  │
│                     layers (cross-cutting concern)            │
└─────────────────────────────────────────────────────────────┘
```

The five layers' responsibility boundaries, interface contracts, and data flow are in **[docs/architecture.md](docs/architecture.md)**.

---

## Core abstractions

The framework binds to no specific LLM, VLA, simulator, or training backend. Four extension points:

| Abstraction | Responsibility | Corresponding existing implementations |
|---|---|---|
| `Substrate` | Execution base (digital or physical) | Containers / sandboxes · LIBERO/RoboCasa/real robot |
| `Surface` | Evolvable artifact family | Weights · prompt/rules/skills · memory |
| `Recipe` | How an update is produced from records | SAO/GRPO · harness editing · memory merging |
| `Ledger` | Evidence and attribution | Layered verifiers · failure attribution |

Full signatures for these abstractions — and for the seven registration groups that
supply them — are in **[docs/interfaces.md](docs/interfaces.md)**, which is checked
against the real code on every run.

---

## Integrating your own system

The framework supplies release chains, the artifact repository, the ledger, the admission policy, the loop's ordering guarantees, and scenario isolation. **You supply five things**, and the total is under sixty lines:

| # | What you write | Where it goes |
|---|---|---|
| 1 | The policy/prompt format your system reads | a render function beside its parser |
| 2 | `execute` — the call into your system | `Substrate.execute` |
| 3 | `health` — how you decide readiness | `Substrate.health` |
| 4 | Scoring | `Verifier` |
| 5 | How the next candidate is generated | `Recipe` |

A complete, runnable template is in **[examples/custom_substrate.py](examples/custom_substrate.py)**. Run it:

```bash
PYTHONPATH=src python examples/custom_substrate.py
```

It wires a threshold classifier end to end and prints one turn: a baseline that mislabels half the samples, a proposal, and an acceptance — after which the same input that was wrong is right, with no restart.

### 1. Declare your implementation

Either register it in-process, or let a package declare it in its own `pyproject.toml`:

```python
from rsihybridagent import ExtensionPoint, register

register(ExtensionPoint.SUBSTRATE, "my-system", MySubstrate(...))
```

```toml
[project.entry-points."rsihybridagent.substrates"]
my-system = "my_pkg.substrates:MySubstrate"
```

The entry-point route is the one that survives into someone else's environment, which is what makes it the mechanism that matters. **Your package does not import this project to declare itself**, and this project does not need to know your package exists.

### 2. Implement the substrate

Two of the five points live here. The marked lines are the only ones you replace:

```python
class MySubstrate(Substrate):
    def kind(self) -> SubstrateKind:
        return SubstrateKind.DIGITAL

    def execute(self, request, *, scenario):
        policy = self._current_policy(scenario)          # read the live release
        result = my_system.run(request, policy)          # <-- YOUR CALL
        receipt = Receipt(value=f"{scenario.name}-{n}", scenario=scenario)
        return receipt, result

    def health(self, *, scenario):
        return {"healthy": self._reachable(scenario), "problem": None}
```

**Read the policy on every call, do not cache it at construction.** That is what makes an accepted improvement take effect on the next request. A substrate that cached it would pass every test and never reflect an update in production.

**`health` takes a scenario.** Readiness is not global: a substrate whose policy was never released for a scenario is not ready for that scenario. There is no argument-free version, because it could only report the global half and would call a misconfigured scenario healthy.

If your system is a separate process or a remote machine, `execute` is where the RPC happens and nothing else in the file changes. That is what keeps the agent side on CPU while the physical side holds the GPU.

### 3. Implement the verifier

Declare your layers **before** any run starts. That is what lets the ledger notice a layer that never ran:

```python
class MyVerifier(Verifier):
    def declared_layers(self) -> tuple[str, ...]:
        return ("contract", "behavior")

    def verify(self, candidate, *, scenario) -> Evidence:
        cases = self._score(candidate, scenario=scenario)
        baseline = self.surface.current(scenario=scenario)
        return Evidence(
            scenario=scenario,
            candidate=candidate,
            baseline=baseline,
            cases=cases,
            declared_layers=self.declared_layers(),
            attribution="behavior",
        )
```

Two rules the framework relies on, both enforced by the ledger:

- **Measure the baseline yourself.** Supplying a baseline figure from the recipe would let the party that produced the change also supply the number used to judge it.
- **Report a layer that did not run as `NOT_RUN`, never as `FAILED`.** When a contract check short-circuits, the behavior layer did not execute; calling it failed blames a layer that never ran, and a wrong attribution corrupts every later decision that reads the entry.

### 4. Implement the recipe

```python
class MyRecipe(Recipe):
    def target_surface(self) -> Surface:
        return self.surface

    def eligible(self, receipts, feedback, *, scenario) -> bool:
        return feedback.score is not None and feedback.score < 0.95

    def propose(self, *, scenario):
        return self.surface.stage(scenario=scenario, files={...})   # or None
```

**Return `None` when there is nothing to propose.** That is an ordinary outcome, not an error, and the loop treats it as one: no candidate means no ledger entry. A recipe that exhausted its range must be distinguishable from one that tried and failed.

### 5. Wire it together

```python
loop = RecursiveLoop(
    substrate=MySubstrate(...),
    recipe=MyRecipe(...),
    verifier=MyVerifier(...),
    policy=EvidenceAdmissionPolicy(baseline_pass_rate=measured),
    ledger=MemoryLedger(),
)

receipt, result = loop.serve(request, scenario=scenario)   # 1. run
loop.observe(Feedback(receipts=(receipt,), score=0.0), scenario=scenario)  # 2. is there signal?
candidate = loop.grow(scenario=scenario)                    # 3. produce a candidate
entry = loop.commit(candidate, scenario=scenario)           # 4. verify, decide, publish
```

`commit` publishes **only** on `ACCEPTED`, and appends a ledger entry whatever the verdict — a rejection is as auditable as an acceptance.

### Four things that will bite you

| Symptom | Cause | Fix |
|---|---|---|
| `TypeError: Can't instantiate abstract class ... without an implementation for abstract method` | You used `@property @abstractmethod` and tried to satisfy it with a dataclass field | Use a method. A field of the same name becomes a class attribute holding a descriptor, so the subclass stays abstract and the message names a method it visibly defines |
| `mypy` rejects your surface, but every test passes | The implementation duck-types the base instead of inheriting it | Inherit explicitly. Runtime checks cannot see the difference; the type checker can |
| Your candidate is never accepted, reason mentions the baseline | Nothing was released for the scenario, so the policy has no baseline to compare against | Publish a baseline first |
| A cross-scenario read raises "not found" instead of naming the scenario | You are reading through a different scenario than the one that stored the artifact | Pass the same `ScenarioId`. Scenarios never share a release chain, and the error names the owning scenario when it can |

---

### Plugging in without forking

An interface nobody can discover is not an open interface, it is just an abstract class. A package supplies an implementation by declaring it in its **own** packaging metadata, and this project never needs to know about it:

```toml
[project.entry-points."rsihybridagent.substrates"]
libero = "my_pkg.substrates:LiberoSubstrate"
```

Seven groups are recognized, each with a contract its members must satisfy:

| Group | Must implement |
|---|---|
| `rsihybridagent.substrates` | `Substrate` |
| `rsihybridagent.surfaces` | `Surface` |
| `rsihybridagent.recipes` | `Recipe` |
| `rsihybridagent.verifiers` | `Verifier` |
| `rsihybridagent.policies` | `AdmissionPolicy` |
| `rsihybridagent.ledgers` | `Ledger` |
| `rsihybridagent.interlock` | `InterlockPort` |

The value may be the implementation itself or a zero-argument callable returning one. A value that does not satisfy its group's contract is **refused at resolution**, not at a later call site where the traceback would point at the wrong layer.

```bash
rsihybrid extensions                                          # what is installed, and what each group requires
rsihybrid extensions rsihybridagent.recipes                   # one group only
rsihybrid check rsihybridagent.substrates my_pkg.sub:Thing    # resolve one and report whether it conforms
```

`check` takes the **full group name**, not a short one, and prints the type it actually
resolved so that "I configured X" and "Y was loaded" can be compared directly.

---

## Status

**The loop runs end to end on CPU.** Both examples below complete a full turn — serve, observe, grow, commit — in under a second.

- ✅ Architecture design and interface contracts (`docs/`)
- ✅ Extension registry, so a third-party backend plugs in without forking
- ✅ A runnable reference implementation: substrate, surface, repository, recipe, verifier, policy, ledger
- ✅ An integration template you can copy: **[examples/custom_substrate.py](examples/custom_substrate.py)**
- ✅ End-to-end validation on deterministic tasks (140 tests)
- ✅ Docs that are checked against the code: `docs/interfaces.md` is compared with the
  real signatures on every run, so it cannot drift the way it did once already
- ⬜ A physical substrate (simulator or robot)
- ⬜ The four interlock channels implemented — they are contracts today, not code
- ⬜ Durable artifact storage and a durable ledger

```bash
PYTHONPATH=src python examples/arithmetic_loop.py     # the loop, with a rejection and an acceptance
PYTHONPATH=src python examples/custom_substrate.py    # how to attach your own system
```

**Two prerequisites that must be stated plainly.**

The full service depends on POSIX process-group semantics (`os.killpg` / `os.setsid` / `fcntl`), so it **does not run on native Windows**; use WSL2 or a Linux container. The core abstractions, the reference implementation, and the test suite do run on Windows.

The reference substrate is a **toy**. It answers arithmetic questions so that the ledger can be exercised deterministically — a gain there is real or absent, never statistical. It is not a benchmark, and its scores say nothing about any model.

---

## Relationship to existing projects

rsihybridagent builds on two excellent open-source projects, and states its increment explicitly:

| Project | License | Borrowed by rsihybridagent | Added by rsihybridagent |
|---|---|---|---|
| [reef](https://github.com/Human-Agent-Society/reef) | Apache-2.0 | The four-step loop; recipe/surface/runtime abstraction; the artifact release chain | Physical substrate, evidence ledger, interlock layer |
| [RPent](https://github.com/RLinf/RPent) | Apache-2.0 | Physical-side RPC decoupling; the memory schema; the planner adapter | The learning loop, weight feedback, cross-environment memory |

**Integrate, do not fork.** The physical side arrives as an independent recipe, adapter, and runtime backend so it can follow upstream changes rather than diverge from them.

The full list of influences, paper citations, and license-compliance notes are in **[References](#references)**.

### How to cite this project

```bibtex
@misc{rsihybridagent2026,
  title={rsihybridagent: Recursive Self-Improvement for Hybrid Agents},
  author={{The rsihybridagent Authors}},
  year={2026},
  howpublished={\url{https://github.com/possibleme2026-lang/rsihybridagent}},
  note={Digital and physical experience improving each other, with an evidence ledger that refuses unverified progress}
}
```

---

## Quick start

> The full service needs a Linux environment (WSL2 or a container). The core abstractions and the evidence ledger run on CPU.

```bash
git clone https://github.com/possibleme2026-lang/rsihybridagent && cd rsihybridagent
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"

pytest -q
rsihybrid channels
```

---

## References

### 1. Projects this work builds on

The following open-source projects form the architectural basis of this work. All are Apache-2.0 and license-compatible with this project.

**[reef](https://github.com/Human-Agent-Society/reef)** · Apache-2.0 · PyPI `reef-infra`

Continual-learning infrastructure for self-improving agents. This project borrows:

- The division of the four-step loop (Serve → Observe → Grow → Commit)
- The recipe / surface / runtime three-layer abstraction, and the boundary discipline that keeps shared mechanisms in the package while method-specific policy stays outside it
- The artifact release chain, and the separation of the three artifact identities
- The receipt mechanism (a handle for one interaction, used to link feedback back to its record)

**[RPent](https://github.com/RLinf/RPent)** · Apache-2.0 · PyPI `rpent`

An agentic framework for the physical world (planner + frozen VLA + simulator/real robot). This project borrows:

- The fully decoupled physical-side RPC design (`--env-endpoint` / `--vla-endpoint` let the agent process avoid importing torch)
- The memory schema of Markdown plus YAML frontmatter (`scope` / `kind` / `confidence` / `evidence`)
- The planner adapter layer and dynamic robot discovery

**[cordis](https://github.com/cordiverse/cordis)** · Apache-2.0

The harness composition and evolution engine. reef's harness evolution surface is built on it.

**[Slime](https://github.com/THUDM/slime)** · Apache-2.0 · **[SGLang](https://github.com/sgl-project/sglang)** · Apache-2.0

Model weight training and high-performance inference, forming the training and serving system for the weights surface.

### 2. Paper citations

The physical-side design of this project draws on the central finding of **Harness VLA** — that a memory-guided agent makes a frozen VLA substantially stronger. This is the basis for claiming that physical task success can improve without retraining weights:

```bibtex
@article{zhang2026harnessvla,
  title={Harness VLA: Steering Frozen VLAs into Reliable Manipulation Primitives via Memory-Guided Agents},
  author={Zhang, Yixian and Zhang, Huanming and Gao, Feng and Li, Xiao and Liu, Zhihao and Zhu, Chunyang
          and Qiu, Jiaxing and Yan, Yuchen and Liu, Jiyuan and Tang, Wenhao and Fang, Zhengru and Nie, Yi
          and Wei, Changxu and Wang, Yu and Ding, Wenbo and Yu, Chao},
  journal={arXiv preprint arXiv:2607.08448},
  year={2026},
  url={https://arxiv.org/abs/2607.08448}
}
```

### 3. Origin of the design ideas

**Honest accounting in layered verification** — this project's central claim that *not run* is neither *failed* nor *skipped* — comes from embodied benchmark engineering practice, not from a paper. Its reference implementation and the pitfalls encountered are recorded in the Harbor task `terminal-bench-science/hybrid-lab-quarantine` in `hybrid-embodied-bench`.

That task's three verification layers (data / controller / embodied) surfaced a real bug during integration testing: the grader wrote one layer's skip into its failure field, making one variant appear to have "failed two layers". That lesson directly produced this project's `LayerStatus` design.

**Task format** follows [Harbor](https://github.com/laude-institute/harbor) / Terminal-Bench.

### 4. License compliance

This project is released under Apache-2.0. Its use of the projects above is **architectural inspiration and interface integration; no source code was copied**.

Should a later version reuse any code directly, the original copyright notice will be retained, the source will be recorded in `NOTICE`, and the requirements of Apache-2.0 section 4 for derivative works will be observed.

This project is an independent implementation. It is not affiliated with, and has not been endorsed by, any of the projects above.

---

## License

Apache-2.0. See [LICENSE](LICENSE).
