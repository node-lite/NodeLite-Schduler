# Codex Task: 全量 Resource Latency Profiling，生成 NodeLite Object Cost Database

## 0. 任务目标

基于当前仓库：

```text
https://github.com/node-lite/NodeLite-Schduler
```

以及现有完整计划：

```text
NODELITE_COMPLETE_LATENCY_BENCHMARK.md
```

实现第一阶段全量 latency benchmark。

这一步暂时不以 Scheduler 加速结果为目标，也不要求先把 greedy scheduling 跑通。

第一阶段唯一核心目标是：

> 把所有可能发生切换、重启、reset、attach、materialize、invalidate、cleanup 的对象实际测一遍，最后得到一个可供 Scheduler 直接查询的 Object Cost Database。

最终 Scheduler 不应该自己猜：

```text
Node 18 -> Node 20 要多久
Chromium cold start 要多久
MongoDB warm reset 要多久
pnpm 9 -> pnpm 10 会失效什么
dependency view 重建要多久
```

而应该直接查询第一阶段测出来的数据。

---

# 1. 必须以现有完整 Benchmark 文档为 source of truth

不要重新发明一份缩减版清单。

首先读取：

```text
NODELITE_COMPLETE_LATENCY_BENCHMARK.md
```

其中已经定义：

```text
PREP
TRANSITION
EXECUTION
CLEANUP
CONTROL
DIAGNOSTIC
```

以及：

```text
network_cold
artifact_cold
process_cold
exact_hit
compatible_reuse
incompatible_switch
dirty_reset
failure_path
contention_path
```

这些定义继续沿用。

同时继续遵守该文档的核心记账规则：

1. 一个物理动作只有一个 latency owner。
2. Node runtime switch 与它触发的 downstream invalidation 分开计费。
3. 全局 Raw CAS 命中不能被错误计成 Task similarity 的巨大收益。
4. Task-private state 不产生 reuse benefit，只产生 reset/cleanup/risk。
5. Task execution 本身与 environment transition 分开。
6. 所有 latency 必须来自真实测量，不能手填常数。

---

# 2. 第一阶段的输出不是“一张软件启动时间表”

我们需要的是一个：

```text
Object Cost Database
```

这里的 Object 指：

```text
一个有明确 identity + version/config + compatibility key
并且其状态可能发生 cold / hit / reuse / switch / reset / invalidation 的对象。
```

例如下面不是一个 Object：

```text
Node.js
```

而应该展开成：

```text
node_runtime:
  Node 18.x
  Linux x86_64
  glibc
  Node ABI X
```

另一个：

```text
node_runtime:
  Node 20.x
  Linux x86_64
  glibc
  Node ABI Y
```

于是可以实际测：

```text
18 -> 18
18 -> 20
18 -> 22
20 -> 18
20 -> 20
20 -> 22
22 -> 18
22 -> 20
22 -> 22
```

同理，不能只写：

```text
Chromium restart = 800 ms
```

应该区分：

```text
Chromium revision A -> A
Chromium revision A -> B
same revision + same flags
same revision + different flags
process cold
process warm
BrowserContext reset
profile reset
```

---

# 3. Object 的规范数据模型

所有可切换对象必须产生一个稳定的 object identity。

建议：

```json
{
  "object_id": "node_runtime:20.19.1:linux:x86_64:glibc:abi-115",
  "resource_kind": "node_runtime",
  "name": "Node.js",
  "version": "20.19.1",
  "scope": "node",
  "compatibility_key": "node|20.19.1|abi-115|linux|x86_64|glibc",
  "dimensions": {
    "os": "linux",
    "arch": "x86_64",
    "libc": "glibc",
    "abi": "115"
  },
  "source": {
    "profile_ids": [],
    "evidence": []
  }
}
```

对象 identity 必须把会改变 compatibility 的维度放进去。

不能只用：

```text
软件名
```

或者：

```text
软件名 + major version
```

---

# 4. 第一阶段必须展开的 Object 类

以现有完整 Benchmark 文档定义的 ResourceKind 为准，至少完整覆盖：

