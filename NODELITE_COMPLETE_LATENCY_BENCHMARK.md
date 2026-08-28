# NodeLite 完整资源延迟 Benchmark 计划

## 0. 文档定位

本文是 `20260828-nodelite_resource_restart_benchmark_list.txt` 的可执行扩展版，目标是回答：

> 对 NodeLite / SWE-smith 的真实工作流，哪些动作需要测 latency、在什么状态下测、哪些成本应进入 Scheduler edge、哪些只应作为准备期或诊断数据保留？

本文结合以下真实证据整理：

- `../CTDP/swe_smith_64_project_ids.txt`
- `../CTDP/acceptance-out/inventory.json`
- `../CTDP/acceptance-out/resolution.json`
- `../CTDP/acceptance-out/normalized.json`
- `../CTDP/acceptance-out/global/global_manifest.json`
- `../CTDP/acceptance-out/prefetch.json`
- `../CTDP/acceptance-out/warm-cache.json`
- `../CTDP/acceptance-out/validation.json`
- 本仓库原始 Resource Graph 设计和 benchmark 清单

本文不会把所有软件都变成 Scheduler Resource。每项 latency 必须标明成本归属：

| 成本类 | 含义 | 是否进入单步 transition |
|---|---|---|
| `PREP` | 一次性或低频准备成本 | 通常否，但决定首次准备时间 |
| `TRANSITION` | 从当前 NodeState 切到目标 Task 可执行状态 | 是 |
| `EXECUTION` | Task 自身执行成本 | 通常否，单独报告 |
| `CLEANUP` | Task 后 reset、清理和隔离验证 | 是 |
| `CONTROL` | Scheduler、Planner、Registry 等控制面开销 | 实测后计入 control overhead |
| `DIAGNOSTIC` | 失败、容量、兼容性和模型误差解释 | 不直接加权 |

表格中还会使用 `PLACEMENT`、`COMPAT`、`RISK` 标签。它们是分析维度，不是新的可相加时间项：placement/compatibility 检查本身归 `CONTROL` 或对应 action owner，实际切换归 `PREP`/`TRANSITION`，污染验证归 `CLEANUP`；`RiskPenalty` 只有在明确建模期望损失时才加入公式。一个 observation 可以带多个分析标签，但只能有一个 latency owner。

优先级：

| 优先级 | 定义 |
|---|---|
| `P0-64` | 固定 64-profile acceptance 已出现，且可能显著影响 transition |
| `P0` | 第一版必须支持，即使 64-profile 中没有完整触发 |
| `P1` | 建议测，主要用于 invalidation、native build、容量或失败解释 |
| `P2` | 只记录版本/证据，默认不给独立 restart weight |

---

## 1. 对原清单完整性的判断

原清单的方向正确，已经覆盖 Node、PM、browser、database、build/test cache、rootfs、private state 等核心概念，但还不是完整实验计划。

主要缺口：

1. 混合了可复用资源、软件命令、兼容维度和 Task-private state；这四类对象不能统一只测 `restart_ms`。
2. 漏掉了 CTDP 实际链路中的 discovery、lock resolution、parse、normalize、CAS、local registry、Git/HTTP artifact、native cache 和失败恢复延迟。
3. 漏掉了 64 profiles 中实际频繁出现的 Rollup、Karma、Cypress、workspace graph、lifecycle、codegen 等路径。
4. 没有统一规定 `network_cold`、`artifact_cold`、`process_cold`、`exact_hit`、`compatible_reuse`、`incompatible_switch`、`dirty_reset`、`failure` 和 `contention`。
5. 没有明确哪些数字进入 Scheduler edge，容易重复记账或把全局 CAS 命中误算成巨大 Task 相似度收益。

本文补齐这些缺口，并保留原设计的原则：普通 JS library 不建独立 restart node；真实 weight 必须来自实测；安全隔离优先于性能。

---

## 2. 64-profile 真实工作负载基线

以下数字来自当前 CTDP acceptance，不应硬编码进实现，但应作为 benchmark 设计证据。

### 2.1 Profile、root、Node 和 PM

| 项目 | 数量 |
|---|---:|
| RepoProfile | 64 |
| Dependency roots | 65 |
| Node 18 | 29 profiles |
| Node 20 | 26 profiles |
| Node 22 | 7 profiles |
| Node 未单独证明 | 2 profiles，来自 Bun image/profile |
| npm | 33 profiles / 34 roots |
| pnpm | 12 profiles / 12 roots |
| Yarn | 17 profiles / 17 roots |
| Bun | 2 profiles / 2 roots |

Node transition 至少覆盖全部方向：

```text
18->18  18->20  18->22
20->18  20->20  20->22
22->18  22->20  22->22
```

同 major 内还要区分 exact version、ABI-compatible 和 ABI-incompatible。

### 2.2 PM/version policy

当前 acceptance 实际产生 22 个 native-cache policy：

- npm 10.9.8；
- pnpm 9.x、10.x、11.x 的多个 exact version；
- Yarn Classic 1.22.21、1.22.22；
- Yarn Berry 3.2.3、3.8.7、4.0.2、4.9.1、4.10.3、4.12.0；
- Bun 1.2.18、1.3.7。

必须测同 PM 同 exact version、同 major 不同 version、跨 major、Yarn Classic/Berry、linker mode、Corepack/project-local activation 和 cache format compatibility。

### 2.3 Lockfile 与 resolution

| 分类 | Roots |
|---|---:|
| `authoritative_existing` | 10 |
| `existing_requires_resolution` | 44 |
| `missing_requires_resolution` | 8 |
| `unsupported_or_manual_review` | 3 |
| source/resolved lock unchanged | 51 |
| source/resolved lock changed | 14 |

实际失败包括 npm peer conflict、lockfile Git conflict markers、PM/version 不明确和 native resolver failure。

### 2.4 Artifact 与 dependency view

| Artifact type | Count |
|---|---:|
| `registry` | 32,477 |
| `git` | 10 |
| `http_tarball` | 6 |
| `local_file` | 914 |
| `workspace` | 306 |
| `patch` | 30 |
| `unknown` | 30 |

Dependency view benchmark 因而必须覆盖 registry、workspace link、local file、patch、Git、HTTP tarball、Yarn PnP/unplugged、platform optional package 和 unknown/manual-review protocol。

### 2.5 实际工具和动态下载证据

对 65 个 root 的 manifest 启发式扫描显示：

- TypeScript 46 profiles；Jest 26、Mocha 19、Vitest 12；
- Rollup 20、Webpack 15、Vite 7、Turbo 9；
- 26 profiles 有 `preinstall/install/postinstall/prepare`；
- 17 profiles 有明显 native package/tool evidence；
- 26 profiles 有 monorepo/workspace orchestration evidence；
- 7 profiles 有 database evidence；
- 23 profiles 有 browser/GUI/test-driver evidence。

这些是启发式 evidence，不等于每个工具都实际启动 persistent process；是否成为 Resource 必须由命令和 profiler 再确认。

动态验证捕获过：

