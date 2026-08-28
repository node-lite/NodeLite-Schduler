# NodeLite Task–Resource Graph 设计说明（给 Codex）

## 0. 目标

在现有 CTDP（Cross-Task Dependency Prefetcher）之上实现一个 **Resource-Aware Scheduler**。

CTDP 已经解决：

```text
很多 SWE-smith RepoProfile
        ↓
解析 Node / npm / pnpm / Yarn / Bun / lockfile
        ↓
全局依赖去重
        ↓
Global CAS + PM native cache
```

新的 Graph 模块解决：

```text
当前 Task 跑完以后，
下一个 Task 选谁最省“环境切换成本”？
```

核心不是“两个 Task 的 package 名称有多像”，而是：

> **从 Task A 的结束状态切到 Task B 的干净可执行状态，需要 reset、switch、reload、invalidate 多少资源？**

第一版调度使用 **greedy**，不做 lookahead。

---

# 1. 核心思想

不要直接把系统建成静态的 Task–Task similarity graph。

先建立：

```text
Task / RepoProfile  <---->  Resource
```

的二部图。

例如：

```text
Profile A ── Node20
          ├─ pnpm9
          ├─ Chromium123
          ├─ MongoDB7
          ├─ depview-A
          └─ vite-cache-A

Profile B ── Node20
          ├─ pnpm9
          ├─ Chromium123
          ├─ MongoDB7
          ├─ depview-B
          └─ jest-cache-B

Profile C ── Node22
          ├─ npm10
          ├─ PostgreSQL16
          └─ depview-C
```

Task–Task 的 weight **不是预先写死的**，而是根据当前资源状态动态计算。

例如当前刚跑完 A：

```text
Chromium123 已经 warm
MongoDB7 已经 warm
Node20 已经存在
pnpm9 cache 已经 warm
```

那么：

```text
A -> B
```

可能只需要：

```text
close old BrowserContext
reset MongoDB data
attach depview-B
reset HOME/tmp
```

而：

```text
A -> C
```

需要：

```text
切 Node20 -> Node22
停/切数据库 MongoDB -> PostgreSQL
dependency view 变化
native ABI 可能失效
build cache 可能失效
```

因此 A→B 的 transition cost 更低。

---

# 2. 这个 Graph 优化的目标

定义：

```text
TransitionCost(A -> B)
    = SwitchCost
    + ResetCost
    + ReloadCost
    + InvalidationCost
    + CleanupCost
    + RiskPenalty
```

然后：

```text
ColdCost(B)
```

表示 B 在完全冷环境中启动所需的资源准备成本。

定义：

```text
ReuseBenefit(A -> B)
    = ColdCost(B) - TransitionCost(A -> B)
```

第一版 Scheduler：

```text
在所有尚未执行且满足安全约束的候选中，
选择 ReuseBenefit 最大的下一个 Task/Profile。
```

不要使用：

```text
共同 dependency 数量
```

直接作为 weight。

---

# 3. 为什么 Resource 要独立建模

同一个软件名称不一定意味着可复用。

例如：

```text
Chromium 123 + flags=A
Chromium 123 + flags=B
```

可能不能直接共享同一个 process。

又例如：

```text
Node20 -> Node22
```

Node executable 的切换可能只有几十毫秒，但它可能导致：

```text
canvas native addon
SWC native binding
node_modules dependency view
build cache
```

全部失效。

所以：

> **SwitchCost 和 InvalidationCost 必须分开。**

Node 本身不要背上所有重建成本。

---

# 4. Resource 的四个层次

每个 Resource 都必须属于一个 scope。

## 4.1 Global Immutable Resource

整个训练期间全局只读，通常不影响单节点 Task 顺序。

例如：

```text
Raw package CAS
Node runtime binary
Browser binary
Database binary
Ubuntu/rootfs
system toolchain
repo object store
```

特点：

```text
prepare once
read-only
all tasks reuse
```

如果所有 CPU node 都拥有它，它不应该给 Task–Task edge 加很大的 weight。

---

## 4.2 Node-Local Warm Resource

只在某个 CPU node 上已经 warm。

例如：

```text
npm cache
pnpm store
Yarn cache
dependency view
build cache
test transform cache
OS page cache
repo checkout/worktree
```