```text
node_runtime
package_manager
pm_native_cache
dependency_view
repo_baseline
source_overlay
build_cache
test_transform_cache
native_binary_bundle
browser_binary
browser_process
browser_context
browser_profile
database_binary
database_daemon
database_clean_snapshot
database_private_layer
display_service
project_server
rootfs
system_toolchain
home_tmp_xdg
network_ports
filesystem_overlay
```

此外，虽然它们不是规范 ResourceKind，也必须单独 profiling：

```text
Raw CAS
local registry
artifact proxy
Git/HTTP artifact acquisition
discovery
resolution
normalize
scheduler/planner/control plane
task harness
failure recovery
contention
```

这些数据仍然保存，只是在后续 Scheduler edge 中是否计入要根据 `cost_class` 决定。

---

# 5. 64 个 SWE-smith RepoProfile 是真实 workload

优先使用 CTDP 已有数据：

```text
../CTDP/swe_smith_64_project_ids.txt
../CTDP/acceptance-out/inventory.json
../CTDP/acceptance-out/resolution.json
../CTDP/acceptance-out/normalized.json
../CTDP/acceptance-out/global/global_manifest.json
../CTDP/acceptance-out/prefetch.json
../CTDP/acceptance-out/warm-cache.json
../CTDP/acceptance-out/validation.json
```

从这 64 个 RepoProfile 中自动发现真实 object instance。

不要手写：

```text
这里有 MongoDB
这里有 Chromium
这里有 Node20
```

必须由 evidence 导出。

当前 Benchmark 文档中已经记录了真实 workload 基线，包括：

```text
64 RepoProfile
65 dependency roots
Node 18 / 20 / 22
npm / pnpm / Yarn / Bun
多个 PM exact version
registry / Git / HTTP / workspace / local_file / patch / unknown
TypeScript
Jest / Mocha / Vitest
Rollup / Webpack / Vite / Turbo
lifecycle scripts
native packages
monorepo/workspace
browser/GUI/test-driver
database
```

以代码实际读取 CTDP acceptance 数据为准，不要把文档中的数量硬编码进程序。

---

# 6. 还需要 synthetic coverage

64 profiles 是真实 workload，但不能覆盖所有我们设计上希望支持的 transition。

因此对象来源分两类：

```text
REAL
SYNTHETIC
```

REAL：

```text
从 64 profiles 实际发现
```

SYNTHETIC：

```text
为缺失但设计要求必须支持的 transition 创建最小 fixture
```

例如如果 64 profiles 没有同时覆盖：

```text
Firefox exact/switch
WebKit exact/switch
PostgreSQL version switch
MySQL version switch
Redis reset
Yarn linker mode switch
Node same-major exact-version switch
rootfs glibc/musl invalidation
```

则创建小型 fixture。

所有结果必须标：

```json
"workload_origin": "real"
```

或：

```json
"workload_origin": "synthetic"
```

绝不能混在一起不说明。

---

# 7. 每个 Object 都要测哪些状态

不是每种对象都有所有状态，但每个适用状态都必须测。

统一 transition class：

```text
network_cold
artifact_cold
process_cold
exact_hit
compatible_reuse
incompatible_switch
dirty_reset
failure_path
contention_path
```

例如 `browser_process`：

```text
process_cold
exact_hit
compatible_reuse
incompatible_switch
dirty_reset
failure_path
contention_path
```

例如 `Raw CAS blob`：

```text
network_cold
artifact_cold
exact_hit
failure_path
contention_path
```

例如 `source_overlay`：

```text
artifact_cold
exact_hit
dirty_reset
failure_path
contention_path
```

不适用的状态写：

```json
{
  "status": "not_applicable",
  "reason": "..."
}
```

不能默认为 0 ms。

---

# 8. 对于可版本切换对象，必须生成有向 Cost Matrix

所有版本/config 可能变化的对象，必须建立：

```text
from_object -> to_object
```

的有向成本矩阵。

不要假设：

```text
Cost(A -> B) == Cost(B -> A)
```

例如 Node：

```text
Node18 -> Node20
Node20 -> Node18
```

都测。

Package Manager：