```text
codeload.github.com
gist.github.com
electronjs.org
cdn.playwright.dev
playwright.download.prss.microsoft.com
playwright.azureedge.net
playwright-akamai.azureedge.net
playwright-verizon.azureedge.net
download.cypress.io
```

因此普通 registry install、Git fetch、lifecycle script、browser/Electron binary download、codegen/build、external miss detection 和 CAS warm replay 必须分别测量。

### 2.6 规范 ResourceKind 到 benchmark 的完整映射

下表把 Resource Graph 第一版规定的 24 个 `ResourceKind` 与本文的实测项逐一对齐。实现、observation 和报告必须使用这些规范名；一个 kind 可以对应多个动作，但不得因为动作分散在不同章节而漏测，也不得把同一动作在多个 kind 下重复记账。

| ResourceKind | 对应 benchmark | 主要需要测的 latency |
|---|---|---|
| `node_runtime` | `RUN-001`–`RUN-004` | Node.js binary resolve/load、进程启动、版本与 ABI switch |
| `package_manager` | `PM-001`–`PM-008` | npm、pnpm、Yarn Classic、Yarn Berry、Bun CLI 激活与切换 |
| `pm_native_cache` | `PMC-001`–`PMC-009` | 原生 cache/store 填充、校验、版本切换、并发与损坏恢复 |
| `dependency_view` | `DEP-001`–`DEP-020`、`INS-001`–`INS-010` | dependency tree materialize/attach/reset、linker 与 lifecycle |
| `repo_baseline` | `SRC-001`、`SRC-002`、`SRC-004`、`SRC-005`、`SRC-011` | immutable repo snapshot 获取、创建、定位、复用与校验 |
| `source_overlay` | `SRC-003`、`SRC-006`–`SRC-010`、`SRC-012`、`SRC-013` | writable overlay/worktree 创建、patch、reset、discard 与安全检查 |
| `build_cache` | `BLD-002`–`BLD-022` | compiler/bundler/monorepo cache attach、hit、invalidate、cleanup |
| `test_transform_cache` | `TST-001`–`TST-016` | transform cache、worker pool、test discovery 与 invalidation |
| `native_binary_bundle` | `NAT-001`–`NAT-010` | prebuild resolve/attach/load、ABI/libc/platform invalidation |
| `browser_binary` | `BRW-001`–`BRW-006` | Chromium、Firefox、WebKit、Electron resolve/download/load |
| `browser_process` | `BRW-007`–`BRW-010`、`BRW-016`–`BRW-019` | browser/Electron start-ready、attach、switch、shutdown |
| `browser_context` | `BRW-011`、`BRW-012`、`BRW-015` | BrowserContext/page create、ready、close、污染验证 |
| `browser_profile` | `BRW-013`、`BRW-014` | profile create/template/reset/delete |
| `database_binary` | `DB-001`–`DB-006` | MongoDB、PostgreSQL、MySQL、Redis、SQLite binary resolve/load |
| `database_daemon` | `DBS-001`–`DBS-004`、`DBS-011`–`DBS-013` | daemon start-ready、attach、connection、switch、shutdown |
| `database_clean_snapshot` | `DBS-005`、`DBS-006` | clean snapshot create、clone、restore |
| `database_private_layer` | `DBS-007`–`DBS-010` | task-private state create、migration/seed、discard/reset |
| `display_service` | `GUI-001`–`GUI-006` | Xvfb、D-Bus、GUI/GPU context、automation handshake |
| `project_server` | `SRV-001`–`SRV-010` | server start-ready、health、reload、reset、shutdown |
| `rootfs` | `SYS-001`–`SYS-004`、`SYS-009` | Ubuntu/Debian rootfs acquire、snapshot、mount、switch、unmount |
| `system_toolchain` | `NTC-001`–`NTC-012`、`SYS-005`–`SYS-008` | build-essential、Python、CMake、Rust、headers/libs、ca-certificates 准备与切换 |
| `home_tmp_xdg` | `FS-005`–`FS-009` | HOME/tmp/XDG/env create、populate、sanitize、reset |
| `network_ports` | `NET-001`–`NET-010` | namespace、DNS/proxy、port/socket、process tree 与 leak cleanup |
| `filesystem_overlay` | `FS-001`–`FS-004`、`FS-010` | overlay backend create/attach/discard、cache 与压力退化 |

规范外但必须测量的全局/控制面对象包括 Raw CAS、local registry、artifact proxy、discovery/resolution/normalize、Scheduler/Planner 和 task harness。它们有自己的 latency observation，但除非未来规范将其提升为新 `ResourceKind`，否则不能伪装成上述 24 类之一。特别是全局 immutable Raw CAS 的 acquisition/replay 主要记作 `PREP`；只有 node-local attach/materialization 才进入 transition。

---

## 3. 总成本模型与记账规则

```text
TransitionCost(S -> T)
    = SwitchCost
    + ResetCost
    + ReloadCost
    + InvalidationCost
    + CleanupCost
    + RiskPenalty
    + ControlOverhead

ReuseBenefit(S -> T)
    = ColdCost(T) - TransitionCost(S -> T)
```

记账规则：

1. Node switch 只记 runtime switch；由 ABI 引起的 dependency/native/build cache 重建记到被失效资源。
2. Raw CAS 全局可用时，不因两个 Task 使用同一 package 而给巨大 edge benefit。
3. Task assertion/test 运行时间不算 transition；只有 worker/process/cache 冷暖差进入复用模型。
4. Task-private 数据不产生 reuse benefit，只产生 reset、cleanup 和 risk。
5. 同一物理动作只能有一个 action owner，避免重复相加。
6. `ColdCost` 默认指全局 immutable artifacts 已准备、node-local warm state 不存在；网络重新下载另报。

---

## 4. 统一测量状态

| 状态 | 定义 | 示例 |
|---|---|---|
| `network_cold` | artifact/binary 不存在，需要联网 | 首次下载 Playwright Chromium |
| `artifact_cold` | 全局 CAS 有 artifact，node-local cache/view 不存在 | 从 CAS 首次 materialize pnpm view |
| `process_cold` | binary/cache 存在，process/daemon 不存在 | Chromium binary 本地存在但未启动 |
| `exact_hit` | compatibility key 完全相同 | Node exact ABI、Chromium flags 相同 |
| `compatible_reuse` | 父资源可复用，但要 reset/attach 子状态 | MongoDB daemon 相同，换 private DB layer |
| `incompatible_switch` | 同 kind 不兼容，要替换并传播 invalidation | Node 18->22、Yarn Classic->Berry |
| `dirty_reset` | 当前资源带 Task A 私有状态 | browser cookies、DB writes、HOME files |
| `failure_path` | miss/corrupt/timeout/conflict/unsupported | CAS SRI mismatch、npm peer conflict、404 |
| `contention_path` | 多 worker 并发争用 | 多 install 并发读 CAS/registry |

区分：

- `logical cold`：删除目标 Resource 的 node-local state，但不主动清 OS page cache；
- `physical cold`：新 node/VM，或在明确授权下清相关 page cache。

Scheduler 默认用可复现的 logical cold；physical cold 单独报告。

---

## 5. 通用测量契约

### 5.1 每次 observation 字段