这类 Resource：

```text
单节点场景：影响 Task 顺序
多节点场景：同时影响 placement
```

---

## 4.3 Persistent Process Resource

真正最重要的调度资源。

例如：

```text
Chromium process
Firefox process
WebKit process
MongoDB daemon
PostgreSQL daemon
Redis daemon
MySQL daemon
Xvfb
Nx daemon
Vite dev server（如果实际长期运行）
project application server
```

它们的：

```text
cold startup
ready
reset
warm attach
shutdown
```

时间应该实测。

---

## 4.4 Task/Rollout Private State

不能把旧 Task 的数据直接给新 Task。

例如：

```text
源码修改
BrowserContext
browser profile
DB private data
HOME
tmp
XDG cache
端口占用
background child process
writable filesystem overlay
```

这些 Resource 一般不提供 reuse benefit。

它们主要贡献：

```text
CleanupCost
RiskPenalty
```

---

# 5. Resource Registry

资源测试清单以：

```text
nodelite_resource_restart_benchmark_list.txt
```

为准。

其中：

```text
P0 = 第一优先级，必须测
P1 = 建议测，主要用于 invalidation / cache / native build
P2 = 纯 library，不单独给 restart weight
```

不要把 P2 中的：

```text
axios
Redux
Zod
GraphQL
Mongoose
jsdom
node-fetch
undici
...
```

都变成 scheduler node。

这些普通 JS library 已经由 CTDP package CAS 处理。

Graph 更关心：

```text
Node runtime
PM cache
dependency view
native addon
browser
database
repo snapshot
build/test cache
rootfs
filesystem
HOME/tmp
network/ports
```

---

# 6. 第一版必须支持的 Resource 类型

第一版至少实现以下 ResourceKind。

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

CTDP 已经存在的 Raw CAS 可以注册为 Resource，但它默认属于：

```text
global immutable
```

所以在单节点 scheduler 里通常不贡献 transition weight。

---

# 7. Resource 数据结构

实现类似以下 schema。

```json
{
  "resource_id": "browser-process:chromium:123:linux-x64:flags-abcd",
  "kind": "browser_process",
  "name": "Chromium",
  "version": "123.0.x",
  "compatibility_key": "chromium|123.0.x|linux-x64|flags-abcd",
  "scope": "node",
  "sharing_mode": "persistent_process_with_isolated_context",

  "cold_start_ms": 850,
  "warm_attach_ms": 32,
  "switch_ms": 0,
  "reset_ms": 41,
  "cleanup_ms": 12,
  "ready_ms": 870,
  "invalidation_ms": 0,

  "rss_mb": 310,
  "peak_rss_mb": 420,
  "disk_bytes": 280000000,
  "cache_bytes": 30000000,

  "can_persist_across_tasks": true,
  "reset_method": "close_old_browser_context",
  "safety_level": "conditional",
  "evidence": []
}
```

---

# 8. Version / Compatibility

每个 Resource 必须有：

```text
exact_version
compatibility_key
```

不要只记录软件名称。

例如 Node：

```text
Node 20.19.1
NODE_MODULE_VERSION / ABI
linux
x86_64
glibc
```

兼容 key：

```text
node|20.19.1|abi-X|linux|x86_64|glibc
```

Chromium：

```text
exact revision
OS/arch
launch flags
extensions
headless/headful
GPU mode
```

MongoDB：

```text
exact version
storage engine
config hash
auth mode
```

Dependency view：

```text
resolved lock hash
PM family/version
Node ABI
OS/arch/libc
install flags
workspace config
```

Build cache：

```text
repo@commit
dependency-view hash
tool version
config hash
important env vars
platform
```

---

# 9. Resource Transition 不是简单相同/不同

需要支持至少四种状态。

```text
1. exact_hit
2. compatible_reuse
3. incompatible_switch
4. cold_miss
```

例子：

## exact_hit

```text
当前：Chromium123 flags=A
下一个：Chromium123 flags=A
```

可以：

```text
reuse process
close old context
create new context
```

---

## compatible_reuse

```text
当前 MongoDB7 daemon
下一个仍然 MongoDB7
但 schema/data 不同
```

可以：