```text
npm exact -> npm exact
pnpm9 -> pnpm9
pnpm9 -> pnpm10
pnpm10 -> pnpm9
Yarn Classic -> Yarn Berry
Yarn Berry -> Yarn Classic
Bun1.2 -> Bun1.3
Bun1.3 -> Bun1.2
```

Browser：

```text
revision A -> A
A -> B
B -> A
flags A -> flags B
profile A -> B
```

Database：

```text
MongoDB exact -> exact
MongoDB version A -> B
config A -> B
snapshot A -> B
```

Rootfs / libc：

```text
same rootfs
different rootfs
glibc -> musl
musl -> glibc
```

Build/Test cache：

```text
same key
repo change
config change
depview change
Node ABI change
tool version change
```

---

# 9. Cost 不能只有 wall_ms

最终一个 object transition 至少产生：

```json
{
  "from_object_id": "...",
  "to_object_id": "...",
  "transition_class": "incompatible_switch",
  "cost_class": "TRANSITION",
  "wall_ms": 0,
  "ready_ms": 0,
  "switch_ms": 0,
  "reset_ms": 0,
  "cleanup_ms": 0,
  "invalidation_ms": 0,
  "user_cpu_ms": 0,
  "system_cpu_ms": 0,
  "rss_mb": 0,
  "peak_rss_mb": 0,
  "read_bytes": 0,
  "write_bytes": 0,
  "network_bytes": 0,
  "files_created": 0,
  "inodes_created": 0,
  "cache_hit": false,
  "success": true,
  "timed_out": false,
  "reuse_safe": true,
  "pollution_check": "pass"
}
```

Scheduler 后续第一版主要查询：

```text
median wall_ms
```

但其他字段必须留下用于：

```text
diagnosis
capacity
contention
failure
paper analysis
```

---

# 10. 不要把 Invalidation 重复记账

例如：

```text
Node18 -> Node20
```

实际动作可能：

```text
Node runtime switch                25 ms
dependency view invalidation      400 ms
canvas rebuild                   2200 ms
Jest transform cache rebuild      300 ms
```

最终：

```text
Node runtime object
只拥有 25 ms
```

不能把全部：

```text
2925 ms
```

都记给 Node。

依赖关系要表示成：

```text
node_runtime change
      ↓ invalidates
dependency_view
native_binary_bundle
build_cache
test_transform_cache
```

然后对应子对象各自拥有自己的：

```text
invalidation/rebuild cost
```

这样 Transition Planner 后续才能组合，并且不 double count。

---

# 11. 必须生成 Invalidation Rules

从现有 Benchmark 文档的 compatibility/invalidation matrix 生成结构化规则。

至少覆盖：

```text
Node exact/ABI change
  -> dependency_view
  -> native_binary_bundle
  -> build_cache
  -> test_transform_cache

PM exact/major change
  -> pm_native_cache validation
  -> dependency_view

Yarn Classic/Berry
  -> cache
  -> node_modules/PnP
  -> unplugged native state

linker mode
  -> dependency_view
  -> unplugged/native view

lock hash
  -> dependency_view
  -> build/test cache

workspace config
  -> workspace links
  -> graph
  -> build cache

repo commit
  -> repo baseline
  -> overlay
  -> build/test cache

browser revision/flags/profile mode
  -> browser process/context/profile

DB version/config/schema
  -> daemon
  -> clean snapshot
  -> private DB layer

rootfs/libc/arch
  -> native binaries
  -> toolchain
  -> depview where platform-sensitive
```

输出：

```text
out/benchmarks/invalidation_rules.json
```

---

# 12. 测量协议

每个场景：

```text
warm-up: 2 次
measurement: 至少 7 次
```

如果单次超过 30 秒，可以允许：

```text
measurement: 5 次
```

但必须在结果里说明。

默认汇总：

```text
min
median
mean
P95
max
stddev
sample_count
success_count
failure_count
timeout_count
```

后续 Scheduler 默认使用：

```text
median
```

Robustness 可以查询：

```text
P95
```

---

# 13. Cold 的定义必须严格

