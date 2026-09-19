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

> `NOT_RUN` 与 `FAILED` 的区别是本框架的核心不变式。见[分层状态语义](#七分层状态语义)。

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

## 二、`Artifact` / `ArtifactRepository`（body 与存储）

**`ArtifactRef` 是引用，`Artifact` 是 body。** 前者只带身份（surface、substrate、
content/release/parent），可以被自由传递、比较、写进台账；后者带实际字节。把两者合成一个类型
会在 `stage` 处立刻卡住——见[三、`Surface`](#三surface可进化面)里的说明。

```python
class ArtifactError(Exception): ...
class ArtifactNotFound(ArtifactError): ...

@dataclass(frozen=True)
class Artifact:
    ref: ArtifactRef
    files: Mapping[str, str] = field(default_factory=dict)   # 文本面：harness / memory
    payload: bytes | None = None                             # 二进制面：weights

    @property
    def content_id(self) -> ContentId: ...
    @property
    def release_id(self) -> ReleaseId: ...
    def text(self, path: str) -> str: ...                    # 缺文件时抛错，不返回默认值

class ArtifactRepository(ABC):
    @abstractmethod
    def store(
        self,
        *,
        scenario: ScenarioId,
        surface: ArtifactRef,
        files: Mapping[str, str] | None = None,
        payload: bytes | None = None,
    ) -> ArtifactRef: ...

    @abstractmethod
    def materialize(self, ref: ArtifactRef, *, scenario: ScenarioId) -> Artifact: ...

    @abstractmethod
    def exists(self, ref: ArtifactRef, *, scenario: ScenarioId) -> bool: ...

    @abstractmethod
    def metadata(self, ref: ArtifactRef, *, scenario: ScenarioId) -> Mapping[str, Any]: ...
```

| 不变式 | 说明 |
|---|---|
| `files` 与 `payload` **二选一** | 两者皆空 → 这是「指向无物的引用」，构造即拒；两者皆有 → 该 artifact 没有确定的读取方，同样拒 |
| `store` 的 `surface` 参数只提供身份 | 它带入 surface / substrate / `parent`，**自身的 content_id 与 release_id 被忽略**，由实际存入的 body 重新推导。传入上一个引用，就是发布链的构建方式 |
| `store` 每次铸新 release | 内容相同也铸新的。合并会让 *发布过两次* 与 *发布过一次* 无法区分 |
| `materialize` 缺 body 时抛 `ArtifactNotFound` | 不返回 `None`——调用方拿到的 `Artifact` 一定是完整可读的 |
| 读取按 scenario 显式寻址 | 跨 scenario 读取在签名上就写明，不能靠默认值静默发生 |

**为什么 `files` 与 `payload` 不统一成一个抽象**：checkpoint 没有有意义的「按文件」接口，
硬套一层 mapping 会迫使每个权重读取方走一条它不想要的路径。文本面与二进制面各自干净，
比一个两边都别扭的统一类型好。

---

## 三、`Substrate`（执行基底）

```python
class Substrate(ABC):
    @abstractmethod
    def kind(self) -> SubstrateKind: ...

    @abstractmethod
    def execute(
        self, request: Mapping[str, Any], *, scenario: ScenarioId
    ) -> tuple[Receipt, Mapping[str, Any]]: ...

    @abstractmethod
    def health(self, *, scenario: ScenarioId) -> Mapping[str, Any]: ...
```

| 契约 | 说明 |
|---|---|
| 边界校验 | 基底在自身边界校验输入，并用自身词汇报告失败；上层不解析基底特有错误 |
| 不得要求 GPU 栈 | 物理基底必须是**独立进程**，经 RPC 访问。这是 agent 侧能留在 CPU 上的原因 |
| `health(*, scenario)` | 不健康的基底不得接受工作 |

`execute` 返回的 `Mapping` 是基底特有的，本层不解释其内容。

**`kind` / `health` 是方法，不是 `@property`。** 这不是风格问题：`@property @abstractmethod`
无法被子类的 dataclass 字段满足——同名字段会变成持有描述符的类属性，子类仍然抽象，
实例化时报 `TypeError: Can't instantiate abstract class ... without an implementation`。
所有扩展点的抽象成员一律用方法，使 dataclass 实现可以正常派生。

**`health` 带 `scenario` 参数**，因为就绪性是**逐 scenario** 的：一个基底可能在 scenario A
已加载模型、在 scenario B 尚未初始化。无参版本只能凭空捏造一个探测用的 scenario 名。

---

## 四、`Surface`（可进化面）

```python
class Surface(ABC):
    @abstractmethod
    def kind(self) -> SurfaceKind: ...

    @abstractmethod
    def repository(self) -> ArtifactRepository: ...

    @abstractmethod
    def current(self, *, scenario: ScenarioId) -> ArtifactRef | None: ...

    @abstractmethod
    def stage(
        self,
        *,
        scenario: ScenarioId,
        files: Mapping[str, str] | None = None,
        payload: bytes | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRef: ...

    @abstractmethod
    def publish(self, candidate: ArtifactRef, *, scenario: ScenarioId) -> ArtifactRef: ...

    @abstractmethod
    def rollback(self, *, scenario: ScenarioId) -> ArtifactRef | None: ...

    @abstractmethod
    def deliver(self, artifact: ArtifactRef, *, scenario: ScenarioId) -> RuntimeLoadId: ...
```

**职责边界**：surface 只回答「当前 artifact 是什么」与「候选如何替换它」。
候选**如何产生**属于 recipe；候选**好不好**属于 ledger。

**surface 自己不存字节。** 它向 `repository()` 要，这是把存储布局挡在所有 surface 实现之外的原因：
harness surface 存文件树、weights surface 存 checkpoint，两者不必背上对方的存储假设。

| 方法 | 语义 |
|---|---|
| `kind` | 本 surface 服务哪一类 artifact |
| `repository` | 本 surface 的字节存在哪里。**公开而非隐藏**：verifier 需要读候选的 body，而 verifier 刻意是与 surface 不同的协作者。把这次读取绕回 surface 会让 surface 成为验证输入的单一真相源，正是分离要避免的耦合 |
| `current` | 首次提交前返回 `None` |
| `stage` | **直接接收字节**（`files` 或 `payload`），在内部铸出 `ArtifactRef` 并放在当前发布**旁边**，尚不服务 |
| `publish` | 推进发布链并返回已发布引用 |
| `rollback` | 回退到父版本；根处返回 `None` |
| `deliver` | 让已发布 artifact 对消费者生效，返回运行时实例 id |

**为什么 `stage` 收字节而不是收 `ArtifactRef`**：早期签名是
`stage(candidate: ArtifactRef, ...)`，它无法工作——调用方若还没有 body，就没有
`content_id` 可填；若已有 body，说明 body 已经被存过，那这次调用只是重复存储。
候选的**产生**因此无法表达。现在的分工是：调用方给字节，surface 交给 repository 铸出引用。
`store()` 每次铸**新 release**，即使内容与上次完全相同——*再次提出* 与 *提出过一次*
是两个不同的事实，合并它们会丢掉重复尝试的记录。

---

## 五、`Ledger` 与 `AdmissionPolicy`（物证台账）

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

## 六、`Recipe` / `Verifier` / `RecursiveLoop`

```python
class Recipe(ABC):
    @abstractmethod
    def target_surface(self) -> Surface: ...

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

## 七、分层状态语义

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

## 八、`Interlock`（互锁通道）

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
    @abstractmethod
    def channel(self) -> Channel: ...
    @abstractmethod
    def health(self, *, scenario: ScenarioId) -> Mapping[str, Any]: ...

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

---

## 九、`ExtensionPoint`（扩展注册表）

前面的章节说明实现必须**做什么**；本节说明实现如何**被找到**。两者缺一不可——
一个没人能发现的接口不是开放接口，只是一个抽象类。

```python
class ExtensionPoint(StrEnum):
    SUBSTRATE = "rsihybridagent.substrates"
    SURFACE   = "rsihybridagent.surfaces"
    RECIPE    = "rsihybridagent.recipes"
    VERIFIER  = "rsihybridagent.verifiers"
    POLICY    = "rsihybridagent.policies"
    LEDGER    = "rsihybridagent.ledgers"
    INTERLOCK = "rsihybridagent.interlock"

#: 每个组的成员必须实现的抽象。这张表让注册表成为**兼容性检查**，而非查找表。
REQUIRED_BASE: Mapping[ExtensionPoint, type] = {...}

class RegistryError(Exception): ...

def register(point: ExtensionPoint, name: str, value: object) -> None: ...
def unregister(point: ExtensionPoint, name: str) -> None: ...
def clear_local(point: ExtensionPoint | None = None) -> None: ...
def available(point: ExtensionPoint) -> tuple[str, ...]: ...
def load(point: ExtensionPoint, spec: str) -> object: ...
def describe(point: ExtensionPoint) -> tuple[str, ...]: ...
```

### 三种提供实现的方式

按持久程度递增：

| 方式 | 写法 | 适用 |
|---|---|---|
| 直接引用 | `load(point, "my_pkg.module:MySubstrate")` | 脚本、测试、自行固定接线的部署 |
| 进程内注册 | `register(point, name, value)` | 想用 fake 替换真实后端的测试 |
| 已安装 entry point | 在 `pyproject.toml` 中声明 | 分发包。**唯一能进入他人环境的方式**，因此是真正重要的机制 |

**为什么用 entry point 而不是扫描插件目录**：目录扫描为了知道「有什么」必须先 import，
于是发现过程带副作用，结果还依赖文件系统顺序。entry point 声明在打包元数据里，
列出来不 import 任何东西，集合是确定的。

**组的值可以是实现本身，也可以是零参可调用对象返回实现。** 与 reef 采用同一约定，
使为任一项目写的后端形状一致。两者都接受，是因为描述符天然是一个值，
而持有连接的后端天然是一个工厂。

```toml
# 第三方包的 pyproject.toml —— 不需要 import 本框架的任何模块
[project.entry-points."rsihybridagent.substrates"]
libero = "my_pkg.substrates:LiberoSubstrate"

[project.entry-points."rsihybridagent.verifiers"]
libero = "my_pkg.verifiers:LiberoVerifier"
```

### `load` 的三条不变式

| 不变式 | 说明 |
|---|---|
| **返回值已通过契约校验** | 返回值保证是所属组的 `REQUIRED_BASE` 实例。不合规的值在此处被拒，而不是等到调用点才炸——那时的 traceback 会指向错误的层 |
| **名字缺失是错误，不是回退** | 静默的默认值会让部署以为自己跑的是物理基底，实际跑的是桩。这与证据台账要防的是同一类失败 |
| **本地注册遮蔽同名已安装项** | 测试可以替换真实后端而不必卸载任何东西 |

**为什么点号 spec 没有冒号会被当作格式错误而非「未知名字」**：`my_pkg.module` 看起来就像引用，
也确实是有人想写引用时的形状。报「没有这个名字的扩展」会把人引向一个并不存在的注册错误。
注册名按约定是裸标识符，这就是区分依据：

```python
def _looks_like_reference(spec: str) -> bool:
    return bool(spec) and "." in spec and all(part.isidentifier() for part in spec.split("."))
```

同名被多个提供方声明时报 `RegistryError` 并列出全部来源，而不是任选一个——
选一个会让「跑的是谁」变成环境巧合。

### CLI

命令名是 **`rsihybrid`**（`pyproject.toml` 的 `[project.scripts]` 条目），不是 `rsihybridagent`。

```bash
rsihybrid channels                                       # 列出四个互锁通道及其方向
rsihybrid extensions                                     # 列出所有组及其可用实现
rsihybrid extensions rsihybridagent.recipes              # 只看一个组
rsihybrid check rsihybridagent.substrates my_pkg.sub:Thing   # 解析一个扩展并报告是否符合契约
```

空组会被**显示**而不是省略：正在排查后端缺失的部署需要看到「组存在但是空的」，
这与「组根本没被识别」是两条不同的信息。

`check` 的定位是诊断接线错误——它把 `RegistryError` 打给 stderr 并返回 1，
成功时打印解析到的实际类型，让「我配了 X」与「实际加载的是 Y」当场对上。