```text
reuse daemon
reset/replace database state
```

---

## incompatible_switch

```text
当前 Node20
下一个 Node22
```

需要：

```text
switch runtime
+
检查 dependency view/native addon/build cache 是否失效
```

---

## cold_miss

```text
当前 node 上没有 PostgreSQL16
下一个 Task 需要 PostgreSQL16
```

成本：

```text
cold load/start/readiness
```

---

# 10. Version Switch Matrix

某些 Resource 的 A→B 成本不是对称的，也不能只记录一个数字。

建议存：

```json
{
  "resource_kind": "node_runtime",
  "transitions": {
    "20.19.1->22.14.0": {
      "switch_ms": 28,
      "invalidates": [
        "dependency_view",
        "native_binary_bundle",
        "build_cache"
      ]
    }
  }
}
```

同样适用于：

```text
npm version
pnpm version
Yarn Classic/Berry
Bun
Chromium revision
MongoDB version
PostgreSQL version
rootfs/libc
```

---

# 11. Task / RepoProfile Requirement

每个 SWE-smith RepoProfile 生成 Resource Requirement。

例如：

```json
{
  "profile_id": "swesmith/trpc__trpc.2f40ba93",
  "resources": [
    {
      "kind": "node_runtime",
      "compatibility_key": "node|20.x|...",
      "required": true,
      "phase": "all"
    },
    {
      "kind": "package_manager",
      "compatibility_key": "pnpm|9.x|...",
      "required": true,
      "phase": "prepare"
    },
    {
      "kind": "dependency_view",
      "compatibility_key": "depview|sha256-...",
      "required": true,
      "phase": "all"
    },
    {
      "kind": "browser_process",
      "compatibility_key": "chromium|123|...",
      "required": true,
      "phase": "test",
      "access_mode": "new_browser_context"
    }
  ]
}
```

---

# 12. Task–Resource Graph

内部 graph 表示：

```text
Profile/Task node
Resource requirement node
```

不要真的把所有 `lodash@version` 都画进去。

package 层可以压缩成：

```text
dependency_view
pm_native_cache
native_binary_bundle
```

而 Raw CAS 保留在 CTDP 存储层。

---

# 13. 11,105 个 SWE-smith Task 如何处理

不要构建一个 11,105 × 11,105 的完全图。

SWE-smith 中大量 Task 共享 RepoProfile/environment。

第一版：

```text
11,105 Tasks
      ↓
按 RepoProfile / Resource Signature 聚合
      ↓
Environment Group
      ↓
每个 group 维护 task queue
```

例如：

```json
{
  "environment_group_id": "env-abc",
  "profile_id": "swesmith/axios__axios.ef36347f",
  "resource_signature": "sha256-...",
  "pending_tasks": 173
}
```

Scheduler 优先在 Environment Group 级别选下一个 group。

group 内再取一个 pending task。

---

# 14. 当前 Node State

Scheduler 不能只看“上一个 Task”。

必须维护真实的：

```text
NodeState
```

例如：

```json
{
  "node_id": "cpu-node-0",
  "warm_resources": [
    {
      "kind": "node_runtime",
      "compatibility_key": "node20..."
    },
    {
      "kind": "browser_process",
      "compatibility_key": "chromium123..."
    },
    {
      "kind": "database_daemon",
      "compatibility_key": "mongodb7..."
    },
    {
      "kind": "pm_native_cache",
      "compatibility_key": "pnpm9..."
    }
  ],
  "dirty_private_state": [
    "browser_context:A",
    "database_private_layer:A",
    "source_overlay:A",
    "home_tmp:A"
  ]
}
```

真正的 transition 是：

```text
NodeState S
    ↓
candidate Profile B
    ↓
Planner
    ↓
需要 reset 什么？
需要保留什么？
需要 switch 什么？
需要 cold load 什么？
```

---

# 15. Transition Planner

实现：

```text
plan_transition(node_state, target_profile)
```

输出：