统一沿用 Benchmark 文档：

## network_cold

```text
网络 artifact 不在 CAS / tool cache
需要真实联网
```

## artifact_cold

```text
Global CAS 已有
但 node-local cache/view 不存在
```

## process_cold

```text
binary 和需要的静态文件已经存在
但 process/daemon 没启动
```

## logical cold

```text
删除目标 object 的 node-local state
不主动清 OS page cache
```

## physical cold

```text
新 node / VM
或明确授权后清 page cache
```

主结果默认：

```text
logical cold
```

physical cold 单独报告，不能混入。

---

# 14. Ready condition 必须真实

不能把：

```text
fork/exec 成功
```

当成 ready。

Browser：

```text
process alive
+
可以创建 BrowserContext
+
创建 page
+
关闭成功
```

Database：

```text
daemon alive
+
health query 成功
+
最小事务成功
```

Project server：

```text
listen port
+
semantic health/request 成功
```

Xvfb：

```text
display socket 可连接
```

Dependency View：

```text
Node/PM 能 resolve/import/require 一个代表 package
```

Build/Test cache：

```text
实际 build/test 命令证明 cache hit
```

Local registry：

```text
packument GET
+
tarball GET
```

---

# 15. 全量 Benchmark Catalog 必须执行

第一阶段明确要求：

> 把 `NODELITE_COMPLETE_LATENCY_BENCHMARK.md` 中列出的 benchmark ID 全部纳入执行器。

包括：

```text
CTL-*
PRE-*
SRC-*
ART-*
CAS-*
REG-*
RUN-*
PM-*
PMC-*
DEP-*
INS-*
BLD-*
TST-*
BRW-*
GUI-*
DB-*
DBS-*
NAT-*
NTC-*
SYS-*
FS-*
NET-*
SRV-*
TSK-*
FAIL-*
CON-*
```

每个 ID 最终必须处于下面之一：

```text
measured
not_applicable
unsupported
manual_review
blocked
failed
```

不能未运行但不报告。

---

# 16. 软件/工具只在真实使用路径下测

不要因为某 package 出现在 `package.json` 就自动测它的 restart。

例如：

```text
axios
Redux
Zod
GraphQL
Mongoose
jsdom
```

如果只是普通 library：

```text
不创建独立 restart object
```

但它仍然通过：

```text
Raw package CAS
dependency_view
build/test cache
```

间接被测。

反过来，如果工具真实启动了：

```text
daemon
worker pool
watch process
server
native service
browser
DB
```

则创建独立 object。

---

# 17. Build / Test 对象必须根据真实 command 才启用

对：

```text
TypeScript
Babel
SWC
esbuild
Rollup
Webpack
Vite
Next.js
Nx
Turborepo
Jest
Vitest
Mocha
Karma
Nightwatch
Cypress
Playwright
```

区分：

```text
library present
```

和：

```text
actual executable/resource path used
```

只有后者才建立：

```text
build_cache
test_transform_cache
worker_pool
project_server
browser_process
```

对象。

但 benchmark catalog 中的 synthetic fixture 仍应覆盖设计要求的功能。

---

# 18. Native Object 必须包含 ABI / platform

至少处理：

```text
canvas
SWC
esbuild
sharp
sqlite3
Prisma engine
gRPC native transport
node-gyp output
```

identity 必须包含：

```text
package version
Node ABI
OS
arch
libc
toolchain hash
system library hash
build flags
```

---

# 19. Browser Object 要拆层

至少拆成：

```text
browser_binary
browser_process
browser_context
browser_profile
display_service
```

不能全部记成一个 Chromium。

同时必须做 pollution check：

```text
cookies
localStorage
IndexedDB
service workers
HTTP cache
open pages
workers
websockets
downloads
extensions
permissions
renderer children
ports
temp files
```

污染失败：

```text
reuse_safe = false
```

后续 Scheduler 不得走该 reuse path。

---

# 20. Database Object 要拆层

至少：

```text
database_binary
database_daemon
database_clean_snapshot
database_private_layer
connection/pool
```

需要测：