```json
{
  "benchmark_id": "DEP-MATERIALIZE",
  "resource_kind": "dependency_view",
  "resource_id": "depview:profile:root:sha256-...",
  "profile_id": "swesmith/example__repo.01234567",
  "dependency_root": ".",
  "node_id": "cpu-node-0",
  "state_before": "artifact_cold",
  "transition": "cold_miss",
  "compatibility_key_before": null,
  "compatibility_key_after": "depview|...",
  "wall_ms": 0,
  "ready_ms": 0,
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
  "exit_code": 0,
  "timed_out": false,
  "reuse_safe": true,
  "pollution_check": "pass",
  "stdout_path": "...",
  "stderr_path": "...",
  "evidence": []
}
```

### 5.2 统计协议

每个场景 warm-up 1-2 次，正式 measurement 至少 5 次。默认调度成本用 median，同时报告 min、median、mean、P95、max、stddev。

失败和 timeout 不得静默删除，另报 success/failure/timeout count、failure detection latency 和 cleanup-after-failure latency。

### 5.3 每个样本固定记录的环境

- OS/rootfs digest、kernel、libc；
- CPU model、arch/features、CPU quota、memory limit；
- filesystem backend/mount options；
- Node exact version/ABI、PM exact version；
- repo full commit、lock/config hash；
- network policy、并发度、page-cache policy；
- container/namespace/VM 信息；
- profiler 版本。

### 5.4 Ready 不能只等于进程存在

- browser：能创建并关闭 context/page；
- database：health check 和最小事务成功；
- project server：端口健康检查和最小请求成功；
- Xvfb：display socket 可连接；
- dependency view：Node/PM 能 resolve/load 代表 package；
- build/test cache：实际命令证明 cache hit；
- local registry：packument 和 tarball GET 都成功。

---

## 6. 控制面与调度器 latency

| ID | 优先级 | 成本类 | 动作 | 处理方式 |
|---|---|---|---|---|
| `CTL-001` | P0 | CONTROL | 加载 resources/requirements/invalidation rules | 启动成本，不进入 profile edge |
| `CTL-002` | P0 | CONTROL | 11,105 tasks 聚合为 Environment Groups | 初始化成本 |
| `CTL-003` | P0 | CONTROL | 单轮 candidate enumeration | 每轮 overhead |
| `CTL-004` | P0 | CONTROL | 单 candidate compatibility matching | planner overhead |
| `CTL-005` | P0 | CONTROL | 单 candidate transition planning | planner overhead |
| `CTL-006` | P0 | CONTROL | invalidation graph 传播 | 不重复记资源重建时间 |
| `CTL-007` | P0 | CONTROL | greedy selection/tie-break | 每轮 overhead |
| `CTL-008` | P0 | CONTROL | NodeState 写盘、恢复、更新 | action 后实测 |
| `CTL-009` | P0 | CONTROL | action executor dispatch | 与 action 本身分开 |
| `CTL-010` | P1 | CONTROL | JSONL logging/report aggregation | 诊断 overhead |
| `CTL-011` | P1 | CONTROL | state lock/并发等待 | contention |
| `CTL-012` | P1 | CONTROL | 多节点 placement scoring | 未来接口 |

规模至少测试 64 profiles、synthetic 1,000 groups、11,105 tasks 聚合后的真实 groups，以及候选数 10/100/1,000/全量。

---

## 7. Discovery、Resolution、Normalize latency

这些主要是 PREP 成本，但决定首次准备、幂等重跑和失败恢复。

| ID | 优先级 | 动作 | 必测变体 |
|---|---|---|---|
| `PRE-001` | P0-64 | 读取/校验 profile IDs | cold FS、warm、重复运行 |
| `PRE-002` | P0-64 | official profile lookup | remote cold、local cache、missing ID |
| `PRE-003` | P0-64 | Dockerfile fetch/parse | cold/warm、remote failure |
| `PRE-004` | P0-64 | manifest/config/lock discovery | single root、多 root、large monorepo |
| `PRE-005` | P0-64 | source hash/fingerprint | small/large lock、cache hit |
| `PRE-006` | P0-64 | lock authority classification | strict/frozen/immutable/mutable/edited/missing |
| `PRE-007` | P0-64 | exact-commit temporary checkout | object cold/warm、submodules |
| `PRE-008` | P0-64 | manifest transformation replay | zero/single/workspace edits |
| `PRE-009` | P0-64 | npm lock-only resolution | existing/missing、peer conflict、legacy flags |
| `PRE-010` | P0-64 | pnpm lock-only resolution | v9/v10/v11、frozen/no-frozen |
| `PRE-011` | P0-64 | Yarn Classic resolution | existing/missing lock、node_modules cleanup |
| `PRE-012` | P0-64 | Yarn Berry update-lockfile | v3/v4、project-local、linker mode |
| `PRE-013` | P0-64 | Bun lock resolution | 1.2/1.3、format difference |
| `PRE-014` | P0-64 | source/resolved lock diff/hash/save | unchanged/changed/large |
| `PRE-015` | P0-64 | npm lock parse | v1/v2/v3、invalid JSON/conflict markers |
| `PRE-016` | P0-64 | pnpm lock parse | schema/version/workspace snapshots |
| `PRE-017` | P0-64 | Yarn Classic lock parse | registry/Git/file/link aliases |
| `PRE-018` | P0-64 | Yarn Berry lock parse | workspace/link/patch/virtual/locator |
| `PRE-019` | P0-64 | Bun lock parse | supported text/binary variants |
| `PRE-020` | P0-64 | normalized manifest generation | registry/Git/http/workspace/local/patch/unknown |
| `PRE-021` | P0-64 | global union/dedup/index | 1k/10k/102,051 references |
| `PRE-022` | P1 | reports/CSV generation | cold/warm、large JSON |
| `PRE-023` | P0 | stage reuse check | hit、fingerprint changed、output corrupt/missing |
| `PRE-024` | P0 | partial-stage resume | one/many/no failures |

同时报告 first run、identical second run、changed-input rerun、bytes read/write、network requests/bytes 和 failure detection。

---

## 8. Source、Repo、Filesystem latency

| ID | 优先级 | Scope | 动作 | 必测场景 | 成本类 |
|---|---|---|---|---|---|
| `SRC-001` | P0-64 | global/node | Git clone/fetch | network cold、object hit、shallow/full | PREP/PLACEMENT |
| `SRC-002` | P0-64 | node | exact commit checkout | object cold/warm、repo size | TRANSITION |
| `SRC-003` | P0-64 | node | worktree create/remove | first/repeated/concurrent | TRANSITION/CLEANUP |
| `SRC-004` | P0-64 | node | submodule init/update | cached/network cold/recursive | PREP/TRANSITION |
| `SRC-005` | P0 | node | baseline snapshot create/attach | tar/overlay/btrfs/tmpfs | PREP/TRANSITION |
| `SRC-006` | P0 | task | writable overlay create | tree size/inodes | TRANSITION |
| `SRC-007` | P0 | task | SWE task patch apply | clean/conflict/large patch | TRANSITION |
| `SRC-008` | P0 | task | dirty-tree scan | clean/few/many files | CLEANUP |
| `SRC-009` | P0 | task | overlay discard/reset | bytes/inodes/open handles | CLEANUP |
| `SRC-010` | P0-64 | node/task | dependency root attach | root/nested/two-root profile | TRANSITION |
| `SRC-011` | P1 | node | repo page-cache effect | logical/physical cold | DIAGNOSTIC |
| `SRC-012` | P1 | task | generated output cleanup | build/codegen/untracked | CLEANUP |
| `SRC-013` | P0 | task | symlink safety/cleanup | internal/escaping/broken | CLEANUP/RISK |