```json
{
  "target": "profile-B",
  "actions": [
    {
      "action": "reset",
      "resource": "browser_context",
      "cost_ms": 35
    },
    {
      "action": "reuse",
      "resource": "chromium-process:123",
      "cost_ms": 0
    },
    {
      "action": "reset",
      "resource": "mongodb-private-layer",
      "cost_ms": 60
    },
    {
      "action": "attach",
      "resource": "depview-B",
      "cost_ms": 18
    }
  ],
  "transition_cost_ms": 113,
  "cold_cost_ms": 1020,
  "reuse_benefit_ms": 907
}
```

---

# 16. Invalidation Graph

Resource 之间存在依赖。

例如：

```text
Node ABI
   ↓
dependency view
   ↓
native addon bundle
   ↓
build/test cache
```

所以 Node20→Node22 不能只计算：

```text
Node switch = 25 ms
```

还必须传播：

```text
dependency view invalid
canvas/SWC/native outputs invalid
build cache invalid
```

建议用简单 dependency rules：

```json
{
  "parent_kind": "node_runtime",
  "change_dimension": "node_abi",
  "invalidates": [
    "dependency_view",
    "native_binary_bundle",
    "build_cache",
    "test_transform_cache"
  ]
}
```

类似规则：

```text
PM major version/change linker mode
    -> dependency_view

lockfile hash changes
    -> dependency_view
    -> build/test cache

repo commit changes
    -> build/test cache
    -> repo baseline

browser revision changes
    -> browser process/context/profile

DB version changes
    -> daemon
    -> clean snapshot
```

第一版用静态规则即可。

---

# 17. Cost Profiler

Graph 的 weight 不允许手填。

每个 P0/P1 Resource 根据：

```text
nodelite_resource_restart_benchmark_list.txt
```

实测。

至少记录：

```text
cold_start_ms
warm_start_or_attach_ms
switch_ms
reset_ms
cleanup_ms
ready_ms
invalidation_ms

RSS / peak RSS
disk/cache bytes
cold/warm network bytes
```

每个实验重复多次，推荐：

```text
warm-up 1-2 次
measurement >= 5 次
记录 median / P95 / min / max
```

Scheduler 默认使用：

```text
median
```

论文/报告同时保留：

```text
P95
```

---

# 18. Cold / Warm 定义必须一致

## Cold

例如 browser cold：

```text
process 不存在
对应可丢弃 cache 清空
binary 已经在全局 artifact store
```

注意：

> 全局预下载已经由 CTDP 完成，因此 cold startup 不等于重新联网下载所有 binary。

下载成本单独统计。

---

## Warm

例如 Chromium：

```text
browser process 已经运行
旧 BrowserContext 已关闭
创建新 BrowserContext
```

MongoDB：

```text
daemon 已经 ready
Task A 数据已清理
恢复/挂载 B 所需 clean state
```

Dependency view：

```text
对应 view 已存在
只需要 mount/link/attach
```

---

# 19. Cleanup 与污染验证

性能不是唯一条件。

任何 Persistent Resource 只有通过 isolation test 才允许 reuse。

例如 browser：

```text
cookies
localStorage
IndexedDB
service workers
cache
open pages
extensions
downloads
temporary profile files
```

数据库：

```text
databases/schemas
users/roles
transactions
locks
connections
extensions
configuration changes
background jobs
```

Project server：

```text
child processes
open ports
files
environment variables
in-memory singleton state
```

每个 Resource profiler 必须返回：

```text
reuse_safe = true/false/conditional
```

如果：

```text
reuse_safe = false
```

Scheduler 不允许用 warm reuse 路径。

---

# 20. RiskPenalty

第一版可以简单：

```text
safe        = 0
conditional = configurable positive penalty
unsafe      = INF
```

即：

```text
unsafe resource
```

直接禁止复用。

不要为了省 100 ms 牺牲 benchmark correctness。

---

# 21. Greedy Scheduler

第一版只做 greedy，不做 lookahead。

伪代码：

```python
while pending_profiles:
    candidates = []

    for profile in pending_profiles:
        plan = transition_planner.plan(node_state, profile)

        if not plan.safe:
            continue

        benefit = plan.cold_cost_ms - plan.transition_cost_ms
        candidates.append((benefit, profile, plan))

    benefit, target, plan = max(candidates)

    execute_transition(plan)
    run_one_task_from(target)
    update_node_state()
```

如果多个候选 benefit 相同，可以依次按：