```text
cold daemon -> ready
warm attach
connection create
connection close
snapshot create
snapshot clone
private layer create
private reset/discard
migration
seed
same-version config switch
version switch
graceful shutdown
forced shutdown
```

---

# 21. Repo / Filesystem Object 要拆层

至少：

```text
repo_baseline
worktree
source_overlay
dependency_root_attach
filesystem_overlay
HOME
tmp
XDG
network namespace
port allocation
process tree
```

真正 Task A -> Task B 时，这些 cleanup 很可能是 transition 的主要组成部分之一。

---

# 22. Failure Path 也要有 cost

失败也是系统状态变化。

至少记录：

```text
time_to_first_error
time_to_final_classification
retry_count
cleanup_after_failure_ms
state_recovery_ms
dirty_resources
```

例如：

```text
npm peer conflict
invalid lockfile
artifact 404
CAS hash mismatch
missing PM/runtime
registry refused
platform mismatch
readiness timeout
hung build/test
disk full
OOM
stale process/port
pollution failure
scheduler state corrupt
```

---

# 23. Contention 也要测

至少：

```text
1 / 2 / 4 / 8 concurrent clients
```

适用项可以进一步测：

```text
16 / 32
```

覆盖：

```text
registry
CAS
PM cache
dependency view
worktree
BrowserContext
DB reset
port allocator
scheduler state lock
```

Scheduler 第一版默认 edge cost 可以仍然使用：

```text
single-worker median
```

---

# 24. 最终必须生成一个可直接查询的 Object Cost Database

核心产物：

```text
out/costdb/objects.json
out/costdb/object_costs.jsonl
out/costdb/object_cost_matrix.json
out/costdb/invalidation_rules.json
out/costdb/resource_summaries.json
out/costdb/failure_costs.json
out/costdb/contention_costs.json
```

同时生成：

```text
out/reports/object_costs.csv
out/reports/object_switch_matrix.csv
out/reports/object_latency_summary.csv
```

---

# 25. `objects.json`

保存所有 object identity。

例如：

```json
[
  {
    "object_id": "node_runtime:20.19.1:linux:x86_64:glibc:abi115",
    "resource_kind": "node_runtime",
    "name": "Node.js",
    "version": "20.19.1",
    "compatibility_key": "...",
    "workload_origin": "real",
    "profile_ids": ["..."]
  }
]
```

---

# 26. `object_costs.jsonl`

每一行是一条真实 observation。

例如：

```json
{
  "benchmark_id": "RUN-004",
  "resource_kind": "node_runtime",
  "from_object_id": "node18",
  "to_object_id": "node20",
  "transition_class": "incompatible_switch",
  "cost_class": "TRANSITION",
  "sample_index": 3,
  "wall_ms": 27.4,
  "ready_ms": 27.4,
  "success": true
}
```

---

# 27. `object_cost_matrix.json`

这是 Scheduler 最重要的输入。

结构示例：

```json
{
  "node_runtime": {
    "node18": {
      "node18": {
        "median_ms": 4.1,
        "p95_ms": 5.3,
        "transition_class": "exact_hit"
      },
      "node20": {
        "median_ms": 27.2,
        "p95_ms": 31.8,
        "transition_class": "incompatible_switch",
        "invalidates": [
          "dependency_view",
          "native_binary_bundle",
          "build_cache",
          "test_transform_cache"
        ]
      }
    }
  }
}
```

注意：

```text
matrix 里的 direct_ms
只包含这个 object 自己拥有的动作。
```

Invalidated object 的重建成本不直接加进这里。

---

# 28. `resource_summaries.json`

每个 object / transition 至少包含：

```text
sample_count
success_count
failure_count
timeout_count
min
median
mean
p95
max
stddev
reuse_safe
pollution_result
measurement_environment
```

---

# 29. 要生成一个一眼能看懂的总表

`object_latency_summary.csv` 至少包含：

```text
resource_kind
object_name
from_version/config
to_version/config
transition_class
cost_class
median_ms
p95_ms
invalidation_targets
reuse_safe
sample_count
workload_origin
benchmark_id
```

目标是打开 CSV 后可以直接看到类似：