必须覆盖当前 root + `client` 双 dependency-root profile。

---

## 9. Artifact、CAS、本地 Registry、网络 latency

### 9.1 Upstream acquisition

| ID | 优先级 | 动作 | 必测场景 |
|---|---|---|---|
| `ART-001` | P0-64 | registry packument lookup | DNS/TLS cold、keep-alive、metadata hit |
| `ART-002` | P0-64 | registry tarball download | size buckets、retry、timeout、404、5xx |
| `ART-003` | P0-64 | GitHub codeload archive | exact commit、redirect、rate limit |
| `ART-004` | P0-64 | generic Git archive fallback | cached repo、unsupported host、SSH/HTTPS |
| `ART-005` | P0-64 | direct HTTP tarball | immutable/no-integrity/404 |
| `ART-006` | P0 | browser/Electron binary download | network cold、tool cache、CAS replay |
| `ART-007` | P1 | system package download | apt index/package cold/warm |
| `ART-008` | P0 | retry/backoff/final failure | refused、DNS、404、timeout |

### 9.2 CAS

| ID | 优先级 | 动作 | 必测场景 |
|---|---|---|---|
| `CAS-001` | P0-64 | artifact index lookup | cold/warm、32k artifacts |
| `CAS-002` | P0-64 | blob stat/existence | metadata warm、concurrent readers |
| `CAS-003` | P0-64 | blob read | 1KB/100KB/1MB/10MB/100MB |
| `CAS-004` | P0-64 | SHA-256 validation | size、page-cache cold/warm |
| `CAS-005` | P0-64 | SHA-512/SRI validation | valid/invalid、size |
| `CAS-006` | P0-64 | atomic write/rename/fsync | local/overlay、disk failure |
| `CAS-007` | P0-64 | metadata read/write | first/reuse、large references |
| `CAS-008` | P0-64 | duplicate fetch coalescing | 2/8/32 callers |
| `CAS-009` | P0 | corrupt hit detection/repair | zero/wrong hash/truncated |
| `CAS-010` | P1 | retention/garbage scan | 32k/100k/1M blobs |

### 9.3 Local artifact service

| ID | 优先级 | 动作 | 必测场景 |
|---|---|---|---|
| `REG-001` | P0-64 | registry startup-ready | cold/restart/port conflict |
| `REG-002` | P0-64 | unscoped packument GET | single/concurrent/hit |
| `REG-003` | P0-64 | scoped packument GET | encoding/single/concurrent |
| `REG-004` | P0-64 | local tarball GET | size/concurrency/page-cache |
| `REG-005` | P0-64 | lock/package URL rewrite | npm JSON、pnpm/Yarn text、large lock |
| `REG-006` | P0 | outbound proxy startup | cold/port conflict |
| `REG-007` | P0 | HTTP/CONNECT record-and-block | single/burst/concurrent |
| `REG-008` | P0 | expected miss classification | CAS/external/Git/unknown |
| `REG-009` | P0 | connection-refused recovery | Bun observed path |

报告 service overhead、first byte、full body、RPS、P50/P95/P99、bytes served 和 unexpected upstream requests。

---

## 10. Runtime、版本选择、进程 latency

| ID | 优先级 | Resource | Compatibility key | 必测动作 |
|---|---|---|---|---|
| `RUN-001` | P0-64 | Node binary | exact+ABI+OS/arch/libc | resolve/load、page-cache cold/warm |
| `RUN-002` | P0-64 | Node selector | selector+target | direct PATH、nvm、associated switch |
| `RUN-003` | P0-64 | Node process | Node key+env | spawn/exit、module loader startup |
| `RUN-004` | P0-64 | Node ABI switch | old/new ABI+native set | direct switch与invalidation分开 |
| `RUN-005` | P0-64 | Bun runtime | exact+platform | runtime/PM spawn、1.2<->1.3 |
| `RUN-006` | P1 | Deno | exact+cache+platform | spawn、compile/dependency cache |
| `RUN-007` | P1 | Java/JVM | JDK+JVM args | JVM、Gradle daemon attach/switch |
| `RUN-008` | P1 | Python | exact+venv/site hash | interpreter、venv switch |
| `RUN-009` | P1 | shell | bash/dash+env | process、login/non-login |
| `RUN-010` | P1 | environment block | PATH/env/config hash | build、sanitize、restore |

Node transition 必须测方向性、有/无 native addon，并将 runtime switch 与 downstream invalidation 分离。

---

## 11. PM、Native Cache、Dependency View latency

### 11.1 PM CLI/activation

| ID | 优先级 | 动作 | 必测变体 |
|---|---|---|---|
| `PM-001` | P0-64 | npm CLI startup | npm 10.9.8 + Node 18/20/22 |
| `PM-002` | P0-64 | pnpm CLI startup | exact v9/v10/v11 policies |
| `PM-003` | P0-64 | Yarn Classic startup | 1.22.21/1.22.22 |
| `PM-004` | P0-64 | Yarn Berry startup | project `.cjs`/Corepack、v3/v4 |
| `PM-005` | P0-64 | Bun PM startup | 1.2.18/1.3.7 |
| `PM-006` | P0-64 | Corepack enable/prepare | active/switch/offline cache |
| `PM-007` | P1 | global PM install | `npm install -g pnpm@...` cold/warm |
| `PM-008` | P0 | incompatible PM switch | cache format/linker changes |

### 11.2 Native cache/store

| ID | 优先级 | 动作 | 必测状态 |
|---|---|---|---|
| `PMC-001` | P0-64 | npm cache population | empty/partial/full/corrupt |
| `PMC-002` | P0-64 | pnpm store population | empty/partial/full、v9/v10/v11 |
| `PMC-003` | P0-64 | Yarn Classic cache | empty/partial/full、1.22 versions |
| `PMC-004` | P0-64 | Yarn Berry zip cache | v3/v4、global/local |
| `PMC-005` | P0-64 | Bun cache | 1.2/1.3、refused/retry |
| `PMC-006` | P0 | cache validation/index | hit/partial/corrupt |
| `PMC-007` | P0 | policy switch | exact/minor/major/Classic-Berry |
| `PMC-008` | P1 | disk pressure/eviction | normal/quota/inode pressure |
| `PMC-009` | P1 | concurrent readers/writers | 2/8/32 installs |

### 11.3 Dependency view

