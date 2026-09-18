# rsihybridagent 架构

> 本文档描述五层架构的职责边界、接口契约与数据流。

---

## 一、设计出发点

自进化系统（RSI, Recursive Self-Improvement）目前被切成两半，各自都不完整：

| 形态 | 代表 | 有 | 缺 |
|---|---|---|---|
| 数字自进化基础设施 | reef、cordis | 完整的「推理→反馈→学习→版本化交付」闭环 | 没有身体 |
| 物理 agentic 框架 | RPent、openpi | planner + 冻结 VLA 的操作能力 | 没有学习闭环 |
| 具身 RL 训练 | RLinf、slime | 能训 VLA 权重 | 没有 harness 进化面 |

rsihybridagent 的立场是：**这三者不该各自独立，它们必须互锁。** 而互锁的前提是有一个能同时承载两类经验、并且拒绝谎报进步的底层。

---

## 二、五层架构

```
┌─────────────────────────────────────────────────────────────────┐
│  L5  Interlock      四个咬合点：数字 ↔ 物理 ↔ 权重 的双向喂养      │
├─────────────────────────────────────────────────────────────────┤
│  L4  Recursive Loop Serve → Observe → Grow → Commit              │
├─────────────────────────────────────────────────────────────────┤
│  L3  Surfaces       权重面 · harness 面 · memory 面               │
├─────────────────────────────────────────────────────────────────┤
│  L2  Substrate      Digital Substrate │ Physical Substrate        │
├─────────────────────────────────────────────────────────────────┤
│  L1  Evidence Ledger 贯穿 L2–L5 的物证与归因（横切关注点）          │
└─────────────────────────────────────────────────────────────────┘
```

**依赖方向**：L5 依赖 L4，L4 依赖 L3 与 L2，L1 被 L2–L5 全部依赖。**L1 不依赖任何层**——这是刻意的，物证的定义不能依赖被验证的对象。

### L1 · Evidence Ledger（物证台账）

**职责**：记录每一次进化，并强制「变更 / 物证 / 归因」三者齐全。

**核心不变式**：

| 不变式 | 为什么 |
|---|---|
| 每层的「未运行」与「运行失败」必须分开记录 | 折叠二者会同时产生空过（vacuous pass）与失败被隐藏 |
| `SKIPPED` 既不是通过也不是失败 | 跳过必须给出理由，且不可被计入通过 |
| 归因必须指向**实际运行过**的层 | 归因到没跑的层是猜测，不是证据 |
| 无基线不接受 | 没有基线，提升无法与噪声区分 |
| 台账只追加 | 改写判定会抹掉「为什么这个 artifact 是活的」的唯一记录 |

**关键类型**（`src/rsihybridagent/ledger/base.py`）：`LayerResult` · `CaseOutcome` · `Evidence` · `LedgerEntry` · `Ledger` · `AdmissionPolicy`

### L2 · Substrate（执行基底）

**职责**：与外界的边界。产生记录、消费交付的 artifact。

**两类基底**：

- **Digital Substrate**：容器化 / 沙箱化的执行环境
- **Physical Substrate**：仿真器或真机

**硬约束**：物理基底必须是**独立进程**，通过 RPC 通信，agent 进程不 import torch。理由很实际——8GB 显存上 agent 推理与物理仿真同时跑必然 OOM。分离后 agent 侧可跑 CPU，物理侧可在 GPU 机器或远程集群。

### L3 · Surfaces（可进化面）

**职责**：版本历史 + 交付。**只回答两个问题**：当前 artifact 是什么、候选如何替换它。

三个面：

| 面 | artifact 形态 | 交付方式 | 依赖 |
|---|---|---|---|
| **weights** | 模型权重 / adapter | 引擎热加载 | GPU |
| **harness** | 文本文件树（prompt/rules/skills） | 客户端拉取安装 | 仅需模型 endpoint |
| **memory** | 带 frontmatter 的 Markdown 树 | 客户端拉取安装 | 无 |

**三种身份必须分开**：`content_id`（内容指纹）· `release_id`（发布版本）· `runtime_load_id`（运行时实例）。混用是自进化系统最难查的 bug 来源——同一份内容可以发布两次，一个发布版本可以被加载进多个运行时实例。

### L4 · Recursive Loop（递归循环）

**职责**：四步序列 + 两条顺序不变式。**不含任何方法知识，也不含任何基底知识。**

