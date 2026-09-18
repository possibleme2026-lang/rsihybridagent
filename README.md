<div align="center">

# rsihybridagent

**Recursive Self-Improvement for Hybrid Agents**

数字经验与物理经验互相进化 · 每一次自进化都必须留下可复核的物证

[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB)](pyproject.toml)
[![Status](https://img.shields.io/badge/status-design--stage-orange)]()

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

四个扩展点的完整接口签名见 **[docs/interfaces.md](docs/interfaces.md)**。

---

## 状态

**当前为设计阶段（design-stage）。** 已交付：

- ✅ 架构设计与接口契约（`docs/`）
- ✅ 核心抽象的类型骨架（`src/rsihybridagent/`）
- ⬜ 可运行的 reference implementation
- ⬜ 仿真环境的端到端验证

**一个必须说清的前置约束**：本框架的完整服务依赖 POSIX 进程组语义（`os.killpg` / `os.setsid` / `fcntl`），**Windows 原生不可用**，需 WSL2 或 Linux 容器。

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
git clone <this-repo> && cd rsihybridagent
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"
python -c "import rsihybridagent; print(rsihybridagent.__version__)"
```

---

## References

### 1. 直接建立其上的项目

以下开源项目构成本项目的架构基础。两者均为 Apache-2.0，与本项目许可证兼容。

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
这条教训直接催生了本项目的 `LedgerStatus` 设计。

**任务格式**参考 [Harbor](https://github.com/laude-institute/harbor) / Terminal-Bench。

### 4. 许可证遵守

本项目以 Apache-2.0 发布。对上述项目的使用方式为**架构借鉴与接口对接，未复制其源代码**。

若后续版本直接复用其中任何代码，将保留原始版权声明、在 `NOTICE` 中注明来源，并遵守
Apache-2.0 第 4 条关于衍生作品的要求。

本项目为独立实现，与上述项目无隶属关系，也未获得其背书。

---

## 许可证

Apache-2.0。见 [LICENSE](LICENSE)。