| ID | 优先级 | 动作 | 必测状态 |
|---|---|---|---|
| `DEP-001` | P0-64 | npm `node_modules` materialize | local registry、scripts off |
| `DEP-002` | P0-64 | pnpm linked view | store hit、scripts off |
| `DEP-003` | P0-64 | Yarn Classic view | cache hit、frozen lock |
| `DEP-004` | P0-64 | Yarn Berry node-modules | v3/v4、immutable/mutable |
| `DEP-005` | P0 | Yarn PnP view | `.pnp.cjs`、unplugged hit/miss |
| `DEP-006` | P0-64 | Bun view | cache hit/miss、1.2/1.3 |
| `DEP-007` | P0-64 | exact view reuse | same lock/PM/ABI/config |
| `DEP-008` | P0-64 | compatible attach/mount/link | existing view、新 overlay |
| `DEP-009` | P0-64 | incompatible switch | lock/PM/linker/ABI change |
| `DEP-010` | P0-64 | unmount/remove/reset | inode tree、open file |
| `DEP-011` | P0-64 | workspace links | 306 entries、monorepo size |
| `DEP-012` | P0-64 | local-file packages | 914 entries、copy/link/tar |
| `DEP-013` | P0-64 | patch apply | 30 entries、hit/fail/reapply |
| `DEP-014` | P0-64 | Git dependency | 10 network Git artifacts |
| `DEP-015` | P0-64 | HTTP tarball | 6 artifacts、404 |
| `DEP-016` | P0-64 | optional/platform filter | compatible/incompatible |
| `DEP-017` | P0 | unknown protocol | 30 unknown entries/manual review |
| `DEP-018` | P0 | view validation | require/import/bin links |
| `DEP-019` | P1 | concurrent creation | shared store/separate overlay |
| `DEP-020` | P1 | inode/page-cache effect | logical/physical cold |

### 11.4 Install/lifecycle semantics

| ID | 优先级 | 动作 | 必测状态 |
|---|---|---|---|
| `INS-001` | P0-64 | strict install | npm ci/frozen/immutable |
| `INS-002` | P0-64 | mutable install | plain/no-frozen/lock update |
| `INS-003` | P0-64 | scripts-disabled install | view/cache cold/warm |
| `INS-004` | P0-64 | `preinstall` | no-op/guard/tool setup |
| `INS-005` | P0-64 | `install` | native/download/no-op |
| `INS-006` | P0-64 | `postinstall` | bootstrap/browser/binary/codegen |
| `INS-007` | P0-64 | `prepare` | husky/build/preconstruct/workspace |
| `INS-008` | P0-64 | peer conflict | default/legacy/failure detection |
| `INS-009` | P0 | partial install cleanup | view/lock/process cleanup |
| `INS-010` | P0 | identical reinstall | warm hit/unnecessary writes |

---

## 12. Build、Codegen、Monorepo latency

工具只在实际命令、cache 或 daemon 被使用时成为 Resource；仅作为 dependency 出现时不自动加 edge weight。

| ID | 优先级 | Resource/动作 | 必测延迟 |
|---|---|---|---|
| `BLD-001` | P0-64 | generic PM script | shell+PM dispatch |
| `BLD-002` | P0-64 | TypeScript `tsc` | cold、tsbuildinfo hit、source/config/ABI invalidation |
| `BLD-003` | P1 | tsserver | ready、project load、reuse/reset、RSS |
| `BLD-004` | P0-64 | Babel | cold/cache/config invalidation |
| `BLD-005` | P0-64 | SWC | binding load/cache/ABI switch |
| `BLD-006` | P0-64 | esbuild | binary/service startup、build、platform switch |
| `BLD-007` | P0-64 | Rollup | graph cold/cache/plugin invalidation |
| `BLD-008` | P0-64 | Webpack | compiler、FS cache、watch、config invalidation |
| `BLD-009` | P0-64 | Vite | server ready、optimize-deps、depview/config invalidation |
| `BLD-010` | P0 | Next.js | dev/server ready、`.next/cache`、build invalidation |
| `BLD-011` | P0-64 | Nx | daemon、project graph、cache、reset |
| `BLD-012` | P0-64 | Turborepo | daemon若有、task graph、local cache |
| `BLD-013` | P1 | Gulp/Grunt | task graph、watch process |
| `BLD-014` | P0-64 | Lerna/preconstruct/manypkg | graph、bootstrap/link、cache |
| `BLD-015` | P1 | Changesets/Rush | graph/config change |
| `BLD-016` | P0-64 | make/bootstrap/setup | startup、incremental output、cleanup |
| `BLD-017` | P0-64 | generic codegen/generate | cold、output cache、schema/config invalidation |
| `BLD-018` | P1 | protobuf/protoc | binary/plugin/schema/output cache |
| `BLD-019` | P1 | Prisma generate/migrate | engine、schema、binary/cache |
| `BLD-020` | P0 | build cache attach | cold build/cache attach/verify |
| `BLD-021` | P0 | build cache invalidation | repo/depview/tool/config/env |
| `BLD-022` | P0 | watch process reset | handles/children/ports/RSS |

每项测 clean+cold、clean+warm、small patch+warm、config change、depview change、Node/ABI change和failed-build cleanup。

---

## 13. Test Runner、Worker、Transform Cache latency

| ID | 优先级 | Resource/动作 | 必测延迟 |
|---|---|---|---|
| `TST-001` | P0-64 | Jest | discovery、transform cold/warm、workers、shutdown |
| `TST-002` | P0-64 | Vitest | Vite server、transform、worker pool、watch mode |
| `TST-003` | P0-64 | Mocha | CLI/loader、discovery、workers |
| `TST-004` | P0 | AVA | worker pool、startup/reset |
| `TST-005` | P0-64 | Karma | server ready、browser launcher、cleanup |
| `TST-006` | P0-64 | Nightwatch | runner、driver/browser、shutdown |
| `TST-007` | P0-64 | Cypress | binary/cache check、launch、download miss |
| `TST-008` | P0-64 | Playwright | driver、browser/context、download miss |
| `TST-009` | P1 | Puppeteer | browser resolve、launch/context/close |
| `TST-010` | P1 | Selenium/WebDriver | driver、handshake、shutdown |
| `TST-011` | P0 | transform cache | Jest/Vitest/Babel/SWC/ts-jest |
| `TST-012` | P0 | worker pool | create/reuse/reset/leak |
| `TST-013` | P0 | test selection/discovery | full/target/changed files |
| `TST-014` | P1 | coverage | V8/Istanbul、cold/warm、cleanup |
| `TST-015` | P0 | failed/timeout cleanup | process/ports/tmp/coverage |
| `TST-016` | P0 | isolated comparison | reordered vs fresh result parity |

Test assertion execution记为 `EXECUTION`；worker/transform/browser/server 冷暖差才进入 environment reuse model。

---

## 14. Browser、Electron、Display、GUI latency

### 14.1 Binary/external artifact

| ID | 优先级 | 动作 | 必测状态 |
|---|---|---|---|
| `BRW-001` | P0-64 | Chromium binary resolve/load | system/Playwright revision、page-cache cold/warm |
| `BRW-002` | P0 | Firefox binary resolve/load | exact revision、page-cache cold/warm |
| `BRW-003` | P0 | WebKit binary resolve/load | Playwright revision、platform deps |
| `BRW-004` | P0-64 | Electron binary resolve/load | Electron/Chromium/Node ABI |
| `BRW-005` | P0-64 | browser/Electron download | network cold、tool cache、CAS replay、mirror fallback |
| `BRW-006` | P0-64 | browser install-deps check | packages present/missing |