```text
Node18 -> Node20
pnpm9 -> pnpm10
Chromium cold -> ready
Chromium warm context switch
MongoDB cold -> ready
MongoDB warm reset
depview A exact attach
depview A -> B rebuild
Vite cache exact hit
Vite cache invalidation
source overlay discard
HOME/tmp reset
```

所有数值必须来自真实实验，不能预填假数据。

---

# 30. Experiment Harness

实现一个统一 harness：

```text
setup
  ↓
force state_before
  ↓
verify state_before
  ↓
start timer
  ↓
perform exactly one owned action
  ↓
wait for semantic ready
  ↓
stop timer
  ↓
collect metrics
  ↓
pollution/isolation check
  ↓
cleanup
  ↓
verify cleanup
```

---

# 31. 时间测量

使用 monotonic high-resolution clock。

Python：

```python
time.perf_counter_ns()
```

或等价机制。

---

# 32. Benchmark 运行环境必须固定并记录

每次 run 固定或记录：

```text
CPU model
CPU core/quota
memory limit
OS
kernel
rootfs digest
filesystem backend
mount options
disk
Node version
PM version
repo commit
lock hash
network policy
concurrency
page-cache policy
container/namespace/VM
profiler commit/version
```

如果环境改变，不要静默合并成同一 cost summary。

建立：

```text
measurement_environment_id
```

---

# 33. Benchmark Registry

实现结构化 benchmark registry：

```python
BenchmarkSpec(
    id="BRW-007",
    resource_kind="browser_process",
    cost_class="TRANSITION",
    supported_states=[...],
    runner=...,
)
```

要求 `NODELITE_COMPLETE_LATENCY_BENCHMARK.md` 中所有 benchmark ID 都可以在 registry 中查询到。

启动时自动检查：

```text
document IDs - registered IDs
registered IDs - document IDs
```

并报 mismatch。

---

# 34. 分组运行，但最终全量覆盖

CLI 建议：

```bash
./nodelite-bench inventory
./nodelite-bench run --group control
./nodelite-bench run --group prep
./nodelite-bench run --group source
./nodelite-bench run --group artifact
./nodelite-bench run --group runtime
./nodelite-bench run --group pm
./nodelite-bench run --group dependency
./nodelite-bench run --group build
./nodelite-bench run --group test
./nodelite-bench run --group browser
./nodelite-bench run --group database
./nodelite-bench run --group native
./nodelite-bench run --group system
./nodelite-bench run --group filesystem
./nodelite-bench run --group network
./nodelite-bench run --group server
./nodelite-bench run --group failure
./nodelite-bench run --group contention
```

最终：

```bash
./nodelite-bench run-all   --profiles ../CTDP/swe_smith_64_project_ids.txt   --ctdp-out ../CTDP/acceptance-out   --out out/
```

---

# 35. 支持 Resume

实验可能很长。

必须支持：

```text
每个 benchmark/sample 完成后立即写 observation
resume
retry failed
rerun one benchmark
rerun one object
rerun one transition
force
```

例如：

```bash
./nodelite-bench run-one BRW-007 --object chromium-123
./nodelite-bench run-transition RUN-004 --from node18 --to node22
```

---

# 36. 不要求一台机器拥有所有依赖

如果本机不支持：

```text
WebKit
某数据库
某 GUI
某 rootfs backend
某 architecture
```

不要伪造结果。

写：

```text
blocked / unsupported
```

并生成：

```text
out/reports/environment_gaps.md
```

说明缺什么软件、权限、kernel capability、architecture 或 machine。

---

# 37. 正确性优先

任何 reuse benchmark 都必须和 fully isolated baseline 比较。

如果：

```text
test result
exit status
observable output
state checksum
```

不一致，则：

```text
reuse_safe = false
```

即使 latency 很低也不能用于 Scheduler。

---

# 38. 第一阶段 Definition of Done

必须满足：

## Coverage

```text
现有完整 Benchmark 文档中的所有 benchmark ID
都有明确状态
```

状态只能是：

```text
measured
not_applicable
unsupported
manual_review
blocked
failed
```

