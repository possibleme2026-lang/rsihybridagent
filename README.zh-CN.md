<div align="center">

# rsihybridagent

**面向混合 agent 的递归自进化**

**Recursive Self-Improvement for Hybrid Agents**

数字经验与物理经验互相进化 · 每一次自进化都必须留下可复核的物证

[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB)](pyproject.toml)
[![Status](https://img.shields.io/badge/status-design--stage-orange)]()
[![CI](https://github.com/possibleme2026-lang/rsihybridagent/actions/workflows/ci.yml/badge.svg)](https://github.com/possibleme2026-lang/rsihybridagent/actions/workflows/ci.yml)

[English](README.md) | 简体中文

</div>

---

## 一句话

**rsihybridagent 是一个让「数字侧 agent」与「物理侧机器人」互相喂养经验的自进化框架，并且它拒绝在没有物证的情况下宣布任何一次进化成功。**

---

## 为什么需要它

现有工作分成两半，各自都不完整：

| 现有形态 | 代表 | 有什么 | 缺什么 |
|---|---|---|---|
| 数字自进化基础设施 | reef、cordis | 完整的「推理→反馈→学习→版本化交付」闭环 | **没有身体**。物理侧概念零命中 |
| 物理 agentic 框架 | RPent、openpi | LLM planner + 冻结 VLA 的操作能力 | **没有学习闭环**。全仓无梯度更新 |
| 具身 RL 训练 | RLinf、slime | 能训 VLA 权重 | **没有 harness 进化面**，也没有混合任务 |

rsihybridagent 的主张是：**这两半不是可以各自独立的，它们必须互锁。**

具体地说，四个咬合点（详见[架构文档](docs/architecture.md)）：

1. **数字 → 物理**：数字侧进化出的 skill，无需重训 VLA 就能提升物理任务成功率
2. **物理 → 数字**：物理侧的失败模式，变成数字侧的约束条目，改变 planner 决策
3. **物理 → 权重**：物理侧的成功轨迹，成为 VLA 的训练数据
4. **数字 → 权重**：数字侧的世界模型变强，生成更好的 primitive 分解，喂出更干净的数据

---

## 三个不妥协的设计原则

### 1. 物证台账（Evidence Ledger）—— 不接受无物证的自进化

这是本项目**最核心的差异化**，也是从具身 benchmark 实践中得到的硬教训。

自进化系统最大的失败模式不是「学不会」，而是**「以为自己学会了」**：

- 验证器里「没跑」被记成了「跑过了」→ 空过（vacuous pass）
- 「跑失败」被记成了「跳过」→ 失败被隐藏
- 进化的收益来自噪声而非真实能力提升 → 虚假进步

rsihybridagent 要求**每一次进化都必须附带一条可复核的物证记录**：

```
一次进化 = 一个变更 + 一份物证 + 一个归因
```

- **变更**：改了哪个 surface（权重 / harness / memory）
- **物证**：哪些实例、哪些种子、哪个层级上验证过，**显式记录每层的状态**
- **归因**：这次进步/退步**归因到哪一层**。归因错的记录判定为失败

没有物证的进化不允许 commit。**每层的「未运行」与「运行失败」必须分开记录**，这是硬约束。

### 2. 双基底分离（Substrate Separation）—— 物理侧不依赖 agent 侧的 GPU

数字侧和物理侧是**独立进程**，通过 RPC 通信。agent 进程不 import torch。

理由很实际：8GB 显存的笔记本上，agent 推理和物理仿真同时跑必然 OOM。分离后可以：

- agent 侧跑在 CPU（本机可跑）
- 物理侧跑在 GPU 机器或远程集群
- 一侧崩溃不影响另一侧的记录完整性

### 3. 版本化一切（Version Everything）—— 可回滚、可 A/B、可复现

自进化的对象是**版本化的 artifact**，不是「当前状态」。每个 artifact 有三种身份，必须分开追踪：

- `content_id`：内容指纹（同样的内容永远同一个 id）
- `release_id`：发布版本（一次 commit 产生一个）
- `runtime_load_id`：运行时实际加载的实例（热替换时与 release 不同）

混用这三种 id 是自进化系统最难查的 bug 来源。

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  Interlock Layer    四个咬合点：数字↔物理↔权重 的双向喂养      │
├─────────────────────────────────────────────────────────────┤
│  Recursive Loop     Serve → Observe → Grow → Commit          │
├─────────────────────────────────────────────────────────────┤
│  Surfaces           权重面 · harness 面 · memory 面           │
├─────────────────────────────────────────────────────────────┤
│  Substrate          Digital Substrate │ Physical Substrate    │
├─────────────────────────────────────────────────────────────┤
│  Evidence Ledger    贯穿全部四层的物证与归因（横切关注点）      │
└─────────────────────────────────────────────────────────────┘
```

五层的职责边界、接口契约与数据流，见 **[docs/architecture.md](docs/architecture.md)**。

---

## 核心抽象

框架不绑定任何具体的 LLM、VLA、仿真器或训练后端。四个扩展点：

| 抽象 | 职责 | 对应现有实现 |
|---|---|---|
| `Substrate` | 执行基底（数字 or 物理） | 容器/沙箱 · LIBERO/RoboCasa/真机 |
| `Surface` | 可进化的 artifact 类型 | 权重 · prompt/rules/skills · memory |
| `Recipe` | 如何从记录产生更新 | SAO/GRPO · harness 编辑 · memory 合并 |
| `Ledger` | 物证与归因 | 分层验证器 · 失败归因 |

这些抽象、以及提供它们的七个注册组的完整签名，见 **[docs/interfaces.md](docs/interfaces.md)** ——
该文档每次运行都会与真实代码比对。

---

## 接入你自己的系统

框架提供：发布链、artifact 仓储、物证台账、准入策略、循环的顺序保证、场景隔离。**你只需提供五样东西**，合计不到六十行：

| # | 你要写的 | 放在哪里 |
|---|---|---|
| 1 | 你的系统读取的策略/prompt 格式 | 与解析器放在一起的 render 函数 |
| 2 | `execute` —— 调用你的系统 | `Substrate.execute` |
| 3 | `health` —— 如何判断就绪 | `Substrate.health` |
| 4 | 打分逻辑 | `Verifier` |
| 5 | 下一个候选怎么生成 | `Recipe` |

完整可运行模板见 **[examples/custom_substrate.py](examples/custom_substrate.py)**。直接跑：

```bash
PYTHONPATH=src python examples/custom_substrate.py
```

它把一个阈值分类器端到端接了起来，并打印一整轮：一个把一半样本判错的 baseline、一次提案、一次接受 —— 之后同一个输入由错变对，无需重启。

### 1. 声明你的实现

可以在进程内注册，也可以让你的包在自己的 `pyproject.toml` 里声明：

```python
from rsihybridagent import ExtensionPoint, register

register(ExtensionPoint.SUBSTRATE, "my-system", MySubstrate(...))
```

```toml
[project.entry-points."rsihybridagent.substrates"]
my-system = "my_pkg.substrates:MySubstrate"
```

**entry point 这条路径才是能进入别人环境的那条**，因此它才是真正要紧的机制。**你的包不需要 import 本项目来声明自己**，本项目也不需要知道你的包存在。

### 2. 实现 substrate

五个接入点里有两个在这里。标记处是唯一需要你替换的地方：

```python
class MySubstrate(Substrate):
    def kind(self) -> SubstrateKind:
        return SubstrateKind.DIGITAL

    def execute(self, request, *, scenario):
        policy = self._current_policy(scenario)          # 读取当前发布的版本
        result = my_system.run(request, policy)          # <-- 换成你的调用
        receipt = Receipt(value=f"{scenario.name}-{n}", scenario=scenario)
        return receipt, result

    def health(self, *, scenario):
        return {"healthy": self._reachable(scenario), "problem": None}
```

**每次调用都要重新读策略，不要在构造时缓存。** 这正是"被接受的改进能立刻生效"的原因。缓存策略的 substrate 能通过所有测试，却在生产环境里永远不反映更新。

**`health` 接收 scenario。** 就绪不是全局属性：一个策略从未为某场景发布的 substrate，对该场景就是不就绪。这里没有无参版本，因为它只能回答全局那一半，会把配置错误的场景报成健康。

如果你的系统是独立进程或远程机器，`execute` 就是发生 RPC 的地方，文件其余部分不用改。这正是让 agent 侧留在 CPU、而物理侧持有 GPU 的方式。

### 3. 实现 verifier

在任何运行开始**之前**声明你的层。这正是台账能发现"某层从未运行"的前提：

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

框架依赖两条规则，都由台账强制：

- **自己测 baseline。** 让 recipe 提供 baseline 数值，等于让"产生变更的一方"同时提供"评判该变更的数字"。
- **没运行的层必须报 `NOT_RUN`，绝不能报 `FAILED`。** 当契约检查短路时，行为层并未执行；把它称为失败就是在归咎一个从未运行的层，而错误的归因会污染此后所有读取该条目的决策。

### 4. 实现 recipe

```python
class MyRecipe(Recipe):
    def target_surface(self) -> Surface:
        return self.surface

    def eligible(self, receipts, feedback, *, scenario) -> bool:
        return feedback.score is not None and feedback.score < 0.95

    def propose(self, *, scenario):
        return self.surface.stage(scenario=scenario, files={...})   # 或 None
```

**没有可提案的就返回 `None`。** 这是正常结果，不是错误，循环也这样对待它：没有候选就没有台账条目。搜索空间耗尽的 recipe 必须能与"试过但失败"区分开。

### 5. 串起来

```python
loop = RecursiveLoop(
    substrate=MySubstrate(...),
    recipe=MyRecipe(...),
    verifier=MyVerifier(...),
    policy=EvidenceAdmissionPolicy(baseline_pass_rate=measured),
    ledger=MemoryLedger(),
)

receipt, result = loop.serve(request, scenario=scenario)   # 1. 服务
loop.observe(Feedback(receipts=(receipt,), score=0.0), scenario=scenario)  # 2. 有信号吗
candidate = loop.grow(scenario=scenario)                    # 3. 产出候选
entry = loop.commit(candidate, scenario=scenario)           # 4. 验证、裁决、发布
```

`commit` **只在 `ACCEPTED` 时**发布，且无论裁决如何都追加台账条目 —— 拒绝与接受同样可审计。

### 四个必踩的坑

| 症状 | 原因 | 修法 |
|---|---|---|
| `TypeError: Can't instantiate abstract class ... without an implementation for abstract method` | 你用了 `@property @abstractmethod`，却想用同名 dataclass 字段满足它 | 改用方法。同名字段会变成持有描述符的类属性，子类因此仍是抽象类，而报错却指向一个它明明定义了的方法 |
| `mypy` 拒绝你的 surface，但测试全过 | 实现只是鸭子类型地"长得像"基类，没有继承 | 显式继承。运行时检查看不出差别，类型检查器看得出 |
| 候选从未被接受，理由里提到 baseline | 该场景没有发布过任何版本，策略没有可比对的基准 | 先发布一个 baseline |
| 跨场景读取报 "not found"，而不是指出是哪个场景 | 你读取时传的 scenario 与存储时不同 | 传同一个 `ScenarioId`。场景之间从不共享发布链；能确定归属时错误里会指出所属场景 |

---

### 不 fork 也能接入

**没人能发现的接口不是开放接口，只是一个抽象类。** 第三方包只需在**自己的**打包元数据里声明实现，本项目完全不需要知道它的存在：

```toml
[project.entry-points."rsihybridagent.substrates"]
libero = "my_pkg.substrates:LiberoSubstrate"
```

识别 7 个注册组，每组都规定了成员必须满足的契约：

| 注册组 | 必须实现 |
|---|---|
| `rsihybridagent.substrates` | `Substrate` |
| `rsihybridagent.surfaces` | `Surface` |
| `rsihybridagent.recipes` | `Recipe` |
| `rsihybridagent.verifiers` | `Verifier` |
| `rsihybridagent.policies` | `AdmissionPolicy` |
| `rsihybridagent.ledgers` | `Ledger` |
| `rsihybridagent.interlock` | `InterlockPort` |

注册值可以是实现本身，也可以是一个返回实现的零参可调用对象。**不满足本组契约的值会在解析阶段就被拒绝**，而不是等到某个调用点才失败 —— 那时 traceback 会指向错误的层。

```bash
rsihybrid extensions                                          # 已安装了什么，以及每组要求什么
rsihybrid extensions rsihybridagent.recipes                   # 只看一个组
rsihybrid check rsihybridagent.substrates my_pkg.sub:Thing    # 解析一个扩展并报告是否符合契约
```

`check` 收的是**完整组名**，不是短名；它会打印实际解析到的类型，
让「我配的是 X」与「加载的是 Y」可以直接对照。

---

## 状态

**闭环已在 CPU 上端到端跑通。** 下面两个示例都能在一秒内完成一整轮 Serve → Observe → Grow → Commit。

- ✅ 架构设计与接口契约（`docs/`）
- ✅ 扩展点注册机制，第三方后端不 fork 即可接入
- ✅ 可运行的 reference implementation：substrate / surface / repository / recipe / verifier / policy / ledger
- ✅ 可直接复制的接入模板：**[examples/custom_substrate.py](examples/custom_substrate.py)**
- ✅ 确定性任务上的端到端验证（140 个测试）
- ✅ 文档受代码校验：`docs/interfaces.md` 每次运行都与真实签名比对，
  不会再像曾经那样悄悄漂移
- ⬜ 物理侧 substrate（仿真器或真机）
- ⬜ 四个互锁通道的实现 —— 目前是契约，不是代码
- ⬜ 持久化 artifact 存储与持久化物证台账

```bash
PYTHONPATH=src python examples/arithmetic_loop.py     # 闭环：一次被拒绝、一次被接受
PYTHONPATH=src python examples/custom_substrate.py    # 如何接入你自己的系统
```

**两个必须说清的前置约束。**

本框架的完整服务依赖 POSIX 进程组语义（`os.killpg` / `os.setsid` / `fcntl`），**Windows 原生不可用**，需 WSL2 或 Linux 容器。核心抽象、reference implementation 与测试套件可在 Windows 上运行。

参考 substrate 是**玩具**。它做算术题，目的是让物证台账能被确定性地检验 —— 那里的提升要么真实存在要么不存在，不涉及统计。它不是 benchmark，分数对任何模型都没有意义。

---

## 与现有项目的关系

rsihybridagent 站在两个优秀开源项目之上，并明确其增量：

| 项目 | 许可证 | rsihybridagent 借用 | rsihybridagent 新增 |
|---|---|---|---|
| [reef](https://github.com/Human-Agent-Society/reef) | Apache-2.0 | 四步循环、recipe/surface/runtime 抽象、版本发布链 | 物理基底、物证台账、互锁层 |
| [RPent](https://github.com/RLinf/RPent) | Apache-2.0 | 物理侧 RPC 解耦、memory schema、planner 适配 | 学习闭环、权重回灌、跨环境 memory |

**不做 fork，做集成。** 物理侧以独立 recipe + adapter + runtime backend 的形式接入，跟随上游演进。

完整的借鉴清单、论文引用与许可证遵守说明，见 **[References](#references)**。

### 如何引用本项目

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

## 快速开始

> 完整服务需要 Linux 环境（WSL2 或容器）。核心抽象与物证台账可在 CPU 上运行。

```bash
git clone https://github.com/possibleme2026-lang/rsihybridagent && cd rsihybridagent
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"

pytest -q
rsihybrid channels
```

---

## References

### 1. 直接建立其上的项目

以下开源项目构成本项目的架构基础。均为 Apache-2.0，与本项目许可证兼容。

**[reef](https://github.com/Human-Agent-Society/reef)** · Apache-2.0 · PyPI `reef-infra`

自进化 agent 的持续学习基础设施。本项目借鉴其：

- 四步循环的划分（Serve → Observe → Grow → Commit）
- recipe / surface / runtime 三层抽象，以及「核心在包内、方法在 `recipes/`」的边界纪律
- artifact 版本发布链与三种 artifact 身份分离的设计
- receipt 机制（一次交互的凭据，用于把反馈关联回记录）

**[RPent](https://github.com/RLinf/RPent)** · Apache-2.0 · PyPI `rpent`

物理世界的 agentic 框架（planner + 冻结 VLA + 仿真器/真机）。本项目借鉴其：

- 物理侧 RPC 完全解耦的设计（`--env-endpoint` / `--vla-endpoint` 允许 agent 进程不 import torch）
- memory 的 Markdown + YAML frontmatter schema（`scope` / `kind` / `confidence` / `evidence`）
- planner 适配层与 robot 的动态发现机制

**[cordis](https://github.com/cordiverse/cordis)** · Apache-2.0

harness 的组合与演化引擎，reef 的 harness 进化面构建于其上。

**[Slime](https://github.com/THUDM/slime)** · Apache-2.0 · **[SGLang](https://github.com/sgl-project/sglang)** · Apache-2.0

模型权重训练与高性能推理引擎，构成权重面的训练与服务体系。

### 2. 论文引用

本项目的物理侧设计参考了 **Harness VLA** 的核心结论——记忆引导的 agent 能让冻结的 VLA
显著变强，这正是不重训权重也能提升物理任务成功率的依据：

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

### 3. 设计思想的来源

**分层验证的诚实记账**（本项目的核心主张：未运行 ≠ 失败 ≠ 跳过）来自具身 benchmark 的工程实践，
而非论文。其参考实现与踩坑记录见 `hybrid-embodied-bench` 中的 Harbor 任务
`terminal-bench-science/hybrid-lab-quarantine`。

该任务的三层验证（data / controller / embodied）在集成测试中抓出过一个真 bug：
grader 把某一层的 skip 写进了失败字段，导致一个变体看起来「挂了两层」。
这条教训直接催生了本项目的 `LayerStatus` 设计。

**任务格式**参考 [Harbor](https://github.com/laude-institute/harbor) / Terminal-Bench。

### 4. 许可证遵守

本项目以 Apache-2.0 发布。对上述项目的使用方式为**架构借鉴与接口对接，未复制其源代码**。

若后续版本直接复用其中任何代码，将保留原始版权声明、在 `NOTICE` 中注明来源，并遵守
Apache-2.0 第 4 条关于衍生作品的要求。

本项目为独立实现，与上述项目无隶属关系，也未获得其背书。

---

## 许可证

Apache-2.0。见 [LICENSE](LICENSE)。