### 14.2 Process/context/profile

| ID | 优先级 | 动作 | 必测状态 |
|---|---|---|---|
| `BRW-007` | P0-64 | Chromium cold start-ready | flags/headless/GPU/extensions/profile |
| `BRW-008` | P0 | Firefox cold start-ready | revision/flags/profile |
| `BRW-009` | P0 | WebKit cold start-ready | revision/flags |
| `BRW-010` | P0-64 | warm process attach | reconnect/health check |
| `BRW-011` | P0-64 | BrowserContext create | default/custom/storage state |
| `BRW-012` | P0-64 | BrowserContext close/reset | dirty pages/downloads/service workers |
| `BRW-013` | P0-64 | profile create | empty/template/large |
| `BRW-014` | P0-64 | profile reset/delete | cache/cookies/IndexedDB/workers |
| `BRW-015` | P0-64 | page/tab ready-close | blank/local app/blocked remote |
| `BRW-016` | P0 | browser process switch | flags/revision change |
| `BRW-017` | P0 | graceful/forced shutdown | normal/hung/child processes |
| `BRW-018` | P0-64 | Electron main/renderer ready | exact binary/config/profile |
| `BRW-019` | P0 | Electron reset/restart | window/renderer/main cleanup |

### 14.3 Display/IPC/GPU

| ID | 优先级 | 动作 | 必测状态 |
|---|---|---|---|
| `GUI-001` | P0 | Xvfb start-ready | display/screen/depth/port conflict |
| `GUI-002` | P0 | Xvfb reuse/reset/stop | stale clients/socket/lock |
| `GUI-003` | P0 | D-Bus session start-ready/reset | clean/reused/socket cleanup |
| `GUI-004` | P1 | GTK/system GUI library load | page-cache/rootfs switch |
| `GUI-005` | P1 | WebGL/GPU/SwiftShader context | context/shader cache/flags |
| `GUI-006` | P1 | automation protocol handshake | Playwright/CDP/WebDriver compatibility |

Browser reuse 每次必须测 cleanup latency，并验证 cookies、storage、IndexedDB、service workers、HTTP cache、open pages/workers/websockets、downloads、extensions、permissions、profile files、renderer children、ports 和 temp files。污染失败将 reuse 标成 false/conditional。

---

## 15. Database 与持久服务 latency

### 15.1 Engines

| ID | 优先级 | Resource | 必测延迟 |
|---|---|---|---|
| `DB-001` | P0-64 | MongoDB | binary、daemon ready、connect、reset、shutdown |
| `DB-002` | P0 | PostgreSQL | initdb/snapshot、ready、connect、reset、shutdown |
| `DB-003` | P0 | MySQL | datadir/snapshot、ready、auth、reset、shutdown |
| `DB-004` | P0 | Redis | ready、PING、FLUSH/reset、snapshot、shutdown |
| `DB-005` | P0-64 | SQLite | file clone/open、schema baseline、reset、reopen |
| `DB-006` | P0-64 | mongodb-memory-server | binary lookup/download、spawn、ready、cleanup |

### 15.2 State transitions

| ID | 优先级 | 动作 | 必测状态 |
|---|---|---|---|
| `DBS-001` | P0 | daemon cold start-ready | local binary、clean data dir |
| `DBS-002` | P0 | warm attach/health | exact compatible daemon |
| `DBS-003` | P0 | connection/pool create | auth/TLS cold、daemon warm |
| `DBS-004` | P0 | connection/pool close | idle/transaction/cursor |
| `DBS-005` | P0 | clean snapshot create | schema/seed size |
| `DBS-006` | P0 | snapshot clone/restore | copy/CoW/tmpfs/backend |
| `DBS-007` | P0 | task-private layer create | empty/template |
| `DBS-008` | P0 | private layer discard/reset | writes/locks/connections/jobs |
| `DBS-009` | P0 | migration | no-op/pending/failure rollback |
| `DBS-010` | P0 | seed/fixture load | size、transaction mode |
| `DBS-011` | P0 | same-version config switch | auth/extensions/config hash |
| `DBS-012` | P0 | DB version switch | daemon + snapshot invalidation |
| `DBS-013` | P0 | graceful/forced shutdown | normal/open handles/hung |

污染检查覆盖 databases/schemas/tables、users/roles、extensions、transactions/locks/cursors、connections、background jobs、config、WAL/binlog、sockets 和 seed data。

---

## 16. Native Binary、Addon、Toolchain latency

64 profiles 已出现 canvas、SWC、esbuild、sharp、sqlite3、node-gyp、gRPC；Dockerfile 还有 cairo/pango/jpeg/gif/rsvg、X11、libsecret、krb5、Python、make、g++、pkg-config。

### 16.1 Native artifacts

| ID | 优先级 | Resource | 必测延迟 |
|---|---|---|---|
| `NAT-001` | P0 | prebuild selection | exact platform/ABI hit、fallback、unsupported |
| `NAT-002` | P0 | native bundle attach/load | local cold/warm、page cache |
| `NAT-003` | P0-64 | canvas | prebuild/load、cairo stack、ABI rebuild |
| `NAT-004` | P0-64 | SWC | binding lookup/load、ABI/platform switch |
| `NAT-005` | P0-64 | esbuild | binary lookup/service startup |
| `NAT-006` | P0-64 | sharp/libvips | prebuild/download/load、ABI/libc |
| `NAT-007` | P0-64 | sqlite3/@vscode/sqlite3 | prebuild/load/build、ABI |
| `NAT-008` | P1 | Prisma engine | lookup/download/load/generate |
| `NAT-009` | P1 | gRPC/native transport | binding或JS fallback |
| `NAT-010` | P0 | native bundle invalidation | ABI、OS/arch/libc/toolchain |

### 16.2 Toolchain

| ID | 优先级 | 动作 | 必测延迟 |
|---|---|---|---|
| `NTC-001` | P0-64 | node-gyp configure | headers hit/miss、Python/compiler |
| `NTC-002` | P0-64 | node-gyp build | cold/incremental/ABI change |
| `NTC-003` | P0-64 | make/GCC/G++ | startup、cold/incremental build |
| `NTC-004` | P1 | Clang/LLVM | startup/build/tool switch |
| `NTC-005` | P1 | CMake configure | cold/cache/generator change |
| `NTC-006` | P1 | Ninja | cold/incremental/graph change |
| `NTC-007` | P1 | Rust/Cargo | registry/git cache、incremental、target |
| `NTC-008` | P1 | Python subprocess | interpreter/venv cold/warm |
| `NTC-009` | P1 | pkg-config | search path/rootfs switch |
| `NTC-010` | P1 | headers/libs discovery | present/missing/version |
| `NTC-011` | P1 | ccache/sccache if used | cold/warm/invalidate |
| `NTC-012` | P0 | failed native build cleanup | build dir/children/partial binary |