```text
1. pending task count 多
2. transition cost 小
3. profile ID 稳定排序
```

作为 tie-breaker。

---

# 22. 不要做 Lookahead

当前版本明确不要：

```text
A->B->C 总路径优化
TSP
动态规划
beam search
RL scheduler
```

只做：

```text
current state
    ↓
next best candidate
```

以后再扩展。

---

# 23. Multi-Node 预留接口

第一版可以单 CPU node。

但数据模型必须能扩展：

```text
Task/Profile
      ↓
选择 CPU node
      ↓
该 node 当前 warm resources
      ↓
transition cost
```

未来目标：

```text
argmin(node, task)
TransitionCost(node_state[node], task)
```

所以 `NodeState` 必须显式带：

```text
node_id
```

Resource 的 scope 也必须区分：

```text
global
node-local
process
task-private
```

---

# 24. 与 CTDP 的接口

不要重写 CTDP。

Graph 模块从 CTDP 消费：

```text
profile_id
repo
commit
Node version
PM family/version
dependency root
resolved lockfile hash
normalized manifest
CAS state
native cache state
```

Graph 需要新增：

```text
Resource Discovery
Resource Profiler
Resource Registry
Task Resource Requirements
Node State
Invalidation Rules
Transition Planner
Greedy Scheduler
```

建议目录结构：

```text
src/nodelite_deps/
    ...
    graph/
        models.py
        resource_registry.py
        resource_discovery.py
        profiler.py
        compatibility.py
        invalidation.py
        node_state.py
        transition.py
        scheduler.py
        reports.py
```

名字可以按当前 repo 风格调整。

---

# 25. Graph 输出

至少生成：

```text
out/graph/resources.json
out/graph/resource_profiles.json
out/graph/profile_requirements.json
out/graph/environment_groups.json
out/graph/invalidation_rules.json

out/graph/node_state.json
out/graph/schedule.json
out/graph/transitions.jsonl

out/reports/resource_profile.md
out/reports/scheduler_summary.md
```

---

# 26. schedule.json

例如：

```json
{
  "scheduler": "greedy_resource_reuse_v1",
  "initial_state": "cold",
  "sequence": [
    {
      "step": 1,
      "profile_id": "A",
      "task_id": "...",
      "transition_cost_ms": 900,
      "cold_cost_ms": 900,
      "reuse_benefit_ms": 0
    },
    {
      "step": 2,
      "profile_id": "B",
      "task_id": "...",
      "transition_cost_ms": 105,
      "cold_cost_ms": 950,
      "reuse_benefit_ms": 845
    }
  ]
}
```

---

# 27. Baselines

验收和实验至少比较：

```text
FIFO / original order
Random
Greedy Resource Reuse
```

不要只比较 greedy 自己。

输出：

```text
total predicted transition cost
measured total environment time
resource cold-start count
resource reuse count
browser restart count
DB restart count
dependency-view rematerialization count
cache invalidation count
cleanup time
pollution failure count
```

---

# 28. Predicted Cost 与 Measured Cost 必须同时记录

Graph 是模型。

必须验证：

```text
predicted_transition_ms
vs
measured_transition_ms
```

每次 transition 记录：

```json
{
  "from": "A",
  "to": "B",
  "predicted_ms": 120,
  "measured_ms": 137,
  "error_ms": 17,
  "actions": []
}
```

最终报告：

```text
MAE
Median Absolute Error
P95 error
```

这样才能证明 weight 真的能代表实际切换成本。

---

# 29. 第一版重点测的 Resource

从资源清单中，优先实现：

```text
1. Node.js
2. npm / pnpm / Yarn Classic / Yarn Berry / Bun
3. repo baseline / source overlay
4. dependency view
5. PM-native cache
6. Vite / Webpack / Next / Nx / Turborepo 中真实存在的 daemon/cache
7. Jest / Vitest / Mocha transform/worker cache
8. Chromium / Firefox / WebKit + BrowserContext
9. Electron binary/process
10. Xvfb / D-Bus
11. MongoDB / PostgreSQL / MySQL / Redis
12. SQLite baseline DB
13. canvas / SWC / esbuild / sharp / Prisma / node-gyp native outputs
14. rootfs / libc / architecture / native toolchain
15. build cache / test transform cache
16. HOME / tmp / XDG
17. network namespace / ports
18. filesystem writable overlay
```