```
Serve ──► Observe ──► Grow ──► Commit
  │           │          │        │
 产生        反馈       产生      验证
 receipt    是否足够    候选     → 判定 → 发布
```

**两条顺序不变式**：

1. **未发布的不得被服务**。候选 staged 在活 artifact 旁边，绝不在它前面。被拒绝的候选不触碰活 artifact——这是让回归可存活的原因。
2. **无物证的不得发布**。`commit` 查询准入策略。物证不完整的候选是 `INCONCLUSIVE`，既非接受也非拒绝：必须重跑，且台账记录「未作决定」。

**三个协作者**（都由外部注入，循环不实现它们）：

| 协作者 | 职责 | 为什么不内置 |
|---|---|---|
| `Recipe` | 从记录+反馈产生候选 | 方法特定策略，属于部署 |
| `Verifier` | 产生物证 | **产生变更的一方不能同时判定变更是否有效** |
| `AdmissionPolicy` | 判定接受与否 | 部署可改自己的门槛，而不动物证存储 |

### L5 · Interlock（互锁层）

**职责**：四个定向通道，让两侧经验互为输入。

| 通道 | 方向 | 目标面 |
|---|---|---|
| `SKILL_TRANSFER` | 数字 → 物理 | harness |
| `FAILURE_BACKPROP` | 物理 → 数字 | harness |
| `TRAJECTORY_DISTILLATION` | 物理 → 数字 | weights |
| `PRIMITIVE_DECOMPOSITION` | 数字 → 物理 | weights |

**为什么是四个而不是一个**：单通道使系统成为流水线，而流水线无法从「只接收的那一侧」的回归中恢复。每个通道携带自己的物证义务——**跨基底传播的主张，正是最容易被轻信的地方。**

**端口分离**：`CrossingProducer` 只读，`CrossingConsumer` 只写。一个既读又写的端口会模糊「哪一侧拥有验证权」，台账就无法归因回归。

---

## 三、一次完整进化的数据流

以「物理侧失败 → 数字侧约束」为例（`FAILURE_BACKPROP`）：

```
1. Serve    物理基底执行任务 → 产生 Receipt + 轨迹
2. Observe  任务判定为失败 → Feedback(score=0, detail={失败模式})
3. Grow     Recipe 读记录 → 提出 Crossing(payload={失败模式}, evidence=...)
4. Commit   Verifier 跑声明层 → Evidence
            AdmissionPolicy 判定 → 台账追加
            若 ACCEPTED → Surface.publish + deliver
```

注意第 3 步：`Crossing` **必须携带 evidence**。一个没有物证的 crossing 是猜测，而猜测到了另一侧之后，事后无法与真实增益区分——这正是本框架存在要防的事。

---

## 四、与现有实现的映射

框架不绑定任何具体实现。四个扩展点与其对应的现有实现：

| 抽象 | 可对接 |
|---|---|
| `Substrate` (digital) | 容器 / 沙箱 / 本地进程 |
| `Substrate` (physical) | LIBERO-PRO · RoboCasa · RoboTwin · Franka 真机 |
| `Surface` (weights) | Slime + SGLang 训练链 |
| `Surface` (harness) | 文本树 + 客户端安装 |
| `Surface` (memory) | Markdown + YAML frontmatter 语料 |
| `Recipe` | SAO/GRPO · harness 编辑 · memory 合并 |
| `Ledger` | 分层验证器 + 归因 |

---

## 五、已知边界与未决问题

**已确认的硬约束**：

- 完整服务依赖 POSIX 进程组语义（`os.killpg` / `os.setsid` / `fcntl`），**Windows 原生不可用**
- Python 版本需 `>=3.12`

**尚未解决的开放问题**：

1. **基线从哪来**。当前 `AdmissionPolicy` 要求 `baseline_pass_rate` 由验证器提供，但框架尚未定义基线的采集协议（同一批 case？同一组种子？统计显著性？）。
2. **跨基底的物证如何对齐**。数字侧的验证层与物理侧的验证层命名与粒度不同，`Crossing.evidence` 目前只做场景一致性检查，未做层级映射。
3. **连续进化的漂移检测**。多次接受后可能整体漂移，而每一次单步判定都通过。台账只追加的特性使其可审计，但尚无自动的漂移告警。
4. **权重面的物证成本**。跑一次完整验证可能需要数小时 GPU，与「快速迭代」冲突。是否需要分层验证（快筛 + 全验）尚未确定。