Native compatibility key 包含 package version、Node ABI、OS/arch/libc、toolchain hash、system libs、flags、Python/CMake/node-gyp versions。

---

## 17. Rootfs、System、Filesystem、Network latency

### 17.1 Rootfs/system

| ID | 优先级 | 动作 | 必测状态 | 成本类 |
|---|---|---|---|---|
| `SYS-001` | P0 | image/rootfs acquisition | remote/local | PREP |
| `SYS-002` | P0 | unpack/snapshot | cold/reuse | PREP |
| `SYS-003` | P0 | mount/attach | exact/switch | TRANSITION |
| `SYS-004` | P0 | unmount/reset | clean/dirty/open handle | CLEANUP |
| `SYS-005` | P1 | apt index refresh | network cold/hit | PREP |
| `SYS-006` | P1 | apt package install | present/missing/diff | PREP |
| `SYS-007` | P1 | system library load | GUI/cairo/OpenSSL/page-cache | DIAGNOSTIC |
| `SYS-008` | P1 | trust store/TLS init | hash switch/first TLS | COMPAT |
| `SYS-009` | P1 | libc/rootfs switch | glibc/musl + invalidation | TRANSITION |
| `SYS-010` | P1 | arch/CPU placement | x86/arm/features | PLACEMENT |
| `SYS-011` | P1 | kernel/cgroup/seccomp check | host capabilities | PLACEMENT |

### 17.2 Filesystem/private environment

| ID | 优先级 | 动作 | 必测状态 |
|---|---|---|---|
| `FS-001` | P0 | overlay/tmpfs/btrfs layer create | backend/tree/inodes |
| `FS-002` | P0 | mount/attach | cold/warm/concurrent |
| `FS-003` | P0 | discard/unmount | clean/dirty/open FD |
| `FS-004` | P1 | page/inode/dentry cache | logical/physical cold |
| `FS-005` | P0 | HOME create/populate | empty/template/selective cache |
| `FS-006` | P0 | HOME cleanup/reset | size/hidden/open FD |
| `FS-007` | P0 | tmp cleanup/reset | file count/size/socket/lock |
| `FS-008` | P0 | XDG reset | selective retain/purge |
| `FS-009` | P0 | environment/PATH restore | exact/changed/secrets |
| `FS-010` | P1 | disk/inode pressure | normal/near-full/recovery |

### 17.3 Network、ports、process tree

| ID | 优先级 | 动作 | 必测状态 |
|---|---|---|---|
| `NET-001` | P0 | network namespace create | cold/reuse/policy switch |
| `NET-002` | P0 | namespace teardown | idle/open sockets/process |
| `NET-003` | P0 | port allocate/reserve | free/contention/exhaustion |
| `NET-004` | P0 | stale socket cleanup | normal/TIME_WAIT/hung listener |
| `NET-005` | P0 | DNS/proxy policy setup | offline/local/external |
| `NET-006` | P0 | proxy switch/reset | env + inherited process state |
| `NET-007` | P1 | first DNS/TLS | cold/warm pool |
| `NET-008` | P0 | process tree enumerate/terminate | normal/deep/orphan/daemonized |
| `NET-009` | P0 | TERM->KILL escalation | clean/hung |
| `NET-010` | P0 | FD/port/process leak validation | baseline vs after task |

Git、curl、wget、ffmpeg、jq、OpenSSL/GnuPG、protoc、Corepack 和 shell utilities 默认记 PREP/EXECUTION；只有产生可复用 cache/process 时才升级为 Resource。

---

## 18. Project Server 与通用 Persistent Process latency

| ID | 优先级 | 动作 | 必测状态 |
|---|---|---|---|
| `SRV-001` | P0 | server cold start | repo/depview/config key |
| `SRV-002` | P0 | readiness probe | port + semantic request |
| `SRV-003` | P0 | warm attach/health | exact hit |
| `SRV-004` | P0 | compatible reset | request/session/memory state |
| `SRV-005` | P0 | config/env/command switch | incompatible restart |
| `SRV-006` | P0 | source-change reload | HMR/watch/incremental build |
| `SRV-007` | P0 | graceful shutdown | normal/open connection/job |
| `SRV-008` | P0 | forced cleanup | hung/children/ports |
| `SRV-009` | P0 | pollution test | singleton/files/ports/env/sessions |
| `SRV-010` | P1 | repeated-reuse memory trend | RSS/FD over many tasks |

只有实际长期运行并通过 isolation test 的 Vite/Next/Webpack/Nx/project server 才能设置 `can_persist_across_tasks=true`。

---

## 19. Task Harness、Evaluation、Cleanup latency

| ID | 优先级 | 成本类 | 动作 |
|---|---|---|---|
| `TSK-001` | P0 | TRANSITION | 创建 rollout-private workspace |
| `TSK-002` | P0 | TRANSITION | 注入 task metadata/patch/test selection |
| `TSK-003` | P0 | EXECUTION | evaluation harness startup |
| `TSK-004` | P0 | EXECUTION | task command/test execution |
| `TSK-005` | P0 | EXECUTION | result/patch/log collection |
| `TSK-006` | P0 | CLEANUP | terminate process tree |
| `TSK-007` | P0 | CLEANUP | discard source/FS overlay |
| `TSK-008` | P0 | CLEANUP | reset HOME/tmp/XDG |
| `TSK-009` | P0 | CLEANUP | reset browser context/profile |
| `TSK-010` | P0 | CLEANUP | reset DB layer/connections |
| `TSK-011` | P0 | CLEANUP | release ports/network namespace |
| `TSK-012` | P0 | CLEANUP | verify no process/FD/socket/file leak |
| `TSK-013` | P0 | DIAGNOSTIC | compare fully isolated baseline |
| `TSK-014` | P0 | CONTROL | update NodeState after success/failure/timeout |

调序后 test result、task patch、evaluation score、exit status 和 observable output 必须与隔离 baseline 一致；不一致时禁止相关 reuse path。

---

## 20. Failure-path latency

| ID | 优先级 | 场景 | 需要记录 |
|---|---|---|---|
| `FAIL-001` | P0-64 | npm peer conflict | detect/log/cleanup/fallback |
| `FAIL-002` | P0-64 | invalid/conflicted lock | parse failure/manual review |
| `FAIL-003` | P0-64 | artifact 404 | retries/final detect/cleanup |
| `FAIL-004` | P0-64 | CAS integrity mismatch | detect/quarantine/refetch |
| `FAIL-005` | P0-64 | missing PM/runtime | lookup/install/unsupported |
| `FAIL-006` | P0-64 | local registry refused | retry/no-fallback/cleanup |
| `FAIL-007` | P0-64 | platform optional mismatch | skip/no false failure |
| `FAIL-008` | P0 | readiness timeout | timeout/kill/port cleanup |
| `FAIL-009` | P0 | hung install/build/test | escalation/partial cleanup |
| `FAIL-010` | P0 | disk/inode full | detect/atomicity/recover |
| `FAIL-011` | P0 | cgroup OOM | detect/state reconcile |
| `FAIL-012` | P0 | stale process/port | detect/cleanup/retry |
| `FAIL-013` | P0 | pollution failure | validate/disable reuse |
| `FAIL-014` | P1 | scheduler state corrupt | recover/rebuild |