---

# 30. 明确不应该给独立 restart weight 的东西

普通 JS library：

```text
axios
Redux
Zod
GraphQL
Mongoose
node-fetch
undici
jsdom
happy-dom
Monaco
CodeMirror
ProseMirror
...
```

不要因为：

```text
Task A 和 Task B 都需要 axios
```

就给一条很大的 scheduler edge。

这些包的下载/缓存已经属于 CTDP。

它们只有在导致：

```text
dependency view 变化
native ABI 变化
build cache invalidation
```

时，才间接产生 transition cost。

---

# 31. CLI 建议

在现有 `nodelite-deps` 下增加：

```bash
./nodelite-deps graph-discover \
  --out acceptance-out

./nodelite-deps profile-resources \
  --out acceptance-out \
  --repeats 5

./nodelite-deps build-resource-graph \
  --out acceptance-out

./nodelite-deps schedule \
  --out acceptance-out \
  --policy greedy

./nodelite-deps validate-schedule \
  --out acceptance-out
```

也可以根据现有 CLI 风格调整。

---

# 32. 验收标准

## A. Resource Discovery

对固定 SWE-smith 64 RepoProfile：

```text
64/64 profile 都产生 Resource Requirement
无 profile 静默丢失
```

每个 requirement 必须有证据来源。

---

## B. Resource Profiling

所有当前 workload 真正出现的 P0 Resource：

```text
要么有测量值
要么明确标记 unsupported/manual_review
```

不能默认为 0。

---

## C. Compatibility

至少验证：

```text
Node same version hit
Node version switch
PM same/different version
lockfile hash change
browser same/different revision
DB same/different version
repo commit change
```

是否正确触发对应 invalidation。

---

## D. Transition Planner

准备几个人工 fixture：

```text
A = Node20 + Chromium + MongoDB
B = Node20 + Chromium + MongoDB
C = Node22 + PostgreSQL
```

必须得到：

```text
Cost(A->B) < Cost(A->C)
```

并能解释每一项 cost 来自哪个 Resource。

---

## E. Scheduler

比较：

```text
FIFO
Random
Greedy
```

要求至少报告：

```text
predicted total transition cost
measured total transition time
cold starts
warm reuses
invalidations
cleanup cost
```

不硬编码“greedy 必须快多少”。

---

## F. Correctness / Isolation

执行顺序改变以后：

```text
测试结果
task patch
evaluation result
```

必须与 baseline 隔离执行保持一致。

一旦发现污染：

```text
resource reuse 必须被禁用或降级
```

---

# 33. Codex 完成后必须回复

不要只回复“implemented”。

必须提供：

```text
1. 新增/修改了哪些文件
2. Resource 数据模型
3. 实际发现了哪些 Resource kinds
4. 64 个 RepoProfile 覆盖率
5. 每种 Resource 的版本分布
6. 哪些 P0 Resource 已实测
7. cold / warm / switch / reset / invalidation 测量摘要
8. compatibility/invalidation 规则
9. FIFO / Random / Greedy 的 predicted result
10. 实际 schedule validation result
11. predicted vs measured transition error
12. isolation/pollution test 结果
13. unsupported/manual-review Resource
14. 下一步 TODO
```

---

# 34. 一句话定义整个系统

CTDP 解决：

> **“这一批 Task 总共需要什么，把不可变 artifact 尽量只准备一次。”**

Resource Graph 解决：

> **“当前 CPU node 已经热着什么，下一个跑哪个 Task，才能用最小的 reset/switch/reload/invalidation 成本进入干净可执行状态。”**

两者组合：

```text
CTDP
  ↓
减少重复下载 / dependency materialization

Resource Profiler
  ↓
测真实切换成本

Task–Resource Graph
  ↓
描述每个 Profile 需要哪些可复用状态

Transition Planner
  ↓
计算 A -> B 的真实环境切换成本

Greedy Scheduler
  ↓
选择下一条最省环境成本的任务

Isolation Validator
  ↓
确保复用不会污染 benchmark correctness
```

这就是第一版完整 Graph 方案。