## Real workload

```text
64/64 SWE-smith RepoProfile 已被 inventory
64/64 有 object requirement/result accounting
```

## Objects

```text
所有真实发现的可切换 object
都有 object_id + compatibility_key
```

## Costs

每个适用的：

```text
cold
exact hit
compatible reuse
incompatible switch
dirty reset
```

都有 measurement 或明确阻塞原因。

## Version matrix

所有 workload 中实际出现的版本组合至少生成 full directed matrix，能实测的全部实测。

## Invalidation

每个 switch 的 invalidation targets 可追溯，且没有 double counting。

## Safety

每个 persistent reuse path 有 isolation/pollution 结论。

## Cost DB

以下文件均生成：

```text
out/costdb/objects.json
out/costdb/object_costs.jsonl
out/costdb/object_cost_matrix.json
out/costdb/invalidation_rules.json
out/costdb/resource_summaries.json
out/costdb/failure_costs.json
out/costdb/contention_costs.json
```

## Human-readable output

```text
out/reports/object_costs.csv
out/reports/object_switch_matrix.csv
out/reports/object_latency_summary.csv
out/reports/coverage.md
out/reports/environment_gaps.md
```

---

# 39. 第一阶段暂时不要做什么

这一阶段不要把主要时间花在：

```text
greedy scheduling speedup
lookahead
TSP
RL scheduler
multi-node placement policy optimization
```

可以保留接口。

当前目标是把：

```text
Cost(S -> T)
```

测准。

只有 Cost Database 稳定后，第二阶段 Scheduler 才消费这些数字。

---

# 40. Codex 完成后必须回复

不要只说 `implemented`。

必须返回：

1. 新增/修改文件。
2. Benchmark Registry 中注册了多少 benchmark ID。
3. 和 `NODELITE_COMPLETE_LATENCY_BENCHMARK.md` 的 ID coverage 是否 100%。
4. 64 profiles inventory 覆盖率。
5. 一共发现多少 object。
6. 按 ResourceKind 的 object 数量。
7. 一共测了多少 directed transitions。
8. measured / blocked / unsupported / failed 数量。
9. Node version switch matrix。
10. PM/version switch matrix。
11. Browser process/context/profile cost。
12. Database daemon/snapshot/private reset cost。
13. Dependency view cold/hit/switch cost。
14. Repo/overlay/HOME/tmp/network cleanup cost。
15. Build/Test cache hit/invalidation cost。
16. Native ABI invalidation/rebuild cost。
17. Rootfs/system/toolchain switch cost。
18. failure-path cost。
19. contention results。
20. isolation/pollution failures。
21. Cost DB 文件路径。
22. 最大的 20 个 transition cost。
23. 最值得复用的 20 个 object。
24. 当前仍缺测的 object/transition 及原因。

---

# 41. 最终目标

做完这一阶段后，我们应该能够直接查询：

```text
cost(node18 -> node20)
cost(pnpm9 -> pnpm10)
cost(yarn1 -> yarn4)

cost(depview-A cold)
cost(depview-A exact-hit)
cost(depview-A -> depview-B)

cost(chromium process cold)
cost(chromium warm context reset)
cost(chromium revision A -> B)

cost(mongodb cold)
cost(mongodb warm reset)
cost(mongodb snapshot A -> B)

cost(repo A -> repo B)
cost(source overlay discard)

cost(Vite cache hit)
cost(Vite invalidation)

cost(Jest worker cold)
cost(Jest transform-cache hit)

cost(canvas ABI rebuild)
cost(SWC ABI switch)

cost(rootfs A -> B)

cost(HOME/tmp cleanup)
cost(port/process cleanup)
```

而且每个 cost 都必须对应：

```text
真实 workload / synthetic fixture
+
明确版本
+
明确 compatibility key
+
明确 cold/warm state
+
重复实验
+
median/P95
+
污染检查
```

最终形成：

```text
Object Cost Database
        ↓
第二阶段 Transition Planner
        ↓
Task/Profile Edge Weight
        ↓
Greedy Scheduler
```

这就是第一阶段的完整验收目标。