记录 time-to-first-error、time-to-final-classification、retry count、cleanup-after-failure、state recovery 和 dirty resources。

---

## 21. Contention 与容量 latency

| ID | 优先级 | 场景 |
|---|---|---|
| `CON-001` | P0 | 1/2/4/8 concurrent registry clients |
| `CON-002` | P0 | same CAS blob concurrent fetch/read |
| `CON-003` | P0 | multiple PM cache writers |
| `CON-004` | P0 | multiple dependency views |
| `CON-005` | P1 | concurrent worktrees/checkouts |
| `CON-006` | P1 | concurrent BrowserContexts |
| `CON-007` | P1 | DB connections/private resets |
| `CON-008` | P1 | CPU/memory/disk saturation |
| `CON-009` | P1 | port allocator contention |
| `CON-010` | P1 | scheduler state lock contention |

报告 throughput、queue wait、service time、P50/P95/P99、fairness、failure rate 和 saturation point。

---

## 22. Compatibility 与 invalidation latency matrix

| Parent change | 直接动作 | 失效资源 | 必测重建 latency |
|---|---|---|---|
| Node exact/ABI | runtime switch | depview/native/build/test cache | view + native + caches |
| PM exact/major | PM switch | native cache/depview | validate/populate/materialize |
| Yarn Classic/Berry | PM/linker switch | cache/node_modules/PnP | full view switch |
| linker mode | mode switch | depview/unplugged native | view regeneration |
| lock hash | view switch | depview/build/test cache | materialize/invalidate |
| workspace config | graph/view switch | links/graph/build cache | graph + links + cache |
| repo commit | baseline switch | overlay/build/test cache | checkout/overlay/cache |
| build config/env | config switch | cache/server/watch | invalidate/restart |
| browser revision | process switch | context/profile/driver | restart/reset |
| browser flags/extensions | process key switch | process/context/profile | restart/reset |
| DB exact version | daemon switch | snapshot/private layer | daemon + snapshot |
| DB config/auth/extensions | config switch | connection/snapshot | restart/reset/connect |
| rootfs/libc/arch | system switch/placement | runtime/native/browser/DB | attach + invalidation |
| network/proxy policy | namespace/env switch | connection pools | reset/reconnect |

所有 matrix 都测 A->B 与 B->A，不假定对称。

---

## 23. 默认不单独给 restart weight 的对象

普通 libraries 如 axios、Redux、Zod、GraphQL、Mongoose、node-fetch、undici、jsdom、happy-dom、Monaco、CodeMirror、ProseMirror、Sequelize、TypeORM、Zustand、Pinia、Drizzle、supertest，默认只进入 normalized dependency view。

它们可间接改变 depview、build/test cache、module initialization、browser bundle 或 DB connection。只有 profiler 证明存在显著、可复用且安全的独立状态时，才升级为 Resource。

CPU arch/features、libc、kernel capabilities、trust-store hash、system package-set hash通常是 compatibility/placement 维度，不独立拥有 restart weight；成本由被失效资源体现。

---

## 24. 第一版最小可交付顺序

### Phase 1：复用 CTDP，建立基础

1. Node 18/20/22 switch/spawn/ABI matrix；
2. npm/pnpm/Yarn Classic/Yarn Berry/Bun CLI；
3. PM cache exact/cold/partial/corrupt；
4. depview cold/exact attach/switch/reset；
5. repo checkout/worktree/source overlay；
6. CAS read/verify、local registry；
7. HOME/tmp/XDG、ports、process cleanup；
8. scheduler/planner/state overhead。

### Phase 2：64 profiles 中明确出现的重资源

1. TypeScript、Babel、SWC、esbuild、Rollup、Webpack、Vite、Nx、Turbo；
2. Jest、Vitest、Mocha、Karma、Nightwatch、Cypress、Playwright；
3. Chromium、Electron、Xvfb/D-Bus；
4. MongoDB、PostgreSQL client path、Redis、MySQL、SQLite；
5. canvas、sharp、sqlite3、node-gyp/native bundle；
6. lifecycle/build/codegen；
7. Git/submodule/codeload 和 external binary replay。

### Phase 3：设计要求但 64 profiles 中证据较弱

1. Firefox、WebKit；
2. PostgreSQL/MySQL/Redis 完整 daemon snapshot matrix；
3. Next.js、AVA、Deno、Java/Gradle；
4. Rust/Cargo、CMake/Ninja、Prisma；
5. rootfs backend、multi-node placement、physical page-cache cold。

任何实际出现的 P0：要么有测量，要么明确 unsupported/manual_review，不能默认为 0。

---

## 25. 推荐输出

```text
out/graph/resources.json
out/graph/profile_requirements.json
out/graph/environment_groups.json
out/graph/invalidation_rules.json

out/benchmarks/observations.jsonl
out/benchmarks/resource_summaries.json
out/benchmarks/version_switch_matrix.json
out/benchmarks/failure_paths.json
out/benchmarks/contention.json

out/graph/node_state.json
out/graph/schedule.json
out/graph/transitions.jsonl

out/reports/resource_latency_matrix.csv
out/reports/resource_profile.md
out/reports/scheduler_summary.md
out/reports/predicted_vs_measured.json
out/reports/isolation_failures.json
out/reports/manual_review_resources.json
```

每个 resource summary 输出 sample/success/failure counts、min/median/mean/P95/max/stddev、reuse safety 和 evidence。

---

## 26. Scheduler baseline 与验收

至少比较 FIFO/original、多个固定 seed 的 Random、Greedy Resource Reuse。

同时报告：

- predicted/measured total transition；
- control-plane overhead；
- cold/exact/compatible/incompatible counts；
- depview rematerialization、native rebuild；
- browser restart/context reset；
- DB restart/snapshot reset；
- build/test cache invalidation；
- cleanup/failure recovery；
- pollution failure和task-result mismatch。

每次 transition 同时记录 predicted、measured、control overhead、error、actions、invalidations、cleanup checks。最终计算 MAE、Median Absolute Error、P95 Absolute Error、bias，并按 ResourceKind 和 transition class 分解。

验收要求：

1. 64/64 profiles 都有 Resource Requirement；
2. 所有实际 P0 有测量或 manual review；
3. predicted cost 能追溯到 observation；
4. action 不重复记账；
5. FIFO/Random/Greedy 都有 predicted/measured；
6. 调序后的 patch/test/evaluation 与隔离 baseline 一致；
7. pollution failure 会禁用或降级 reuse；
8. failure/timeout/external miss 不会静默删除。

---

## 27. 一句话总结

完整 latency benchmark 不只是测“软件重启多久”，而是测：

> 从一个真实、可能带脏状态的 NodeState，切换到目标 SWE-smith Task 的干净可执行状态时，profile discovery、artifact、runtime、PM cache、dependency view、repo、build/test cache、browser、database、native toolchain、filesystem、network、cleanup、failure recovery 和 scheduler control-plane 分别花了多少时间；哪些状态能安全复用，哪些变化会传播 invalidation，模型预测与真实耗时相差多少。
