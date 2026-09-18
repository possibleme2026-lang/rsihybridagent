# 接口契约

> 本文档给出每个扩展点的完整签名。所有签名以 `src/rsihybridagent/` 中的实际代码为准。

---

## 一、共享值类型（`core.py`）

### 枚举

```python
class SubstrateKind(StrEnum):   DIGITAL · PHYSICAL
class SurfaceKind(StrEnum):     WEIGHTS · HARNESS · MEMORY
class Verdict(StrEnum):         ACCEPTED · REJECTED · INCONCLUSIVE

class LayerStatus(StrEnum):
    NOT_RUN   # 未执行。与 FAILED 严格区分，见下文
    PASSED    # 执行且通过
    FAILED    # 执行且失败
    SKIPPED   # 主动跳过，必须给出理由
```

> `NOT_RUN` 与 `FAILED` 的区别是本框架的核心不变式。见[分层状态语义](#六分层状态语义)。

### 三种 artifact 身份

```python
@dataclass(frozen=True)
class ContentId:
    value: str
    @classmethod
    def of(cls, payload: bytes) -> ContentId   # sha256 指纹

@dataclass(frozen=True)
class ReleaseId:
    value: str

@dataclass(frozen=True)
class RuntimeLoadId:
    value: str
```

| 身份 | 含义 | 何时变化 |
|---|---|---|
| `content_id` | 内容指纹 | 只在内容真正改变时变 |
| `release_id` | 一次被接受的 commit | 每次发布都变，**即使内容与上次相同** |
| `runtime_load_id` | 运行时实际加载的实例 | 每次加载都变，热替换时与 `release_id` 不同 |

### 引用与交互

```python
@dataclass(frozen=True)
class ArtifactRef:
    surface: SurfaceKind
    substrate: SubstrateKind
    content_id: ContentId
    release_id: ReleaseId
    parent: ReleaseId | None = None      # 回滚目标；根 artifact 为 None
    metadata: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ScenarioId:
    name: str

@dataclass(frozen=True)
class Receipt:
    value: str
    scenario: ScenarioId

@dataclass(frozen=True)
class Feedback:
    receipts: tuple[Receipt, ...]
    score: float | None = None            # 便宜的标量，供 recipe 训练
    detail: Mapping[str, Any] | None = None  # 更丰富的结构化/文本信号
```

**`Receipt` 是交互与反馈之间的唯一链接。** 没有有效 receipt 的反馈无法关联，必须拒绝而非猜测归属。

**`ScenarioId` 是隔离边界。** 两个 scenario 永不共享发布链，因此一个不可能静默继承另一个的进展。

---

## 二、`Substrate`（执行基底）

```python
class Substrate(ABC):
    @property
    @abstractmethod
    def kind(self) -> SubstrateKind: ...

    @abstractmethod
    def execute(
        self, request: Mapping[str, Any], *, scenario: ScenarioId
    ) -> tuple[Receipt, Mapping[str, Any]]: ...

    @abstractmethod
    def health(self) -> Mapping[str, Any]: ...
```

| 契约 | 说明 |
|---|---|
| 边界校验 | 基底在自身边界校验输入，并用自身词汇报告失败；上层不解析基底特有错误 |
| 不得要求 GPU 栈 | 物理基底必须是**独立进程**，经 RPC 访问。这是 agent 侧能留在 CPU 上的原因 |
| `health()` | 不健康的基底不得接受工作 |

`execute` 返回的 `Mapping` 是基底特有的，本层不解释其内容。

---

## 三、`Surface`（可进化面）

```python
class Surface(ABC):
    @property
    @abstractmethod
    def kind(self) -> SurfaceKind: ...

    @abstractmethod
    def current(self, *, scenario: ScenarioId) -> ArtifactRef | None: ...

    @abstractmethod
    def stage(self, candidate: ArtifactRef, *, scenario: ScenarioId) -> ArtifactRef: ...

    @abstractmethod
    def publish(self, candidate: ArtifactRef, *, scenario: ScenarioId) -> ArtifactRef: ...

    @abstractmethod
    def rollback(self, *, scenario: ScenarioId) -> ArtifactRef | None: ...

    @abstractmethod
    def deliver(self, artifact: ArtifactRef, *, scenario: ScenarioId) -> RuntimeLoadId: ...
```

**职责边界**：surface 只回答「当前 artifact 是什么」与「候选如何替换它」。
候选**如何产生**属于 recipe；候选**好不好**属于 ledger。

| 方法 | 语义 |
|---|---|
| `current` | 首次提交前返回 `None` |
| `stage` | 把候选放在当前发布**旁边**，尚不服务 |
| `publish` | 推进发布链并返回已发布引用 |
| `rollback` | 回退到父版本；根处返回 `None` |
| `deliver` | 让已发布 artifact 对消费者生效，返回运行时实例 id |

---

## 四、`Ledger` 与 `AdmissionPolicy`（物证台账）

### 分层结果

```python
@dataclass(frozen=True)
class LayerResult:
    layer: str
    status: LayerStatus
    detail: Mapping[str, object] = field(default_factory=dict)

    @property
    def ran(self) -> bool:      # status is not NOT_RUN
    @property
    def passed(self) -> bool:   # status is PASSED（SKIPPED 永远不是通过）

@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    seed: int
    layers: tuple[LayerResult, ...]

    @property
    def all_layers_ran(self) -> bool: ...
    @property
    def all_layers_passed(self) -> bool: ...
    def failing_layers(self) -> tuple[str, ...]:    # 只认 FAILED
    def not_run_layers(self) -> tuple[str, ...]:    # 只认 NOT_RUN
```

> ⚠️ `LayerResult` 的构造器会拒绝**没有 reason 的 SKIPPED**。跳过必须说明原因，否则无法与疏漏区分。

### 物证

```python
@dataclass(frozen=True)
class Evidence:
    scenario: ScenarioId
    candidate: ArtifactRef
    baseline: ArtifactRef | None
    cases: tuple[CaseOutcome, ...]
    declared_layers: tuple[str, ...]
    attribution: str | None = None
    notes: str = ""

    def missing_layers(self) -> tuple[str, ...]    # 完全没有结果的层
    def not_run_layers(self) -> tuple[str, ...]    # 显式报了 NOT_RUN 的层
    def skipped_layers(self) -> tuple[str, ...]
    def pass_rate(self) -> float
```

**`declared_layers` 必须在任何运行开始前声明。** 这是台账能检测出「某层从未运行」的前提——只报告实际执行过的层的验证器，无法区分「省略了检查」与「检查通过了」。

**`attribution` 必须指向实际运行过的层。** 归因到没跑的层会被构造器直接拒绝。

### 存储与准入

```python
@dataclass(frozen=True)
class LedgerEntry:
    entry_id: str
    evidence: Evidence
    verdict: Verdict
    reason: str

class Ledger(ABC):
    @abstractmethod
    def append(self, entry: LedgerEntry) -> None: ...
    @abstractmethod
    def entries(self, *, scenario: ScenarioId) -> Sequence[LedgerEntry]: ...
    @abstractmethod
    def accepted_chain(self, *, scenario: ScenarioId) -> Sequence[ArtifactRef]: ...

class AdmissionPolicy(ABC):
    @abstractmethod
    def decide(self, evidence: Evidence) -> tuple[Verdict, str]: ...
```

**台账只追加**：改写判定会抹掉「为什么这个 artifact 是活的」的唯一记录。

### 默认准入策略

```python
@dataclass(frozen=True)
class EvidenceAdmissionPolicy(AdmissionPolicy):
    min_pass_rate: float = 0.95
    min_improvement: float = 0.0
    baseline_pass_rate: float | None = None
    require_attribution: bool = True
```

**检查顺序（不可颠倒）**：

| # | 检查 | 不通过 |
|---|---|---|
| 1 | 有实例 | `INCONCLUSIVE` |
| 2 | 声明的层都有结果（`missing_layers`） | `INCONCLUSIVE` |
| 3 | 没有层报 `NOT_RUN`（`not_run_layers`） | `INCONCLUSIVE` |
| 4 | 没有层跳过（`skipped_layers`） | `INCONCLUSIVE` |
| 5 | 没有失败用例 | `REJECTED`（点名失败层） |
| 6 | 有归因 | `INCONCLUSIVE` |
| 7 | 通过率 ≥ `min_pass_rate` | `REJECTED` |
| 8 | 有基线 | `INCONCLUSIVE` |
| 9 | 提升 ≥ `min_improvement` | `REJECTED` |
| 10 | 全部通过 | `ACCEPTED` |

**完整性先于性能**：没跑完所有层的候选，其性能数字没有比较价值。

---

## 五、`Recipe` / `Verifier` / `RecursiveLoop`

```python
class Recipe(ABC):
    @property
    @abstractmethod
    def surface(self) -> Surface: ...

    @abstractmethod
    def eligible(
        self, receipts: tuple[Receipt, ...], feedback: Feedback, *, scenario: ScenarioId
    ) -> bool: ...

    @abstractmethod
    def propose(self, *, scenario: ScenarioId) -> ArtifactRef | None: ...

class Verifier(ABC):
    @abstractmethod
    def declared_layers(self) -> tuple[str, ...]: ...

    @abstractmethod
    def verify(self, candidate: ArtifactRef, *, scenario: ScenarioId) -> Evidence: ...

class RecursiveLoop:
    def __init__(
        self,
        *,
        substrate: Substrate,
        recipe: Recipe,
        verifier: Verifier,
        policy: AdmissionPolicy,
        ledger: Ledger,
    ) -> None: ...

    def serve(self, request: Mapping[str, Any], *, scenario: ScenarioId) -> tuple[Receipt, Mapping[str, Any]]: ...
    def observe(self, feedback: Feedback, *, scenario: ScenarioId) -> bool: ...
    def grow(self, *, scenario: ScenarioId) -> ArtifactRef | None: ...
    def commit(self, candidate: ArtifactRef | None, *, scenario: ScenarioId) -> LedgerEntry | None: ...
```

**`propose` 返回 `None` 是正常结果**，不是错误：数据不足与尝试失败必须可区分。

**`observe` 会拒绝跨 scenario 的反馈**，而不是套用——接受它会让一个 scenario 的结果移动另一个的 artifact，这种隔离破坏事后极难发现。

**协作者分离的理由**：产生变更的一方不能同时判定变更是否有效。`Recipe` 提出、`Verifier` 取证、`AdmissionPolicy` 判定，三权分立使台账的归因有意义。

---

## 六、分层状态语义

这是本框架最重要的接口约定。

| 状态 | 含义 | 计入通过？ | 可否被接受？ |
|---|---|---|---|
| `NOT_RUN` | 该层未执行 | ❌ | ❌ 必须重跑 |
| `PASSED` | 执行且通过 | ✅ | ✅ |
| `FAILED` | 执行且失败 | ❌ | ❌ 拒绝并点名 |
| `SKIPPED` | 主动跳过（须有理由） | ❌ | ❌ 须先解决 |

**三种非通过状态必须始终可区分。** 使用枚举**不足以**保证这一点：

```python
# 危险：聚合布尔把三种状态塌回两种
if not case.all_layers_passed:
    failed = case.failing_layers()   # 只认 FAILED → NOT_RUN 时得到空集
    return Verdict.REJECTED, f"failed at: {', '.join(failed)}"
```

上面这段会在一层 `NOT_RUN` 时输出「拒绝 + 归因列表为空」——判定错，且理由不可用。

**规则**：任何以 `all_*_passed` 之类的聚合布尔为条件的分支，都必须确认它是否需要区分 `NOT_RUN`。
需要时，用 `failing_layers()` / `not_run_layers()` 成对判断，不要用单个布尔量。

---

## 七、`Interlock`（互锁通道）

```python
class Channel(StrEnum):
    SKILL_TRANSFER           # digital → physical, harness
    FAILURE_BACKPROP         # physical → digital, harness
    TRAJECTORY_DISTILLATION  # physical → digital, weights
    PRIMITIVE_DECOMPOSITION  # digital → physical, weights

    @property
    def source(self) -> SubstrateKind: ...
    @property
    def target(self) -> SubstrateKind: ...
    @property
    def surface(self) -> SurfaceKind: ...

@dataclass(frozen=True)
class Crossing:
    channel: Channel
    scenario: ScenarioId
    source_artifact: ArtifactRef
    payload: Mapping[str, Any]
    evidence: Evidence = field(kw_only=True)

class InterlockPort(ABC):
    @property
    @abstractmethod
    def channel(self) -> Channel: ...
    @abstractmethod
    def health(self) -> Mapping[str, Any]: ...

class CrossingProducer(InterlockPort):
    @abstractmethod
    def produce(self, *, scenario: ScenarioId) -> tuple[Crossing, ...]: ...

class CrossingConsumer(InterlockPort):
    @abstractmethod
    def consume(self, crossing: Crossing, *, scenario: ScenarioId) -> ArtifactRef: ...

def validate_crossing(crossing: Crossing) -> None: ...
```

**`payload` 按通道而异**：`SKILL_TRANSFER` 是蒸馏出的 skill，`FAILURE_BACKPROP` 是失败模式，
`TRAJECTORY_DISTILLATION` 是导出的轨迹集，`PRIMITIVE_DECOMPOSITION` 是原语分解。

**`evidence` 是必需的。** 没有物证的 crossing 是猜测，而猜测到了另一侧之后，事后无法与真实增益区分。

**`produce` 返回空元组是有效结果**，不得报成失败：尚未产出可迁移经验的基底只是**未就绪**，与**试过但失败**不同。

**`consume` 返回的是候选**，不是已发布的 artifact。发布是循环的决定，不是端口的。

**端口分离**：`CrossingProducer` 只读，`CrossingConsumer` 只写。既读又写的端口会模糊「哪一侧拥有验证权」，台账就无法归因回归。

**`validate_crossing` 检查**：来源基底的 kind 与通道声明一致；来源 artifact 的 surface 与通道声明一致；
payload 非空；crossing 与 evidence 的 scenario 一致。
