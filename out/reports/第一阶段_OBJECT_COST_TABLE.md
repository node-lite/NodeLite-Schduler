# 第一阶段 Object Cost 计算表

> 所有数值均来自本机实际 observation；缺失能力不填 0，而在 coverage/environment gaps 中标注。Scheduler 查询默认使用 `median_ms`，稳健策略可查询 `p95_ms`。`direct_ms` 只包含 object 自己拥有的动作，不包含 invalidated object 的重建时间。

## 总览

- Measured transition summaries: 736
- Catalog status: `blocked`=11, `manual_review`=7, `measured`=265, `not_applicable`=1, `unsupported`=32
- Objects by kind: `artifact_acquisition`=7, `browser_binary`=3, `browser_context`=3, `browser_process`=3, `browser_profile`=3, `build_cache`=97, `contention`=10, `control_plane`=12, `database_binary`=5, `database_clean_snapshot`=5, `database_daemon`=4, `database_private_layer`=5, `dependency_view`=90, `discovery_resolution`=18, `display_service`=3, `failure_recovery`=12, `filesystem_overlay`=1, `home_tmp_xdg`=2, `local_registry`=9, `native_binary_bundle`=22, `network_ports`=1, `node_runtime`=7, `package_manager`=24, `pm_native_cache`=24, `project_server`=3, `raw_cas`=32502, `repo_baseline`=64, `rootfs`=16, `source_overlay`=77, `system_toolchain`=1, `task_harness`=1, `test_transform_cache`=80

## 完整 Cost 表

| Benchmark | Resource kind | Object / transition | Class | Cost class | Median ms | P95 ms | Samples | Reuse safe | Invalidates |
|---|---|---|---|---|---:|---:|---:|---|---|
| `ART-001` | `artifact_acquisition` | cold → v1 (registry packument lookup \| DNS/TLS cold、keep-alive、metadata hit) | `network_cold` | `PREP` | 42.556 | 45.410 | 7 | true | — |
| `ART-002` | `artifact_acquisition` | cold → v1 (registry tarball download \| size buckets、retry、timeout、404、5xx) | `network_cold` | `PREP` | 39.423 | 43.722 | 7 | true | — |
| `ART-003` | `artifact_acquisition` | cold → v1 (GitHub codeload archive \| exact commit、redirect、rate limit) | `network_cold` | `PREP` | 313.844 | 588.370 | 7 | true | — |
| `ART-004` | `artifact_acquisition` | cold → v1 (generic Git archive fallback \| cached repo、unsupported host、SSH/HTTPS) | `network_cold` | `PREP` | 764.821 | 1175.459 | 7 | true | — |
| `ART-005` | `artifact_acquisition` | cold → v1 (direct HTTP tarball \| immutable/no-integrity/404) | `network_cold` | `PREP` | 761.638 | 1169.992 | 7 | true | — |
| `ART-006` | `artifact_acquisition` | cold → v1 (browser/Electron binary download \| network cold、tool cache、CAS replay) | `artifact_cold` | `PREP` | 0.002 | 0.004 | 7 | true | — |
| `ART-008` | `artifact_acquisition` | cold → v1 (retry/backoff/final failure \| refused、DNS、404、timeout) | `network_cold` | `PREP` | 0.103 | 0.114 | 7 | true | — |
| `BLD-001` | `build_cache` | cold → v1 (npm script dispatch) | `process_cold` | `TRANSITION` | 251.842 | 268.755 | 7 | true | — |
| `BLD-002` | `build_cache` | cold → 7.0.2 (typescript) | `artifact_cold` | `TRANSITION` | 525.485 | 555.622 | 7 | true | — |
| `BLD-002` | `build_cache` | 7.0.2 → 7.0.2 (typescript) | `exact_hit` | `TRANSITION` | 251.988 | 257.466 | 7 | true | — |
| `BLD-002` | `build_cache` | 7.0.2 → 7.0.2 (typescript) | `incompatible_switch` | `TRANSITION` | 242.911 | 262.377 | 7 | true | build_cache |
| `BLD-003` | `project_server` | cold → 7.0.2 (tsserver) | `process_cold` | `TRANSITION` | 251.308 | 318.906 | 7 | true | — |
| `BLD-004` | `build_cache` | cold → 7.28.4 (babel) | `artifact_cold` | `TRANSITION` | 240.250 | 255.331 | 7 | true | — |
| `BLD-004` | `build_cache` | 7.28.4 → 7.28.4 (babel) | `exact_hit` | `TRANSITION` | 232.898 | 236.787 | 7 | true | — |
| `BLD-004` | `build_cache` | 7.28.4 → 7.28.4 (babel) | `incompatible_switch` | `TRANSITION` | 234.286 | 244.700 | 7 | true | build_cache |
| `BLD-005` | `build_cache` | cold → 1.16.1 (swc) | `artifact_cold` | `TRANSITION` | 116.848 | 122.239 | 7 | true | — |
| `BLD-005` | `build_cache` | 1.16.1 → 1.16.1 (swc) | `exact_hit` | `TRANSITION` | 119.883 | 125.155 | 7 | true | — |
| `BLD-005` | `build_cache` | 1.16.1 → 1.16.1 (swc) | `incompatible_switch` | `TRANSITION` | 116.057 | 124.300 | 7 | true | build_cache |
| `BLD-006` | `build_cache` | cold → 0.28.2 (esbuild) | `artifact_cold` | `TRANSITION` | 119.641 | 126.698 | 7 | true | — |
| `BLD-006` | `build_cache` | 0.28.2 → 0.28.2 (esbuild) | `exact_hit` | `TRANSITION` | 122.653 | 145.895 | 7 | true | — |
| `BLD-006` | `build_cache` | 0.28.2 → 0.28.2 (esbuild) | `incompatible_switch` | `TRANSITION` | 119.829 | 131.687 | 7 | true | build_cache |
| `BLD-007` | `build_cache` | cold → 4.63.1 (rollup) | `artifact_cold` | `TRANSITION` | 119.888 | 127.443 | 7 | true | — |
| `BLD-007` | `build_cache` | 4.63.1 → 4.63.1 (rollup) | `exact_hit` | `TRANSITION` | 115.849 | 130.548 | 7 | true | — |
| `BLD-007` | `build_cache` | 4.63.1 → 4.63.1 (rollup) | `incompatible_switch` | `TRANSITION` | 121.790 | 131.202 | 7 | true | build_cache |
| `BLD-008` | `build_cache` | cold → 5.110.1 (webpack) | `artifact_cold` | `TRANSITION` | 442.626 | 478.148 | 7 | true | — |
| `BLD-008` | `build_cache` | 5.110.1 → 5.110.1 (webpack) | `exact_hit` | `TRANSITION` | 446.923 | 450.342 | 7 | true | — |
| `BLD-008` | `build_cache` | 5.110.1 → 5.110.1 (webpack) | `incompatible_switch` | `TRANSITION` | 467.117 | 506.489 | 7 | true | build_cache |
| `BLD-009` | `build_cache` | cold → 8.2.2 (vite) | `artifact_cold` | `TRANSITION` | 355.514 | 437.308 | 7 | true | — |
| `BLD-009` | `build_cache` | 8.2.2 → 8.2.2 (vite) | `exact_hit` | `TRANSITION` | 351.748 | 373.925 | 7 | true | — |
| `BLD-009` | `build_cache` | 8.2.2 → 8.2.2 (vite) | `incompatible_switch` | `TRANSITION` | 352.373 | 429.868 | 7 | true | build_cache |
| `BLD-016` | `build_cache` | cold → v1 (make/bootstrap/setup \| startup、incremental output、cleanup) | `artifact_cold` | `TRANSITION` | 117.210 | 121.411 | 7 | true | — |
| `BLD-017` | `build_cache` | cold → v1 (generic codegen/generate \| cold、output cache、schema/config invalidation) | `artifact_cold` | `TRANSITION` | 0.168 | 0.184 | 7 | true | — |
| `BLD-020` | `build_cache` | v1 → v1 (TypeScript incremental cache) | `exact_hit` | `TRANSITION` | 233.706 | 252.360 | 7 | true | — |
| `BLD-021` | `build_cache` | v1 → v1 (TypeScript invalidation) | `incompatible_switch` | `TRANSITION` | 231.099 | 240.539 | 7 | true | build_cache |
| `BLD-022` | `project_server` | 8.2.2 → 8.2.2 (Vite watch process) | `dirty_reset` | `TRANSITION` | 31.448 | 31.466 | 7 | true | — |
| `BRW-001` | `browser_binary` | 151.0.7922.77 → 151.0.7922.77 (chromium) | `exact_hit` | `TRANSITION` | 116.437 | 122.561 | 7 | true | — |
| `BRW-002` | `browser_binary` | Mozilla Firefox 153.0.3 → Mozilla Firefox 153.0.3 (firefox) | `exact_hit` | `TRANSITION` | 999.294 | 1082.813 | 7 | true | — |
| `BRW-004` | `browser_binary` | 40.10.2 → 40.10.2 (electron) | `exact_hit` | `TRANSITION` | 115.186 | 123.233 | 7 | true | — |
| `BRW-005` | `browser_binary` | 40.10.2 → 40.10.2 (electron) | `artifact_cold` | `TRANSITION` | 62.368 | 73.016 | 7 | true | — |
| `BRW-006` | `browser_process` | 151.0.7922.77 → 151.0.7922.77 (chromium) | `exact_hit` | `TRANSITION` | 115.306 | 119.536 | 7 | true | — |
| `BRW-007` | `browser_process` | cold → 151.0.7922.77 (chromium) | `process_cold` | `TRANSITION` | 281.798 | 384.480 | 7 | true | — |
| `BRW-008` | `browser_process` | cold → Mozilla Firefox 153.0.3 (firefox) | `process_cold` | `TRANSITION` | 1872.738 | 1901.830 | 7 | true | — |
| `BRW-010` | `browser_process` | 151.0.7922.77 → 151.0.7922.77 (chromium) | `exact_hit` | `TRANSITION` | 0.607 | 1.293 | 7 | true | — |
| `BRW-011` | `browser_context` | 151.0.7922.77 → 151.0.7922.77 (chromium context) | `compatible_reuse` | `TRANSITION` | 54.417 | 70.074 | 7 | true | — |
| `BRW-012` | `browser_context` | 151.0.7922.77 → 151.0.7922.77 (chromium context) | `dirty_reset` | `TRANSITION` | 50.411 | 63.715 | 7 | true | — |
| `BRW-013` | `browser_profile` | cold → 151.0.7922.77 (chromium profile) | `artifact_cold` | `TRANSITION` | 5.102 | 6.821 | 7 | true | — |
| `BRW-014` | `browser_profile` | 151.0.7922.77 → 151.0.7922.77 (chromium profile) | `dirty_reset` | `TRANSITION` | 1.524 | 1.638 | 7 | true | — |
| `BRW-015` | `browser_context` | 151.0.7922.77 → 151.0.7922.77 (chromium context) | `compatible_reuse` | `TRANSITION` | 70.620 | 102.866 | 7 | true | — |
| `BRW-016` | `browser_process` | 151.0.7922.77 → 151.0.7922.77 (chromium) | `incompatible_switch` | `TRANSITION` | 276.215 | 299.530 | 7 | true | browser_context, browser_profile |
| `BRW-017` | `browser_process` | 151.0.7922.77 → 151.0.7922.77 (chromium) | `dirty_reset` | `TRANSITION` | 67.046 | 68.584 | 7 | true | — |
| `BRW-018` | `browser_process` | cold → 40.10.2 (electron) | `process_cold` | `TRANSITION` | 483.931 | 575.370 | 7 | true | — |
| `BRW-019` | `browser_process` | 40.10.2 → 40.10.2 (electron) | `dirty_reset` | `TRANSITION` | 517.751 | 583.314 | 7 | true | — |
| `CAS-001` | `raw_cas` | v1 → v1 (artifact index lookup \| cold/warm、32k artifacts) | `exact_hit` | `PREP` | 0.003 | 0.004 | 7 | true | — |
| `CAS-002` | `raw_cas` | v1 → v1 (blob stat/existence \| metadata warm、concurrent readers) | `exact_hit` | `PREP` | 0.000 | 0.001 | 7 | true | — |
| `CAS-003` | `raw_cas` | v1 → v1 (blob read \| 1KB/100KB/1MB/10MB/100MB) | `exact_hit` | `PREP` | 0.003 | 0.005 | 7 | true | — |
| `CAS-004` | `raw_cas` | v1 → v1 (SHA-256 validation \| size、page-cache cold/warm) | `exact_hit` | `PREP` | 0.001 | 0.002 | 7 | true | — |
| `CAS-005` | `raw_cas` | v1 → v1 (SHA-512/SRI validation \| valid/invalid、size) | `exact_hit` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `CAS-006` | `raw_cas` | v1 → v1 (atomic write/rename/fsync \| local/overlay、disk failure) | `exact_hit` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `CAS-007` | `raw_cas` | v1 → v1 (metadata read/write \| first/reuse、large references) | `exact_hit` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `CAS-008` | `raw_cas` | v1 → v1 (duplicate fetch coalescing \| 2/8/32 callers) | `exact_hit` | `PREP` | 0.002 | 0.002 | 7 | true | — |
| `CAS-009` | `raw_cas` | cold → v1 (corrupt hit detection/repair \| zero/wrong hash/truncated) | `failure_path` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `CAS-010` | `raw_cas` | v1 → v1 (retention/garbage scan \| 32k/100k/1M blobs) | `exact_hit` | `PREP` | 0.002 | 0.002 | 7 | true | — |
| `CON-001` | `contention` | cold → v1 (1/2/4/8 concurrent registry clients) | `contention_path` | `DIAGNOSTIC` | 89.031 | 102.877 | 7 | true | — |
| `CON-002` | `contention` | cold → v1 (same CAS blob concurrent fetch/read) | `contention_path` | `DIAGNOSTIC` | 4.433 | 4.554 | 7 | true | — |
| `CON-003` | `contention` | cold → v1 (multiple PM cache writers) | `contention_path` | `DIAGNOSTIC` | 147.690 | 182.584 | 7 | true | — |
| `CON-004` | `contention` | cold → v1 (multiple dependency views) | `contention_path` | `DIAGNOSTIC` | 11365.093 | 12391.876 | 7 | true | — |
| `CON-005` | `contention` | cold → v1 (concurrent worktrees/checkouts) | `contention_path` | `DIAGNOSTIC` | 2291.425 | 3354.500 | 7 | true | — |
| `CON-006` | `contention` | cold → v1 (concurrent BrowserContexts) | `contention_path` | `DIAGNOSTIC` | 1655.737 | 2045.696 | 7 | true | — |
| `CON-007` | `contention` | cold → v1 (DB connections/private resets) | `contention_path` | `DIAGNOSTIC` | 320.650 | 474.462 | 7 | true | — |
| `CON-008` | `contention` | cold → v1 (CPU/memory/disk saturation) | `contention_path` | `DIAGNOSTIC` | 83.841 | 98.233 | 7 | true | — |
| `CON-009` | `contention` | cold → v1 (port allocator contention) | `contention_path` | `DIAGNOSTIC` | 3.612 | 3.897 | 7 | true | — |
| `CON-010` | `contention` | cold → v1 (scheduler state lock contention) | `contention_path` | `DIAGNOSTIC` | 2.018 | 2.225 | 7 | true | — |
| `CTL-001` | `control_plane` | v1 → v1 (CONTROL \| 加载 resources/requirements/invalidation rules \| 启动成本，不进入 profile edge) | `exact_hit` | `CONTROL` | 0.004 | 0.005 | 7 | true | — |
| `CTL-002` | `control_plane` | v1 → v1 (CONTROL \| 11,105 tasks 聚合为 Environment Groups \| 初始化成本) | `exact_hit` | `CONTROL` | 0.001 | 0.001 | 7 | true | — |
| `CTL-003` | `control_plane` | v1 → v1 (CONTROL \| 单轮 candidate enumeration \| 每轮 overhead) | `exact_hit` | `CONTROL` | 0.001 | 0.001 | 7 | true | — |
| `CTL-004` | `control_plane` | v1 → v1 (CONTROL \| 单 candidate compatibility matching \| planner overhead) | `exact_hit` | `CONTROL` | 0.001 | 0.001 | 7 | true | — |
| `CTL-005` | `control_plane` | v1 → v1 (CONTROL \| 单 candidate transition planning \| planner overhead) | `exact_hit` | `CONTROL` | 0.000 | 0.001 | 7 | true | — |
| `CTL-006` | `control_plane` | v1 → v1 (CONTROL \| invalidation graph 传播 \| 不重复记资源重建时间) | `exact_hit` | `CONTROL` | 0.000 | 0.001 | 7 | true | — |
| `CTL-007` | `control_plane` | v1 → v1 (CONTROL \| greedy selection/tie-break \| 每轮 overhead) | `exact_hit` | `CONTROL` | 0.000 | 0.001 | 7 | true | — |
| `CTL-008` | `control_plane` | v1 → v1 (CONTROL \| NodeState 写盘、恢复、更新 \| action 后实测) | `exact_hit` | `CONTROL` | 0.001 | 0.001 | 7 | true | — |
| `CTL-009` | `control_plane` | v1 → v1 (CONTROL \| action executor dispatch \| 与 action 本身分开) | `exact_hit` | `CONTROL` | 0.002 | 0.002 | 7 | true | — |
| `CTL-010` | `control_plane` | v1 → v1 (CONTROL \| JSONL logging/report aggregation \| 诊断 overhead) | `exact_hit` | `CONTROL` | 0.001 | 0.001 | 7 | true | — |
| `CTL-011` | `control_plane` | v1 → v1 (CONTROL \| state lock/并发等待 \| contention) | `exact_hit` | `CONTROL` | 0.001 | 0.002 | 7 | true | — |
| `CTL-012` | `control_plane` | v1 → v1 (CONTROL \| 多节点 placement scoring \| 未来接口) | `exact_hit` | `CONTROL` | 0.001 | 0.001 | 7 | true | — |
| `DB-004` | `database_binary` | cold → Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=e53ff17674aa6190 (redis) | `process_cold` | `TRANSITION` | 15.822 | 16.997 | 7 | true | — |
| `DB-005` | `database_binary` | python-stdlib → python-stdlib (sqlite) | `exact_hit` | `TRANSITION` | 0.466 | 0.566 | 7 | true | — |
| `DBS-001` | `database_daemon` | cold → Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=e53ff17674aa6190 (redis) | `process_cold` | `TRANSITION` | 14.710 | 18.702 | 7 | true | — |
| `DBS-002` | `database_daemon` | Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=e53ff17674aa6190 → Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=e53ff17674aa6190 (redis) | `exact_hit` | `TRANSITION` | 5.284 | 6.568 | 7 | true | — |
| `DBS-003` | `database_daemon` | Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=e53ff17674aa6190 → Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=e53ff17674aa6190 (redis) | `compatible_reuse` | `TRANSITION` | 0.252 | 0.262 | 7 | true | — |
| `DBS-004` | `database_daemon` | Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=e53ff17674aa6190 → Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=e53ff17674aa6190 (redis) | `dirty_reset` | `TRANSITION` | 0.071 | 0.075 | 7 | true | — |
| `DBS-005` | `database_clean_snapshot` | cold → python-stdlib (sqlite clean snapshot) | `artifact_cold` | `TRANSITION` | 0.443 | 0.600 | 7 | true | — |
| `DBS-006` | `database_clean_snapshot` | python-stdlib → python-stdlib (sqlite clean snapshot) | `compatible_reuse` | `TRANSITION` | 0.434 | 0.442 | 7 | true | — |
| `DBS-007` | `database_private_layer` | cold → python-stdlib (sqlite private layer) | `artifact_cold` | `TRANSITION` | 0.881 | 0.902 | 7 | true | — |
| `DBS-008` | `database_private_layer` | python-stdlib → python-stdlib (sqlite private layer) | `dirty_reset` | `TRANSITION` | 0.023 | 0.023 | 7 | true | — |
| `DBS-009` | `database_private_layer` | cold → python-stdlib (sqlite private layer) | `artifact_cold` | `TRANSITION` | 0.917 | 0.930 | 7 | true | — |
| `DBS-010` | `database_private_layer` | cold → python-stdlib (sqlite private layer) | `artifact_cold` | `TRANSITION` | 1.478 | 1.619 | 7 | true | — |
| `DBS-011` | `database_daemon` | Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=e53ff17674aa6190 → Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=e53ff17674aa6190 (redis) | `compatible_reuse` | `TRANSITION` | 5.191 | 5.791 | 7 | true | — |
| `DBS-013` | `database_daemon` | Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=e53ff17674aa6190 → Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=e53ff17674aa6190 (redis) | `dirty_reset` | `TRANSITION` | 16.377 | 17.146 | 7 | true | — |
| `DEP-001` | `dependency_view` | cold → 10.9.8 (npm minimal dependency view) | `artifact_cold` | `TRANSITION` | 362.659 | 421.814 | 7 | true | — |
| `DEP-002` | `dependency_view` | cold → 10.17.1 (pnpm minimal dependency view) | `artifact_cold` | `TRANSITION` | 450.923 | 500.480 | 7 | true | — |
| `DEP-002` | `dependency_view` | cold → 10.27.0 (pnpm minimal dependency view) | `artifact_cold` | `TRANSITION` | 518.416 | 557.351 | 7 | true | — |
| `DEP-002` | `dependency_view` | cold → 10.28.2 (pnpm minimal dependency view) | `artifact_cold` | `TRANSITION` | 528.475 | 545.079 | 7 | true | — |
| `DEP-002` | `dependency_view` | cold → 10.34.5 (pnpm minimal dependency view) | `artifact_cold` | `TRANSITION` | 498.547 | 565.990 | 7 | true | — |
| `DEP-002` | `dependency_view` | cold → 10.4.0 (pnpm minimal dependency view) | `artifact_cold` | `TRANSITION` | 455.585 | 562.493 | 7 | true | — |
| `DEP-002` | `dependency_view` | cold → 11.24.0 (pnpm minimal dependency view) | `artifact_cold` | `TRANSITION` | 701.851 | 780.749 | 7 | true | — |
| `DEP-002` | `dependency_view` | cold → 9.12.2 (pnpm minimal dependency view) | `artifact_cold` | `TRANSITION` | 544.622 | 565.996 | 7 | true | — |
| `DEP-002` | `dependency_view` | cold → 9.15.0 (pnpm minimal dependency view) | `artifact_cold` | `TRANSITION` | 464.676 | 546.265 | 7 | true | — |
| `DEP-002` | `dependency_view` | cold → 9.15.4 (pnpm minimal dependency view) | `artifact_cold` | `TRANSITION` | 532.539 | 613.663 | 7 | true | — |
| `DEP-002` | `dependency_view` | cold → 9.15.5 (pnpm minimal dependency view) | `artifact_cold` | `TRANSITION` | 484.847 | 621.672 | 7 | true | — |
| `DEP-002` | `dependency_view` | cold → 9.4.0 (pnpm minimal dependency view) | `artifact_cold` | `TRANSITION` | 482.536 | 532.993 | 7 | true | — |
| `DEP-003` | `dependency_view` | cold → 1.22.21 (yarn minimal dependency view) | `artifact_cold` | `TRANSITION` | 354.484 | 395.788 | 7 | true | — |
| `DEP-003` | `dependency_view` | cold → 1.22.22 (yarn minimal dependency view) | `artifact_cold` | `TRANSITION` | 350.586 | 388.924 | 7 | true | — |
| `DEP-004` | `dependency_view` | cold → 3.2.3 (yarn minimal dependency view) | `artifact_cold` | `TRANSITION` | 381.055 | 413.654 | 7 | true | — |
| `DEP-004` | `dependency_view` | cold → 3.8.7 (yarn minimal dependency view) | `artifact_cold` | `TRANSITION` | 374.669 | 395.265 | 7 | true | — |
| `DEP-004` | `dependency_view` | cold → 4.0.2 (yarn minimal dependency view) | `artifact_cold` | `TRANSITION` | 371.879 | 393.268 | 7 | true | — |
| `DEP-004` | `dependency_view` | cold → 4.10.3 (yarn minimal dependency view) | `artifact_cold` | `TRANSITION` | 369.557 | 379.440 | 7 | true | — |
| `DEP-004` | `dependency_view` | cold → 4.12.0 (yarn minimal dependency view) | `artifact_cold` | `TRANSITION` | 377.344 | 407.202 | 7 | true | — |
| `DEP-004` | `dependency_view` | cold → 4.9.1 (yarn minimal dependency view) | `artifact_cold` | `TRANSITION` | 369.143 | 403.730 | 7 | true | — |
| `DEP-005` | `dependency_view` | cold → 3.2.3 (yarn minimal dependency view) | `compatible_reuse` | `TRANSITION` | 379.874 | 482.051 | 7 | true | — |
| `DEP-005` | `dependency_view` | cold → 3.8.7 (yarn minimal dependency view) | `compatible_reuse` | `TRANSITION` | 357.662 | 372.956 | 7 | true | — |
| `DEP-005` | `dependency_view` | cold → 4.0.2 (yarn minimal dependency view) | `compatible_reuse` | `TRANSITION` | 367.836 | 393.672 | 7 | true | — |
| `DEP-005` | `dependency_view` | cold → 4.10.3 (yarn minimal dependency view) | `compatible_reuse` | `TRANSITION` | 382.750 | 404.041 | 7 | true | — |
| `DEP-005` | `dependency_view` | cold → 4.12.0 (yarn minimal dependency view) | `compatible_reuse` | `TRANSITION` | 375.754 | 426.250 | 7 | true | — |
| `DEP-005` | `dependency_view` | cold → 4.9.1 (yarn minimal dependency view) | `compatible_reuse` | `TRANSITION` | 369.601 | 397.236 | 7 | true | — |
| `DEP-006` | `dependency_view` | cold → 1.2.18 (bun minimal dependency view) | `artifact_cold` | `TRANSITION` | 124.284 | 133.886 | 7 | true | — |
| `DEP-006` | `dependency_view` | cold → 1.3.7 (bun minimal dependency view) | `artifact_cold` | `TRANSITION` | 122.797 | 133.912 | 7 | true | — |
| `DEP-007` | `dependency_view` | f4a039d5d472a10b → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `exact_hit` | `TRANSITION` | 127.936 | 158.101 | 7 | true | — |
| `DEP-008` | `dependency_view` | f4a039d5d472a10b → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `compatible_reuse` | `TRANSITION` | 0.787 | 1.015 | 7 | true | — |
| `DEP-009` | `dependency_view` | v1 → v1 (pnpm fixture) | `incompatible_switch` | `TRANSITION` | 469.119 | 482.853 | 7 | true | build_cache, test_transform_cache |
| `DEP-010` | `dependency_view` | f4a039d5d472a10b → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `dirty_reset` | `TRANSITION` | 0.353 | 0.370 | 7 | true | — |
| `DEP-011` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `artifact_cold` | `TRANSITION` | 15.525 | 16.156 | 7 | true | — |
| `DEP-012` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `artifact_cold` | `TRANSITION` | 174.267 | 178.474 | 7 | true | — |
| `DEP-013` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `artifact_cold` | `TRANSITION` | 2.770 | 4.616 | 7 | true | — |
| `DEP-014` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `artifact_cold` | `TRANSITION` | 0.019 | 0.020 | 7 | true | — |
| `DEP-015` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `artifact_cold` | `TRANSITION` | 0.414 | 0.516 | 7 | true | — |
| `DEP-016` | `dependency_view` | f4a039d5d472a10b → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `compatible_reuse` | `TRANSITION` | 2.232 | 2.501 | 7 | true | — |
| `DEP-018` | `dependency_view` | f4a039d5d472a10b → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `exact_hit` | `TRANSITION` | 110.329 | 123.771 | 7 | true | — |
| `DEP-019` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `contention_path` | `TRANSITION` | 2508.758 | 2571.670 | 7 | true | — |
| `DEP-020` | `dependency_view` | f4a039d5d472a10b → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `exact_hit` | `TRANSITION` | 22.467 | 31.073 | 7 | true | — |
| `FAIL-001` | `failure_recovery` | cold → v1 (npm peer conflict \| detect/log/cleanup/fallback) | `failure_path` | `DIAGNOSTIC` | 566.175 | 598.495 | 7 | false | — |
| `FAIL-002` | `failure_recovery` | cold → v1 (invalid/conflicted lock \| parse failure/manual review) | `failure_path` | `DIAGNOSTIC` | 0.028 | 0.030 | 7 | false | — |
| `FAIL-003` | `failure_recovery` | cold → v1 (artifact 404 \| retries/final detect/cleanup) | `failure_path` | `DIAGNOSTIC` | 3.558 | 4.178 | 7 | false | — |
| `FAIL-004` | `failure_recovery` | cold → v1 (CAS integrity mismatch \| detect/quarantine/refetch) | `failure_path` | `DIAGNOSTIC` | 0.001 | 0.001 | 7 | false | — |
| `FAIL-005` | `failure_recovery` | cold → v1 (missing PM/runtime \| lookup/install/unsupported) | `failure_path` | `DIAGNOSTIC` | 0.994 | 1.613 | 7 | false | — |
| `FAIL-006` | `failure_recovery` | cold → v1 (local registry refused \| retry/no-fallback/cleanup) | `failure_path` | `DIAGNOSTIC` | 0.099 | 0.107 | 7 | false | — |
| `FAIL-007` | `failure_recovery` | cold → v1 (platform optional mismatch \| skip/no false failure) | `failure_path` | `DIAGNOSTIC` | 0.001 | 0.001 | 7 | true | — |
| `FAIL-008` | `failure_recovery` | cold → v1 (readiness timeout \| timeout/kill/port cleanup) | `failure_path` | `DIAGNOSTIC` | 101.288 | 101.309 | 7 | false | — |
| `FAIL-009` | `failure_recovery` | cold → v1 (hung install/build/test \| escalation/partial cleanup) | `failure_path` | `DIAGNOSTIC` | 101.323 | 101.353 | 7 | false | — |
| `FAIL-012` | `failure_recovery` | cold → v1 (stale process/port \| detect/cleanup/retry) | `failure_path` | `DIAGNOSTIC` | 0.021 | 0.022 | 7 | true | — |
| `FAIL-013` | `failure_recovery` | cold → v1 (pollution failure \| validate/disable reuse) | `failure_path` | `DIAGNOSTIC` | 0.248 | 0.284 | 7 | false | — |
| `FAIL-014` | `failure_recovery` | cold → v1 (scheduler state corrupt \| recover/rebuild) | `failure_path` | `DIAGNOSTIC` | 0.583 | 0.604 | 7 | true | — |
| `FS-001` | `filesystem_overlay` | cold → ext4 (directory-copy on ext4) | `artifact_cold` | `TRANSITION` | 1.278 | 1.298 | 7 | true | — |
| `FS-002` | `filesystem_overlay` | ext4 → ext4 (directory-copy on ext4) | `compatible_reuse` | `TRANSITION` | 1.001 | 1.041 | 7 | true | — |
| `FS-003` | `filesystem_overlay` | ext4 → ext4 (directory-copy on ext4) | `dirty_reset` | `TRANSITION` | 0.083 | 0.089 | 7 | true | — |
| `FS-004` | `filesystem_overlay` | ext4 → ext4 (directory-copy on ext4) | `exact_hit` | `TRANSITION` | 0.080 | 0.094 | 7 | true | — |
| `FS-005` | `home_tmp_xdg` | cold → v1 (isolated HOME/tmp/XDG) | `artifact_cold` | `TRANSITION` | 14.770 | 15.068 | 7 | true | — |
| `FS-006` | `home_tmp_xdg` | v1 → v1 (isolated HOME/tmp/XDG) | `dirty_reset` | `TRANSITION` | 1.492 | 1.637 | 7 | true | — |
| `FS-007` | `home_tmp_xdg` | v1 → v1 (isolated HOME/tmp/XDG) | `dirty_reset` | `TRANSITION` | 1.431 | 1.459 | 7 | true | — |
| `FS-008` | `home_tmp_xdg` | v1 → v1 (isolated HOME/tmp/XDG) | `dirty_reset` | `TRANSITION` | 1.505 | 1.574 | 7 | true | — |
| `FS-009` | `home_tmp_xdg` | cold → v1 (isolated HOME/tmp/XDG) | `artifact_cold` | `TRANSITION` | 14.637 | 14.836 | 7 | true | — |
| `FS-010` | `filesystem_overlay` | ext4 → ext4 (directory-copy on ext4) | `exact_hit` | `TRANSITION` | 7.016 | 124.324 | 7 | true | — |
| `GUI-001` | `display_service` | cold → host (Xvfb) | `process_cold` | `TRANSITION` | 5.148 | 5.153 | 7 | true | — |
| `GUI-002` | `display_service` | host → host (Xvfb) | `dirty_reset` | `TRANSITION` | 5.163 | 5.181 | 7 | true | — |
| `GUI-003` | `display_service` | cold → host (D-Bus session) | `process_cold` | `TRANSITION` | 119.437 | 130.775 | 7 | true | — |
| `GUI-004` | `display_service` | v1 → v1 (GTK/system GUI library load \| page-cache/rootfs switch) | `exact_hit` | `TRANSITION` | 115.640 | 116.574 | 7 | true | — |
| `GUI-005` | `browser_process` | 151.0.7922.77 → 151.0.7922.77 (chromium) | `compatible_reuse` | `TRANSITION` | 0.562 | 0.586 | 7 | true | — |
| `GUI-006` | `browser_process` | 151.0.7922.77 → 151.0.7922.77 (chromium) | `compatible_reuse` | `TRANSITION` | 0.549 | 0.569 | 7 | true | — |
| `INS-001` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `artifact_cold` | `TRANSITION` | 385.909 | 1102.764 | 7 | true | — |
| `INS-002` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `artifact_cold` | `TRANSITION` | 375.503 | 400.703 | 7 | true | — |
| `INS-003` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `artifact_cold` | `TRANSITION` | 366.875 | 392.318 | 7 | true | — |
| `INS-004` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `artifact_cold` | `TRANSITION` | 242.873 | 268.646 | 7 | true | — |
| `INS-005` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `artifact_cold` | `TRANSITION` | 247.695 | 286.437 | 7 | true | — |
| `INS-006` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `artifact_cold` | `TRANSITION` | 258.263 | 274.628 | 7 | true | — |
| `INS-007` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `artifact_cold` | `TRANSITION` | 260.651 | 266.885 | 7 | true | — |
| `INS-008` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `failure_path` | `TRANSITION` | 624.605 | 662.274 | 7 | false | — |
| `INS-009` | `dependency_view` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `dirty_reset` | `TRANSITION` | 2.118 | 2.876 | 7 | true | — |
| `INS-010` | `dependency_view` | f4a039d5d472a10b → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | `exact_hit` | `TRANSITION` | 370.025 | 399.402 | 7 | true | — |
| `NAT-001` | `native_binary_bundle` | cold → 1.0.0 (node-gyp hello addon) | `artifact_cold` | `TRANSITION` | 785.841 | 815.756 | 7 | true | — |
| `NAT-002` | `native_binary_bundle` | 1.0.0 → 1.0.0 (node-gyp hello addon) | `exact_hit` | `TRANSITION` | 116.259 | 120.155 | 7 | true | — |
| `NAT-004` | `native_binary_bundle` | 1.16.1 → 1.16.1 (@swc/core) | `exact_hit` | `TRANSITION` | 119.866 | 122.890 | 7 | true | — |
| `NAT-005` | `native_binary_bundle` | 0.28.2 → 0.28.2 (esbuild) | `exact_hit` | `TRANSITION` | 121.196 | 200.582 | 7 | true | — |
| `NAT-006` | `native_binary_bundle` | 0.35.4 → 0.35.4 (sharp) | `exact_hit` | `TRANSITION` | 122.819 | 126.921 | 7 | true | — |
| `NAT-007` | `native_binary_bundle` | 6.0.1 → 6.0.1 (sqlite3) | `exact_hit` | `TRANSITION` | 116.503 | 124.435 | 7 | true | — |
| `NAT-010` | `native_binary_bundle` | 1.0.0 → 1.0.0 (node-gyp hello addon) | `incompatible_switch` | `TRANSITION` | 898.706 | 938.262 | 7 | true | native_binary_bundle |
| `NET-003` | `network_ports` | cold → v1 (host loopback ports) | `compatible_reuse` | `TRANSITION` | 0.047 | 0.051 | 7 | true | — |
| `NET-004` | `network_ports` | v1 → v1 (host loopback ports) | `dirty_reset` | `TRANSITION` | 0.018 | 0.019 | 7 | true | — |
| `NET-005` | `network_ports` | v1 → v1 (host loopback ports) | `compatible_reuse` | `TRANSITION` | 0.001 | 0.001 | 7 | true | — |
| `NET-006` | `network_ports` | v1 → v1 (host loopback ports) | `compatible_reuse` | `TRANSITION` | 0.001 | 0.001 | 7 | true | — |
| `NET-007` | `network_ports` | cold → v1 (host loopback ports) | `network_cold` | `TRANSITION` | 185.208 | 192.227 | 7 | true | — |
| `NET-008` | `network_ports` | v1 → v1 (host loopback ports) | `dirty_reset` | `TRANSITION` | 1.152 | 1.228 | 7 | true | — |
| `NET-009` | `network_ports` | v1 → v1 (host loopback ports) | `dirty_reset` | `TRANSITION` | 101.288 | 101.307 | 7 | true | — |
| `NET-010` | `network_ports` | v1 → v1 (host loopback ports) | `exact_hit` | `TRANSITION` | 0.092 | 0.105 | 7 | true | — |
| `NTC-001` | `system_toolchain` | cold → gcc13-python3.12 (Ubuntu build toolchain) | `artifact_cold` | `PREP` | 234.142 | 239.237 | 7 | true | — |
| `NTC-002` | `system_toolchain` | cold → gcc13-python3.12 (Ubuntu build toolchain) | `artifact_cold` | `PREP` | 790.083 | 818.529 | 7 | true | — |
| `NTC-003` | `system_toolchain` | cold → gcc13-python3.12 (Ubuntu build toolchain) | `artifact_cold` | `PREP` | 116.452 | 123.497 | 7 | true | — |
| `NTC-005` | `system_toolchain` | cold → gcc13-python3.12 (Ubuntu build toolchain) | `artifact_cold` | `PREP` | 239.768 | 319.998 | 7 | true | — |
| `NTC-008` | `system_toolchain` | cold → gcc13-python3.12 (Ubuntu build toolchain) | `process_cold` | `PREP` | 120.229 | 122.427 | 7 | true | — |
| `NTC-009` | `system_toolchain` | gcc13-python3.12 → gcc13-python3.12 (Ubuntu build toolchain) | `exact_hit` | `PREP` | 2.924 | 3.325 | 7 | true | — |
| `NTC-010` | `system_toolchain` | gcc13-python3.12 → gcc13-python3.12 (Ubuntu build toolchain) | `exact_hit` | `PREP` | 2.156 | 2.288 | 7 | true | — |
| `NTC-012` | `system_toolchain` | gcc13-python3.12 → gcc13-python3.12 (Ubuntu build toolchain) | `dirty_reset` | `PREP` | 1.415 | 1.717 | 7 | true | — |
| `PM-001` | `package_manager` | 10.9.8 → 10.9.8 (npm) | `exact_hit` | `TRANSITION` | 119.894 | 139.452 | 7 | true | — |
| `PM-002` | `package_manager` | 10.17.1 → 10.17.1 (pnpm) | `exact_hit` | `TRANSITION` | 349.785 | 363.575 | 7 | true | — |
| `PM-002` | `package_manager` | 10.27.0 → 10.27.0 (pnpm) | `exact_hit` | `TRANSITION` | 362.795 | 374.165 | 7 | true | — |
| `PM-002` | `package_manager` | 10.28.2 → 10.28.2 (pnpm) | `exact_hit` | `TRANSITION` | 355.050 | 372.760 | 7 | true | — |
| `PM-002` | `package_manager` | 10.34.5 → 10.34.5 (pnpm) | `exact_hit` | `TRANSITION` | 369.469 | 477.194 | 7 | true | — |
| `PM-002` | `package_manager` | 10.4.0 → 10.4.0 (pnpm) | `exact_hit` | `TRANSITION` | 352.981 | 370.347 | 7 | true | — |
| `PM-002` | `package_manager` | 11.24.0 → 11.24.0 (pnpm) | `exact_hit` | `TRANSITION` | 618.792 | 664.967 | 7 | true | — |
| `PM-002` | `package_manager` | 9.12.2 → 9.12.2 (pnpm) | `exact_hit` | `TRANSITION` | 524.667 | 528.567 | 7 | true | — |
| `PM-002` | `package_manager` | 9.15.0 → 9.15.0 (pnpm) | `exact_hit` | `TRANSITION` | 402.036 | 492.815 | 7 | true | — |
| `PM-002` | `package_manager` | 9.15.4 → 9.15.4 (pnpm) | `exact_hit` | `TRANSITION` | 353.255 | 433.939 | 7 | true | — |
| `PM-002` | `package_manager` | 9.15.5 → 9.15.5 (pnpm) | `exact_hit` | `TRANSITION` | 351.711 | 361.539 | 7 | true | — |
| `PM-002` | `package_manager` | 9.4.0 → 9.4.0 (pnpm) | `exact_hit` | `TRANSITION` | 241.562 | 259.187 | 7 | true | — |
| `PM-003` | `package_manager` | 1.22.21 → 1.22.21 (yarn) | `exact_hit` | `TRANSITION` | 234.745 | 243.246 | 7 | true | — |
| `PM-003` | `package_manager` | 1.22.22 → 1.22.22 (yarn) | `exact_hit` | `TRANSITION` | 233.559 | 250.895 | 7 | true | — |
| `PM-004` | `package_manager` | 3.2.3 → 3.2.3 (yarn) | `exact_hit` | `TRANSITION` | 241.232 | 251.888 | 7 | true | — |
| `PM-004` | `package_manager` | 3.8.7 → 3.8.7 (yarn) | `exact_hit` | `TRANSITION` | 230.531 | 251.083 | 7 | true | — |
| `PM-004` | `package_manager` | 4.0.2 → 4.0.2 (yarn) | `exact_hit` | `TRANSITION` | 245.482 | 330.570 | 7 | true | — |
| `PM-004` | `package_manager` | 4.10.3 → 4.10.3 (yarn) | `exact_hit` | `TRANSITION` | 230.195 | 242.821 | 7 | true | — |
| `PM-004` | `package_manager` | 4.12.0 → 4.12.0 (yarn) | `exact_hit` | `TRANSITION` | 245.268 | 251.741 | 7 | true | — |
| `PM-004` | `package_manager` | 4.9.1 → 4.9.1 (yarn) | `exact_hit` | `TRANSITION` | 230.326 | 243.874 | 7 | true | — |
| `PM-005` | `package_manager` | 1.2.18 → 1.2.18 (bun) | `exact_hit` | `TRANSITION` | 3.225 | 3.374 | 7 | true | — |
| `PM-005` | `package_manager` | 1.3.7 → 1.3.7 (bun) | `exact_hit` | `TRANSITION` | 3.448 | 3.621 | 7 | true | — |
| `PM-007` | `package_manager` | cold → 10.17.1 (pnpm) | `artifact_cold` | `TRANSITION` | 755.363 | 814.342 | 7 | true | — |
| `PM-008` | `package_manager` | 1.2.18 → 1.2.18 (bun) | `exact_hit` | `TRANSITION` | 3.881 | 5.216 | 7 | true | — |
| `PM-008` | `package_manager` | 1.2.18 → 1.3.7 (bun) | `incompatible_switch` | `TRANSITION` | 3.663 | 4.478 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.3.7 → 1.2.18 (bun) | `incompatible_switch` | `TRANSITION` | 3.688 | 5.699 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.3.7 → 1.3.7 (bun) | `exact_hit` | `TRANSITION` | 4.062 | 6.255 | 7 | true | — |
| `PM-008` | `package_manager` | 10.9.8 → 10.9.8 (npm) | `exact_hit` | `TRANSITION` | 134.138 | 135.493 | 7 | true | — |
| `PM-008` | `package_manager` | 10.17.1 → 10.17.1 (pnpm) | `exact_hit` | `TRANSITION` | 400.037 | 425.413 | 7 | true | — |
| `PM-008` | `package_manager` | 10.17.1 → 10.27.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 360.156 | 368.208 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.17.1 → 10.28.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 375.131 | 403.374 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.17.1 → 10.34.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 452.925 | 461.739 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.17.1 → 10.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 351.560 | 359.157 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.17.1 → 11.24.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 590.378 | 623.136 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.17.1 → 9.12.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 377.538 | 412.729 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.17.1 → 9.15.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 348.813 | 449.046 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.17.1 → 9.15.4 (pnpm) | `incompatible_switch` | `TRANSITION` | 348.472 | 350.326 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.17.1 → 9.15.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 359.876 | 372.198 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.17.1 → 9.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 265.566 | 288.009 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.27.0 → 10.17.1 (pnpm) | `incompatible_switch` | `TRANSITION` | 396.403 | 413.492 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.27.0 → 10.27.0 (pnpm) | `exact_hit` | `TRANSITION` | 346.702 | 372.460 | 7 | true | — |
| `PM-008` | `package_manager` | 10.27.0 → 10.28.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 354.577 | 382.645 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.27.0 → 10.34.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 460.213 | 464.830 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.27.0 → 10.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 348.332 | 370.565 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.27.0 → 11.24.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 572.829 | 590.483 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.27.0 → 9.12.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 352.081 | 428.184 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.27.0 → 9.15.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 348.492 | 424.467 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.27.0 → 9.15.4 (pnpm) | `incompatible_switch` | `TRANSITION` | 358.177 | 385.729 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.27.0 → 9.15.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 352.750 | 400.263 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.27.0 → 9.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 249.175 | 252.663 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.28.2 → 10.17.1 (pnpm) | `incompatible_switch` | `TRANSITION` | 362.723 | 374.425 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.28.2 → 10.27.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 349.704 | 356.487 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.28.2 → 10.28.2 (pnpm) | `exact_hit` | `TRANSITION` | 339.240 | 352.478 | 7 | true | — |
| `PM-008` | `package_manager` | 10.28.2 → 10.34.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 447.889 | 467.204 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.28.2 → 10.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 363.275 | 373.178 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.28.2 → 11.24.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 587.885 | 616.093 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.28.2 → 9.12.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 367.311 | 447.887 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.28.2 → 9.15.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 349.255 | 434.427 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.28.2 → 9.15.4 (pnpm) | `incompatible_switch` | `TRANSITION` | 388.077 | 488.080 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.28.2 → 9.15.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 407.080 | 431.559 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.28.2 → 9.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 247.709 | 262.030 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.34.5 → 10.17.1 (pnpm) | `incompatible_switch` | `TRANSITION` | 368.466 | 439.951 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.34.5 → 10.27.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 364.463 | 400.227 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.34.5 → 10.28.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 370.588 | 397.851 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.34.5 → 10.34.5 (pnpm) | `exact_hit` | `TRANSITION` | 498.545 | 535.154 | 7 | true | — |
| `PM-008` | `package_manager` | 10.34.5 → 10.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 352.925 | 435.182 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.34.5 → 11.24.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 600.308 | 630.547 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.34.5 → 9.12.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 383.608 | 453.702 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.34.5 → 9.15.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 346.507 | 417.177 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.34.5 → 9.15.4 (pnpm) | `incompatible_switch` | `TRANSITION` | 364.076 | 394.129 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.34.5 → 9.15.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 348.101 | 438.731 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.34.5 → 9.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 225.045 | 235.469 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.4.0 → 10.17.1 (pnpm) | `incompatible_switch` | `TRANSITION` | 342.318 | 397.951 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.4.0 → 10.27.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 347.605 | 350.726 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.4.0 → 10.28.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 345.704 | 350.990 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.4.0 → 10.34.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 518.350 | 527.691 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.4.0 → 10.4.0 (pnpm) | `exact_hit` | `TRANSITION` | 422.692 | 597.367 | 7 | true | — |
| `PM-008` | `package_manager` | 10.4.0 → 11.24.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 656.412 | 692.640 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.4.0 → 9.12.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 378.526 | 462.056 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.4.0 → 9.15.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 343.526 | 494.020 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.4.0 → 9.15.4 (pnpm) | `incompatible_switch` | `TRANSITION` | 424.787 | 434.312 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.4.0 → 9.15.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 388.728 | 439.789 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 10.4.0 → 9.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 262.892 | 271.942 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 11.24.0 → 10.17.1 (pnpm) | `incompatible_switch` | `TRANSITION` | 367.574 | 396.585 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 11.24.0 → 10.27.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 374.818 | 413.244 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 11.24.0 → 10.28.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 380.473 | 398.739 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 11.24.0 → 10.34.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 379.635 | 403.614 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 11.24.0 → 10.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 373.120 | 436.243 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 11.24.0 → 11.24.0 (pnpm) | `exact_hit` | `TRANSITION` | 612.664 | 640.655 | 7 | true | — |
| `PM-008` | `package_manager` | 11.24.0 → 9.12.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 427.108 | 485.753 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 11.24.0 → 9.15.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 396.316 | 409.816 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 11.24.0 → 9.15.4 (pnpm) | `incompatible_switch` | `TRANSITION` | 384.425 | 451.704 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 11.24.0 → 9.15.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 379.985 | 399.682 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 11.24.0 → 9.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 260.605 | 279.087 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.12.2 → 10.17.1 (pnpm) | `incompatible_switch` | `TRANSITION` | 370.139 | 397.420 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.12.2 → 10.27.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 374.221 | 389.009 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.12.2 → 10.28.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 384.327 | 401.685 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.12.2 → 10.34.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 388.744 | 499.649 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.12.2 → 10.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 360.820 | 371.788 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.12.2 → 11.24.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 565.319 | 619.453 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.12.2 → 9.12.2 (pnpm) | `exact_hit` | `TRANSITION` | 489.192 | 524.416 | 7 | true | — |
| `PM-008` | `package_manager` | 9.12.2 → 9.15.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 405.066 | 507.719 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.12.2 → 9.15.4 (pnpm) | `incompatible_switch` | `TRANSITION` | 352.964 | 380.751 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.12.2 → 9.15.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 414.090 | 477.919 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.12.2 → 9.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 237.968 | 254.364 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.0 → 10.17.1 (pnpm) | `incompatible_switch` | `TRANSITION` | 369.509 | 377.930 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.0 → 10.27.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 359.148 | 395.531 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.0 → 10.28.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 365.063 | 395.944 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.0 → 10.34.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 441.491 | 471.077 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.0 → 10.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 368.004 | 381.069 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.0 → 11.24.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 601.350 | 635.758 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.0 → 9.12.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 372.821 | 453.409 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.0 → 9.15.0 (pnpm) | `exact_hit` | `TRANSITION` | 374.148 | 447.394 | 7 | true | — |
| `PM-008` | `package_manager` | 9.15.0 → 9.15.4 (pnpm) | `incompatible_switch` | `TRANSITION` | 393.639 | 411.095 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.0 → 9.15.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 372.686 | 494.893 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.0 → 9.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 245.957 | 269.339 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.4 → 10.17.1 (pnpm) | `incompatible_switch` | `TRANSITION` | 384.088 | 407.620 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.4 → 10.27.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 367.410 | 388.262 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.4 → 10.28.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 363.026 | 376.884 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.4 → 10.34.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 377.602 | 504.846 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.4 → 10.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 367.440 | 387.698 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.4 → 11.24.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 604.455 | 633.989 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.4 → 9.12.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 480.601 | 525.102 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.4 → 9.15.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 343.355 | 381.970 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.4 → 9.15.4 (pnpm) | `exact_hit` | `TRANSITION` | 372.182 | 451.221 | 7 | true | — |
| `PM-008` | `package_manager` | 9.15.4 → 9.15.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 381.228 | 436.316 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.4 → 9.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 238.163 | 247.976 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.5 → 10.17.1 (pnpm) | `incompatible_switch` | `TRANSITION` | 346.636 | 361.618 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.5 → 10.27.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 351.485 | 364.644 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.5 → 10.28.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 344.103 | 373.759 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.5 → 10.34.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 448.847 | 464.221 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.5 → 10.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 348.851 | 519.319 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.5 → 11.24.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 582.727 | 621.416 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.5 → 9.12.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 372.184 | 485.341 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.5 → 9.15.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 359.643 | 421.910 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.5 → 9.15.4 (pnpm) | `incompatible_switch` | `TRANSITION` | 385.441 | 446.370 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.15.5 → 9.15.5 (pnpm) | `exact_hit` | `TRANSITION` | 349.878 | 422.338 | 7 | true | — |
| `PM-008` | `package_manager` | 9.15.5 → 9.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 234.033 | 245.877 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.4.0 → 10.17.1 (pnpm) | `incompatible_switch` | `TRANSITION` | 342.336 | 350.099 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.4.0 → 10.27.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 347.542 | 361.452 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.4.0 → 10.28.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 345.911 | 351.151 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.4.0 → 10.34.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 448.743 | 467.896 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.4.0 → 10.4.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 410.154 | 506.309 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.4.0 → 11.24.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 633.452 | 676.846 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.4.0 → 9.12.2 (pnpm) | `incompatible_switch` | `TRANSITION` | 355.215 | 448.431 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.4.0 → 9.15.0 (pnpm) | `incompatible_switch` | `TRANSITION` | 356.029 | 424.297 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.4.0 → 9.15.4 (pnpm) | `incompatible_switch` | `TRANSITION` | 339.247 | 372.259 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.4.0 → 9.15.5 (pnpm) | `incompatible_switch` | `TRANSITION` | 341.090 | 374.687 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 9.4.0 → 9.4.0 (pnpm) | `exact_hit` | `TRANSITION` | 232.227 | 244.508 | 7 | true | — |
| `PM-008` | `package_manager` | 3.2.3 → 3.2.3 (yarn) | `exact_hit` | `TRANSITION` | 242.065 | 263.699 | 7 | true | — |
| `PM-008` | `package_manager` | 3.2.3 → 3.8.7 (yarn) | `incompatible_switch` | `TRANSITION` | 230.794 | 334.071 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 3.2.3 → 4.0.2 (yarn) | `incompatible_switch` | `TRANSITION` | 228.088 | 301.234 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 3.2.3 → 4.10.3 (yarn) | `incompatible_switch` | `TRANSITION` | 232.542 | 305.459 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 3.2.3 → 4.12.0 (yarn) | `incompatible_switch` | `TRANSITION` | 227.093 | 248.342 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 3.2.3 → 4.9.1 (yarn) | `incompatible_switch` | `TRANSITION` | 238.237 | 250.606 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 3.2.3 → 1.22.21 (yarn) | `incompatible_switch` | `TRANSITION` | 225.987 | 238.993 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 3.2.3 → 1.22.22 (yarn) | `incompatible_switch` | `TRANSITION` | 254.559 | 273.540 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 3.8.7 → 3.2.3 (yarn) | `incompatible_switch` | `TRANSITION` | 376.899 | 391.866 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 3.8.7 → 3.8.7 (yarn) | `exact_hit` | `TRANSITION` | 274.413 | 376.042 | 7 | true | — |
| `PM-008` | `package_manager` | 3.8.7 → 4.0.2 (yarn) | `incompatible_switch` | `TRANSITION` | 266.267 | 350.149 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 3.8.7 → 4.10.3 (yarn) | `incompatible_switch` | `TRANSITION` | 265.714 | 349.237 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 3.8.7 → 4.12.0 (yarn) | `incompatible_switch` | `TRANSITION` | 269.445 | 360.875 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 3.8.7 → 4.9.1 (yarn) | `incompatible_switch` | `TRANSITION` | 335.660 | 384.919 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 3.8.7 → 1.22.21 (yarn) | `incompatible_switch` | `TRANSITION` | 237.899 | 250.690 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 3.8.7 → 1.22.22 (yarn) | `incompatible_switch` | `TRANSITION` | 234.359 | 248.751 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.0.2 → 3.2.3 (yarn) | `incompatible_switch` | `TRANSITION` | 246.287 | 331.370 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.0.2 → 3.8.7 (yarn) | `incompatible_switch` | `TRANSITION` | 245.974 | 335.132 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.0.2 → 4.0.2 (yarn) | `exact_hit` | `TRANSITION` | 227.537 | 253.963 | 7 | true | — |
| `PM-008` | `package_manager` | 4.0.2 → 4.10.3 (yarn) | `incompatible_switch` | `TRANSITION` | 242.286 | 335.389 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.0.2 → 4.12.0 (yarn) | `incompatible_switch` | `TRANSITION` | 234.142 | 308.256 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.0.2 → 4.9.1 (yarn) | `incompatible_switch` | `TRANSITION` | 240.678 | 246.046 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.0.2 → 1.22.21 (yarn) | `incompatible_switch` | `TRANSITION` | 234.278 | 246.259 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.0.2 → 1.22.22 (yarn) | `incompatible_switch` | `TRANSITION` | 229.311 | 253.918 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.10.3 → 3.2.3 (yarn) | `incompatible_switch` | `TRANSITION` | 232.524 | 242.506 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.10.3 → 3.8.7 (yarn) | `incompatible_switch` | `TRANSITION` | 236.111 | 305.911 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.10.3 → 4.0.2 (yarn) | `incompatible_switch` | `TRANSITION` | 236.997 | 242.153 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.10.3 → 4.10.3 (yarn) | `exact_hit` | `TRANSITION` | 237.683 | 340.352 | 7 | true | — |
| `PM-008` | `package_manager` | 4.10.3 → 4.12.0 (yarn) | `incompatible_switch` | `TRANSITION` | 265.008 | 348.169 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.10.3 → 4.9.1 (yarn) | `incompatible_switch` | `TRANSITION` | 366.606 | 392.143 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.10.3 → 1.22.21 (yarn) | `incompatible_switch` | `TRANSITION` | 256.859 | 259.064 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.10.3 → 1.22.22 (yarn) | `incompatible_switch` | `TRANSITION` | 230.700 | 238.906 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.12.0 → 3.2.3 (yarn) | `incompatible_switch` | `TRANSITION` | 237.296 | 340.569 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.12.0 → 3.8.7 (yarn) | `incompatible_switch` | `TRANSITION` | 227.060 | 240.118 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.12.0 → 4.0.2 (yarn) | `incompatible_switch` | `TRANSITION` | 232.355 | 239.382 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.12.0 → 4.10.3 (yarn) | `incompatible_switch` | `TRANSITION` | 237.125 | 321.425 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.12.0 → 4.12.0 (yarn) | `exact_hit` | `TRANSITION` | 232.727 | 261.156 | 7 | true | — |
| `PM-008` | `package_manager` | 4.12.0 → 4.9.1 (yarn) | `incompatible_switch` | `TRANSITION` | 233.398 | 304.265 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.12.0 → 1.22.21 (yarn) | `incompatible_switch` | `TRANSITION` | 232.254 | 237.452 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.12.0 → 1.22.22 (yarn) | `incompatible_switch` | `TRANSITION` | 233.266 | 251.961 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.9.1 → 3.2.3 (yarn) | `incompatible_switch` | `TRANSITION` | 242.127 | 323.262 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.9.1 → 3.8.7 (yarn) | `incompatible_switch` | `TRANSITION` | 239.047 | 320.887 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.9.1 → 4.0.2 (yarn) | `incompatible_switch` | `TRANSITION` | 262.754 | 279.314 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.9.1 → 4.10.3 (yarn) | `incompatible_switch` | `TRANSITION` | 241.902 | 311.529 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.9.1 → 4.12.0 (yarn) | `incompatible_switch` | `TRANSITION` | 236.958 | 306.098 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.9.1 → 4.9.1 (yarn) | `exact_hit` | `TRANSITION` | 264.195 | 269.787 | 7 | true | — |
| `PM-008` | `package_manager` | 4.9.1 → 1.22.21 (yarn) | `incompatible_switch` | `TRANSITION` | 236.358 | 239.979 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 4.9.1 → 1.22.22 (yarn) | `incompatible_switch` | `TRANSITION` | 227.462 | 242.547 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.21 → 3.2.3 (yarn) | `incompatible_switch` | `TRANSITION` | 243.008 | 313.321 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.21 → 3.8.7 (yarn) | `incompatible_switch` | `TRANSITION` | 241.227 | 346.865 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.21 → 4.0.2 (yarn) | `incompatible_switch` | `TRANSITION` | 233.591 | 339.704 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.21 → 4.10.3 (yarn) | `incompatible_switch` | `TRANSITION` | 248.550 | 336.645 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.21 → 4.12.0 (yarn) | `incompatible_switch` | `TRANSITION` | 234.029 | 339.697 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.21 → 4.9.1 (yarn) | `incompatible_switch` | `TRANSITION` | 244.966 | 335.670 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.21 → 1.22.21 (yarn) | `exact_hit` | `TRANSITION` | 231.064 | 249.300 | 7 | true | — |
| `PM-008` | `package_manager` | 1.22.21 → 1.22.22 (yarn) | `incompatible_switch` | `TRANSITION` | 223.672 | 229.807 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.22 → 3.2.3 (yarn) | `incompatible_switch` | `TRANSITION` | 234.906 | 347.500 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.22 → 3.8.7 (yarn) | `incompatible_switch` | `TRANSITION` | 263.735 | 323.917 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.22 → 4.0.2 (yarn) | `incompatible_switch` | `TRANSITION` | 236.905 | 263.495 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.22 → 4.10.3 (yarn) | `incompatible_switch` | `TRANSITION` | 232.226 | 328.684 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.22 → 4.12.0 (yarn) | `incompatible_switch` | `TRANSITION` | 239.606 | 324.654 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.22 → 4.9.1 (yarn) | `incompatible_switch` | `TRANSITION` | 230.102 | 326.775 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.22 → 1.22.21 (yarn) | `incompatible_switch` | `TRANSITION` | 239.557 | 244.962 | 7 | true | dependency_view, pm_native_cache |
| `PM-008` | `package_manager` | 1.22.22 → 1.22.22 (yarn) | `exact_hit` | `TRANSITION` | 240.115 | 249.655 | 7 | true | — |
| `PMC-001` | `pm_native_cache` | 10.9.8 → 10.9.8 (npm native cache) | `exact_hit` | `TRANSITION` | 0.102 | 0.109 | 7 | true | — |
| `PMC-001` | `pm_native_cache` | unknown → unknown (npm native cache) | `exact_hit` | `TRANSITION` | 0.040 | 0.042 | 7 | true | — |
| `PMC-002` | `pm_native_cache` | 10.17.1 → 10.17.1 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.041 | 0.044 | 7 | true | — |
| `PMC-002` | `pm_native_cache` | 10.27.0 → 10.27.0 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.041 | 0.048 | 7 | true | — |
| `PMC-002` | `pm_native_cache` | 10.28.2 → 10.28.2 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.040 | 0.042 | 7 | true | — |
| `PMC-002` | `pm_native_cache` | 10.34.5 → 10.34.5 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.039 | 0.041 | 7 | true | — |
| `PMC-002` | `pm_native_cache` | 10.4.0 → 10.4.0 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.042 | 0.043 | 7 | true | — |
| `PMC-002` | `pm_native_cache` | 11.24.0 → 11.24.0 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.039 | 0.043 | 7 | true | — |
| `PMC-002` | `pm_native_cache` | 9.12.2 → 9.12.2 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.040 | 0.042 | 7 | true | — |
| `PMC-002` | `pm_native_cache` | 9.15.0 → 9.15.0 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.042 | 0.046 | 7 | true | — |
| `PMC-002` | `pm_native_cache` | 9.15.4 → 9.15.4 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.040 | 0.041 | 7 | true | — |
| `PMC-002` | `pm_native_cache` | 9.15.5 → 9.15.5 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.039 | 0.042 | 7 | true | — |
| `PMC-002` | `pm_native_cache` | 9.4.0 → 9.4.0 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.042 | 0.045 | 7 | true | — |
| `PMC-003` | `pm_native_cache` | 1.22.21 → 1.22.21 (yarn native cache) | `exact_hit` | `TRANSITION` | 0.045 | 0.081 | 7 | true | — |
| `PMC-003` | `pm_native_cache` | 1.22.22 → 1.22.22 (yarn native cache) | `exact_hit` | `TRANSITION` | 0.039 | 0.042 | 7 | true | — |
| `PMC-004` | `pm_native_cache` | 3.2.3 → 3.2.3 (yarn native cache) | `exact_hit` | `TRANSITION` | 11.267 | 11.798 | 7 | true | — |
| `PMC-004` | `pm_native_cache` | 3.8.7 → 3.8.7 (yarn native cache) | `exact_hit` | `TRANSITION` | 4.657 | 4.689 | 7 | true | — |
| `PMC-004` | `pm_native_cache` | 4.0.2 → 4.0.2 (yarn native cache) | `exact_hit` | `TRANSITION` | 9.682 | 9.821 | 7 | true | — |
| `PMC-004` | `pm_native_cache` | 4.10.3 → 4.10.3 (yarn native cache) | `exact_hit` | `TRANSITION` | 5.964 | 6.028 | 7 | true | — |
| `PMC-004` | `pm_native_cache` | 4.12.0 → 4.12.0 (yarn native cache) | `exact_hit` | `TRANSITION` | 11.353 | 11.464 | 7 | true | — |
| `PMC-004` | `pm_native_cache` | 4.9.1 → 4.9.1 (yarn native cache) | `exact_hit` | `TRANSITION` | 8.424 | 80.518 | 7 | true | — |
| `PMC-005` | `pm_native_cache` | 1.2.18 → 1.2.18 (bun native cache) | `exact_hit` | `TRANSITION` | 7.537 | 7.713 | 7 | true | — |
| `PMC-005` | `pm_native_cache` | 1.3.7 → 1.3.7 (bun native cache) | `exact_hit` | `TRANSITION` | 15.615 | 87.921 | 7 | true | — |
| `PMC-006` | `pm_native_cache` | 1.2.18 → 1.2.18 (bun native cache) | `exact_hit` | `TRANSITION` | 3.631 | 3.658 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 1.2.18 → 1.2.18 (bun native cache) | `exact_hit` | `TRANSITION` | 3.675 | 3.738 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 1.2.18 → 1.3.7 (bun native cache) | `incompatible_switch` | `TRANSITION` | 10.227 | 10.277 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.3.7 → 1.2.18 (bun native cache) | `incompatible_switch` | `TRANSITION` | 3.649 | 3.664 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.3.7 → 1.3.7 (bun native cache) | `exact_hit` | `TRANSITION` | 10.247 | 10.371 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 10.9.8 → 10.9.8 (npm native cache) | `exact_hit` | `TRANSITION` | 0.029 | 0.087 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 10.9.8 → unknown (npm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | unknown → 10.9.8 (npm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | unknown → unknown (npm native cache) | `exact_hit` | `TRANSITION` | 0.026 | 0.030 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 10.17.1 → 10.17.1 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.027 | 0.029 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 10.17.1 → 10.27.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.034 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.17.1 → 10.28.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.17.1 → 10.34.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.033 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.17.1 → 10.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.035 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.17.1 → 11.24.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.17.1 → 9.12.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.032 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.17.1 → 9.15.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.033 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.17.1 → 9.15.4 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.17.1 → 9.15.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.17.1 → 9.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.028 | 0.035 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.27.0 → 10.17.1 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.27.0 → 10.27.0 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.027 | 0.030 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 10.27.0 → 10.28.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.032 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.27.0 → 10.34.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.27.0 → 10.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.029 | 0.080 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.27.0 → 11.24.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.029 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.27.0 → 9.12.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.27.0 → 9.15.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.27.0 → 9.15.4 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.029 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.27.0 → 9.15.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.27.0 → 9.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.025 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.28.2 → 10.17.1 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.025 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.28.2 → 10.27.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.025 | 0.034 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.28.2 → 10.28.2 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.026 | 0.028 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 10.28.2 → 10.34.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.033 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.28.2 → 10.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.28.2 → 11.24.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.025 | 0.027 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.28.2 → 9.12.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.025 | 0.027 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.28.2 → 9.15.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.025 | 0.084 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.28.2 → 9.15.4 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.025 | 0.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.28.2 → 9.15.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.024 | 0.027 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.28.2 → 9.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.032 | 0.068 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.34.5 → 10.17.1 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.34.5 → 10.27.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.34.5 → 10.28.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.34.5 → 10.34.5 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.027 | 0.031 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 10.34.5 → 10.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.032 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.34.5 → 11.24.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.34.5 → 9.12.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.028 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.34.5 → 9.15.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.34.5 → 9.15.4 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.028 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.34.5 → 9.15.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.34.5 → 9.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.4.0 → 10.17.1 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.4.0 → 10.27.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.028 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.4.0 → 10.28.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.4.0 → 10.34.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.4.0 → 10.4.0 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.027 | 0.029 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 10.4.0 → 11.24.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.4.0 → 9.12.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.4.0 → 9.15.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.034 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.4.0 → 9.15.4 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.4.0 → 9.15.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 10.4.0 → 9.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 11.24.0 → 10.17.1 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.028 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 11.24.0 → 10.27.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 11.24.0 → 10.28.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 11.24.0 → 10.34.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 11.24.0 → 10.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 11.24.0 → 11.24.0 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.026 | 0.032 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 11.24.0 → 9.12.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 11.24.0 → 9.15.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 11.24.0 → 9.15.4 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 11.24.0 → 9.15.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.028 | 0.034 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 11.24.0 → 9.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.12.2 → 10.17.1 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.12.2 → 10.27.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.12.2 → 10.28.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.12.2 → 10.34.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.12.2 → 10.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.12.2 → 11.24.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.12.2 → 9.12.2 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.026 | 0.029 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 9.12.2 → 9.15.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.12.2 → 9.15.4 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.12.2 → 9.15.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.080 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.12.2 → 9.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.0 → 10.17.1 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.0 → 10.27.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.0 → 10.28.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.0 → 10.34.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.0 → 10.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.038 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.0 → 11.24.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.035 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.0 → 9.12.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.0 → 9.15.0 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.028 | 0.034 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 9.15.0 → 9.15.4 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.0 → 9.15.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.0 → 9.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.4 → 10.17.1 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.4 → 10.27.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.4 → 10.28.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.4 → 10.34.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.4 → 10.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.4 → 11.24.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.4 → 9.12.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.4 → 9.15.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.4 → 9.15.4 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.026 | 0.029 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 9.15.4 → 9.15.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.4 → 9.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.5 → 10.17.1 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.036 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.5 → 10.27.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.028 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.5 → 10.28.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.095 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.5 → 10.34.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.028 | 0.032 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.5 → 10.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.5 → 11.24.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.5 → 9.12.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.5 → 9.15.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.5 → 9.15.4 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.15.5 → 9.15.5 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.026 | 0.030 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 9.15.5 → 9.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.4.0 → 10.17.1 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.038 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.4.0 → 10.27.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.033 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.4.0 → 10.28.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.4.0 → 10.34.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.4.0 → 10.4.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.028 | 0.085 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.4.0 → 11.24.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.028 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.4.0 → 9.12.2 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.4.0 → 9.15.0 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.028 | 0.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.4.0 → 9.15.4 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.4.0 → 9.15.5 (pnpm native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 9.4.0 → 9.4.0 (pnpm native cache) | `exact_hit` | `TRANSITION` | 0.027 | 0.029 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 3.2.3 → 3.2.3 (yarn native cache) | `exact_hit` | `TRANSITION` | 4.945 | 4.993 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 3.2.3 → 3.8.7 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.035 | 1.040 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 3.2.3 → 4.0.2 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 3.603 | 3.853 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 3.2.3 → 4.10.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.324 | 1.341 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 3.2.3 → 4.12.0 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 4.855 | 5.049 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 3.2.3 → 4.9.1 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 2.421 | 2.466 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 3.2.3 → 1.22.21 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.210 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 3.2.3 → 1.22.22 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 3.8.7 → 3.2.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 4.932 | 5.479 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 3.8.7 → 3.8.7 (yarn native cache) | `exact_hit` | `TRANSITION` | 1.044 | 1.046 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 3.8.7 → 4.0.2 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 3.605 | 3.954 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 3.8.7 → 4.10.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.323 | 1.334 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 3.8.7 → 4.12.0 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 4.848 | 4.906 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 3.8.7 → 4.9.1 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 2.393 | 2.426 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 3.8.7 → 1.22.21 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.025 | 0.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 3.8.7 → 1.22.22 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.025 | 0.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.0.2 → 3.2.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 4.999 | 5.028 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.0.2 → 3.8.7 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.042 | 1.068 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.0.2 → 4.0.2 (yarn native cache) | `exact_hit` | `TRANSITION` | 3.571 | 3.649 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 4.0.2 → 4.10.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.326 | 1.417 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.0.2 → 4.12.0 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 4.845 | 4.870 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.0.2 → 4.9.1 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 2.401 | 2.409 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.0.2 → 1.22.21 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.037 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.0.2 → 1.22.22 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.10.3 → 3.2.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 4.945 | 4.987 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.10.3 → 3.8.7 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.036 | 1.047 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.10.3 → 4.0.2 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 3.586 | 3.635 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.10.3 → 4.10.3 (yarn native cache) | `exact_hit` | `TRANSITION` | 1.309 | 1.333 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 4.10.3 → 4.12.0 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 4.819 | 4.855 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.10.3 → 4.9.1 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 2.430 | 2.494 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.10.3 → 1.22.21 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.10.3 → 1.22.22 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.026 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.12.0 → 3.2.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 5.036 | 5.126 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.12.0 → 3.8.7 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.049 | 1.071 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.12.0 → 4.0.2 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 3.586 | 3.680 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.12.0 → 4.10.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.327 | 1.339 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.12.0 → 4.12.0 (yarn native cache) | `exact_hit` | `TRANSITION` | 4.797 | 4.842 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 4.12.0 → 4.9.1 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 2.404 | 2.414 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.12.0 → 1.22.21 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.028 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.12.0 → 1.22.22 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.025 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.9.1 → 3.2.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 4.951 | 4.993 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.9.1 → 3.8.7 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.036 | 1.063 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.9.1 → 4.0.2 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 3.570 | 3.623 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.9.1 → 4.10.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.334 | 1.345 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.9.1 → 4.12.0 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 4.817 | 4.847 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.9.1 → 4.9.1 (yarn native cache) | `exact_hit` | `TRANSITION` | 2.414 | 2.620 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 4.9.1 → 1.22.21 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.030 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 4.9.1 → 1.22.22 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.21 → 3.2.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 5.013 | 5.031 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.21 → 3.8.7 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.047 | 1.127 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.21 → 4.0.2 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 3.564 | 3.859 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.21 → 4.10.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.326 | 1.331 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.21 → 4.12.0 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 4.865 | 4.885 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.21 → 4.9.1 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 2.414 | 2.421 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.21 → 1.22.21 (yarn native cache) | `exact_hit` | `TRANSITION` | 0.027 | 0.034 | 7 | true | — |
| `PMC-007` | `pm_native_cache` | 1.22.21 → 1.22.22 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.027 | 0.029 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.22 → 3.2.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 4.957 | 5.014 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.22 → 3.8.7 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.038 | 1.043 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.22 → 4.0.2 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 3.599 | 3.701 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.22 → 4.10.3 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 1.326 | 1.344 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.22 → 4.12.0 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 4.851 | 4.896 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.22 → 4.9.1 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 2.422 | 2.431 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.22 → 1.22.21 (yarn native cache) | `incompatible_switch` | `TRANSITION` | 0.029 | 0.035 | 7 | true | dependency_view |
| `PMC-007` | `pm_native_cache` | 1.22.22 → 1.22.22 (yarn native cache) | `exact_hit` | `TRANSITION` | 0.026 | 0.032 | 7 | true | — |
| `PMC-009` | `pm_native_cache` | 1.2.18 → 1.2.18 (bun native cache) | `contention_path` | `TRANSITION` | 102.277 | 118.485 | 7 | true | — |
| `PRE-001` | `discovery_resolution` | v1 → v1 (读取/校验 profile IDs \| cold FS、warm、重复运行) | `exact_hit` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `PRE-002` | `discovery_resolution` | v1 → v1 (official profile lookup \| remote cold、local cache、missing ID) | `exact_hit` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `PRE-003` | `discovery_resolution` | v1 → v1 (Dockerfile fetch/parse \| cold/warm、remote failure) | `exact_hit` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `PRE-004` | `discovery_resolution` | v1 → v1 (manifest/config/lock discovery \| single root、多 root、large monorepo) | `exact_hit` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `PRE-005` | `discovery_resolution` | v1 → v1 (source hash/fingerprint \| small/large lock、cache hit) | `exact_hit` | `PREP` | 0.001 | 0.002 | 7 | true | — |
| `PRE-006` | `discovery_resolution` | v1 → v1 (lock authority classification \| strict/frozen/immutable/mutable/edited/missing) | `exact_hit` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `PRE-007` | `discovery_resolution` | v1 → v1 (exact-commit temporary checkout \| object cold/warm、submodules) | `exact_hit` | `PREP` | 3.086 | 3.936 | 7 | true | — |
| `PRE-008` | `discovery_resolution` | v1 → v1 (manifest transformation replay \| zero/single/workspace edits) | `exact_hit` | `PREP` | 0.002 | 0.002 | 7 | true | — |
| `PRE-014` | `discovery_resolution` | v1 → v1 (source/resolved lock diff/hash/save \| unchanged/changed/large) | `exact_hit` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `PRE-015` | `discovery_resolution` | v1 → v1 (npm lock parse \| v1/v2/v3、invalid JSON/conflict markers) | `exact_hit` | `PREP` | 0.002 | 0.002 | 7 | true | — |
| `PRE-016` | `discovery_resolution` | v1 → v1 (pnpm lock parse \| schema/version/workspace snapshots) | `exact_hit` | `PREP` | 0.002 | 0.003 | 7 | true | — |
| `PRE-017` | `discovery_resolution` | v1 → v1 (Yarn Classic lock parse \| registry/Git/file/link aliases) | `exact_hit` | `PREP` | 0.002 | 0.003 | 7 | true | — |
| `PRE-018` | `discovery_resolution` | v1 → v1 (Yarn Berry lock parse \| workspace/link/patch/virtual/locator) | `exact_hit` | `PREP` | 0.002 | 0.004 | 7 | true | — |
| `PRE-020` | `discovery_resolution` | v1 → v1 (normalized manifest generation \| registry/Git/http/workspace/local/patch/unknown) | `exact_hit` | `PREP` | 0.002 | 0.002 | 7 | true | — |
| `PRE-021` | `discovery_resolution` | v1 → v1 (global union/dedup/index \| 1k/10k/102,051 references) | `exact_hit` | `PREP` | 0.003 | 0.004 | 7 | true | — |
| `PRE-022` | `discovery_resolution` | v1 → v1 (reports/CSV generation \| cold/warm、large JSON) | `exact_hit` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `PRE-023` | `discovery_resolution` | v1 → v1 (stage reuse check \| hit、fingerprint changed、output corrupt/missing) | `exact_hit` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `PRE-024` | `discovery_resolution` | v1 → v1 (partial-stage resume \| one/many/no failures) | `exact_hit` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `REG-001` | `local_registry` | cold → v1 (registry startup-ready \| cold/restart/port conflict) | `process_cold` | `PREP` | 1.632 | 1.909 | 7 | true | — |
| `REG-002` | `local_registry` | v1 → v1 (unscoped packument GET \| single/concurrent/hit) | `exact_hit` | `PREP` | 3.958 | 4.814 | 7 | true | — |
| `REG-003` | `local_registry` | v1 → v1 (scoped packument GET \| encoding/single/concurrent) | `exact_hit` | `PREP` | 67.584 | 69.993 | 7 | true | — |
| `REG-004` | `local_registry` | v1 → v1 (local tarball GET \| size/concurrency/page-cache) | `exact_hit` | `PREP` | 285.881 | 317.475 | 7 | true | — |
| `REG-005` | `local_registry` | v1 → v1 (lock/package URL rewrite \| npm JSON、pnpm/Yarn text、large lock) | `exact_hit` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `REG-006` | `local_registry` | cold → v1 (outbound proxy startup \| cold/port conflict) | `process_cold` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `REG-007` | `local_registry` | cold → v1 (HTTP/CONNECT record-and-block \| single/burst/concurrent) | `failure_path` | `PREP` | 0.099 | 0.120 | 7 | true | — |
| `REG-008` | `local_registry` | cold → v1 (expected miss classification \| CAS/external/Git/unknown) | `failure_path` | `PREP` | 0.001 | 0.001 | 7 | true | — |
| `REG-009` | `local_registry` | cold → v1 (connection-refused recovery \| Bun observed path) | `failure_path` | `PREP` | 1.066 | 1.106 | 7 | true | — |
| `RUN-001` | `node_runtime` | cold → 18.19.1 (Node.js) | `process_cold` | `TRANSITION` | 126.513 | 130.725 | 7 | true | — |
| `RUN-001` | `node_runtime` | cold → 20.19.1 (Node.js) | `process_cold` | `TRANSITION` | 132.305 | 145.559 | 7 | true | — |
| `RUN-001` | `node_runtime` | cold → 22.23.2 (Node.js) | `process_cold` | `TRANSITION` | 127.672 | 134.432 | 7 | true | — |
| `RUN-002` | `node_runtime` | 18.19.1 → 18.19.1 (Node.js) | `exact_hit` | `TRANSITION` | 120.904 | 137.467 | 7 | true | — |
| `RUN-002` | `node_runtime` | 20.19.1 → 20.19.1 (Node.js) | `exact_hit` | `TRANSITION` | 5.008 | 5.404 | 7 | true | — |
| `RUN-002` | `node_runtime` | 22.23.2 → 22.23.2 (Node.js) | `exact_hit` | `TRANSITION` | 112.055 | 122.272 | 7 | true | — |
| `RUN-003` | `node_runtime` | cold → 18.19.1 (Node.js) | `process_cold` | `TRANSITION` | 118.997 | 134.374 | 7 | true | — |
| `RUN-003` | `node_runtime` | cold → 20.19.1 (Node.js) | `process_cold` | `TRANSITION` | 119.045 | 126.014 | 7 | true | — |
| `RUN-003` | `node_runtime` | cold → 22.23.2 (Node.js) | `process_cold` | `TRANSITION` | 123.292 | 125.888 | 7 | true | — |
| `RUN-004` | `node_runtime` | 18.19.1 → 18.19.1 (Node.js) | `exact_hit` | `TRANSITION` | 121.296 | 138.722 | 7 | true | — |
| `RUN-004` | `node_runtime` | 18.19.1 → 20.19.1 (Node.js) | `incompatible_switch` | `TRANSITION` | 121.316 | 125.156 | 7 | true | build_cache, dependency_view, native_binary_bundle, test_transform_cache |
| `RUN-004` | `node_runtime` | 18.19.1 → 22.23.2 (Node.js) | `incompatible_switch` | `TRANSITION` | 120.550 | 133.018 | 7 | true | build_cache, dependency_view, native_binary_bundle, test_transform_cache |
| `RUN-004` | `node_runtime` | 20.19.1 → 18.19.1 (Node.js) | `incompatible_switch` | `TRANSITION` | 118.770 | 129.375 | 7 | true | build_cache, dependency_view, native_binary_bundle, test_transform_cache |
| `RUN-004` | `node_runtime` | 20.19.1 → 20.19.1 (Node.js) | `exact_hit` | `TRANSITION` | 120.984 | 122.391 | 7 | true | — |
| `RUN-004` | `node_runtime` | 20.19.1 → 22.23.2 (Node.js) | `incompatible_switch` | `TRANSITION` | 129.184 | 137.238 | 7 | true | build_cache, dependency_view, native_binary_bundle, test_transform_cache |
| `RUN-004` | `node_runtime` | 22.23.2 → 18.19.1 (Node.js) | `incompatible_switch` | `TRANSITION` | 119.646 | 123.965 | 7 | true | build_cache, dependency_view, native_binary_bundle, test_transform_cache |
| `RUN-004` | `node_runtime` | 22.23.2 → 20.19.1 (Node.js) | `incompatible_switch` | `TRANSITION` | 124.884 | 130.081 | 7 | true | build_cache, dependency_view, native_binary_bundle, test_transform_cache |
| `RUN-004` | `node_runtime` | 22.23.2 → 22.23.2 (Node.js) | `exact_hit` | `TRANSITION` | 123.274 | 127.283 | 7 | true | — |
| `RUN-005` | `package_manager` | cold → 1.2.18 (bun) | `process_cold` | `TRANSITION` | 3.376 | 3.842 | 7 | true | — |
| `RUN-005` | `package_manager` | cold → 1.3.7 (bun) | `process_cold` | `TRANSITION` | 3.364 | 4.501 | 7 | true | — |
| `RUN-007` | `node_runtime` | cold → v1 (Java/JVM \| JDK+JVM args \| JVM、Gradle daemon attach/switch) | `process_cold` | `TRANSITION` | 121.180 | 130.959 | 7 | true | — |
| `RUN-008` | `node_runtime` | cold → v1 (Python \| exact+venv/site hash \| interpreter、venv switch) | `process_cold` | `TRANSITION` | 122.338 | 129.269 | 7 | true | — |
| `RUN-009` | `node_runtime` | cold → v1 (shell \| bash/dash+env \| process、login/non-login) | `process_cold` | `TRANSITION` | 122.004 | 130.021 | 7 | true | — |
| `RUN-010` | `home_tmp_xdg` | v1 → v1 (environment block \| PATH/env/config hash \| build、sanitize、restore) | `exact_hit` | `TRANSITION` | 0.031 | 0.033 | 7 | true | — |
| `SRC-001` | `source_overlay` | cold → v1 (global/node \| Git clone/fetch \| network cold、object hit、shallow/full \| PREP/PLAC) | `artifact_cold` | `TRANSITION` | 118.620 | 130.037 | 7 | true | — |
| `SRC-002` | `source_overlay` | cold → v1 (node \| exact commit checkout \| object cold/warm、repo size \| TRANSITION) | `artifact_cold` | `TRANSITION` | 12.590 | 14.082 | 7 | true | — |
| `SRC-003` | `source_overlay` | cold → v1 (node \| worktree create/remove \| first/repeated/concurrent \| TRANSITION/CLEANUP) | `artifact_cold` | `TRANSITION` | 11.709 | 12.109 | 7 | true | — |
| `SRC-005` | `source_overlay` | cold → v1 (node \| baseline snapshot create/attach \| tar/overlay/btrfs/tmpfs \| PREP/TRANSITI) | `artifact_cold` | `TRANSITION` | 0.001 | 0.001 | 7 | true | — |
| `SRC-006` | `source_overlay` | cold → v1 (task \| writable overlay create \| tree size/inodes \| TRANSITION) | `artifact_cold` | `TRANSITION` | 0.001 | 0.001 | 7 | true | — |
| `SRC-007` | `source_overlay` | cold → v1 (task \| SWE task patch apply \| clean/conflict/large patch \| TRANSITION) | `artifact_cold` | `TRANSITION` | 3.575 | 4.547 | 7 | true | — |
| `SRC-008` | `source_overlay` | v1 → v1 (task \| dirty-tree scan \| clean/few/many files \| CLEANUP) | `dirty_reset` | `CLEANUP` | 0.001 | 0.001 | 7 | true | — |
| `SRC-009` | `source_overlay` | v1 → v1 (task \| overlay discard/reset \| bytes/inodes/open handles \| CLEANUP) | `dirty_reset` | `CLEANUP` | 1.676 | 2.172 | 7 | true | — |
| `SRC-010` | `source_overlay` | cold → v1 (node/task \| dependency root attach \| root/nested/two-root profile \| TRANSITION) | `artifact_cold` | `TRANSITION` | 0.001 | 0.001 | 7 | true | — |
| `SRC-011` | `source_overlay` | cold → v1 (node \| repo page-cache effect \| logical/physical cold \| DIAGNOSTIC) | `artifact_cold` | `DIAGNOSTIC` | 0.001 | 0.001 | 7 | true | — |
| `SRC-012` | `source_overlay` | v1 → v1 (task \| generated output cleanup \| build/codegen/untracked \| CLEANUP) | `dirty_reset` | `CLEANUP` | 1.476 | 1.570 | 7 | true | — |
| `SRC-013` | `source_overlay` | v1 → v1 (task \| symlink safety/cleanup \| internal/escaping/broken \| CLEANUP/RISK) | `dirty_reset` | `TRANSITION` | 0.001 | 0.002 | 7 | true | — |
| `SRV-001` | `project_server` | cold → v1 (semantic HTTP fixture) | `process_cold` | `TRANSITION` | 2.093 | 2.607 | 7 | true | — |
| `SRV-002` | `project_server` | v1 → v1 (semantic HTTP fixture) | `exact_hit` | `TRANSITION` | 1.096 | 1.613 | 7 | true | — |
| `SRV-003` | `project_server` | v1 → v1 (semantic HTTP fixture) | `exact_hit` | `TRANSITION` | 1.006 | 1.154 | 7 | true | — |
| `SRV-004` | `project_server` | v1 → v1 (semantic HTTP fixture) | `compatible_reuse` | `TRANSITION` | 1.172 | 1.380 | 7 | true | — |
| `SRV-005` | `project_server` | v1 → v1 (semantic HTTP fixture) | `incompatible_switch` | `TRANSITION` | 1.159 | 1.260 | 7 | true | project_server |
| `SRV-006` | `project_server` | v1 → v1 (semantic HTTP fixture) | `incompatible_switch` | `TRANSITION` | 1.190 | 1.400 | 7 | true | project_server |
| `SRV-007` | `project_server` | v1 → v1 (semantic HTTP fixture) | `dirty_reset` | `TRANSITION` | 500.761 | 500.780 | 7 | true | — |
| `SRV-008` | `project_server` | v1 → v1 (semantic HTTP fixture) | `dirty_reset` | `TRANSITION` | 500.736 | 500.751 | 7 | true | — |
| `SRV-009` | `project_server` | v1 → v1 (semantic HTTP fixture) | `compatible_reuse` | `TRANSITION` | 1.117 | 1.305 | 7 | true | — |
| `SRV-010` | `project_server` | v1 → v1 (semantic HTTP fixture) | `compatible_reuse` | `TRANSITION` | 88.755 | 105.471 | 7 | true | — |
| `SYS-007` | `rootfs` | 24.04 → 24.04 (Ubuntu host rootfs) | `exact_hit` | `DIAGNOSTIC` | 139.095 | 144.535 | 7 | true | — |
| `SYS-008` | `rootfs` | 24.04 → 24.04 (Ubuntu host rootfs) | `exact_hit` | `PREP` | 118.313 | 124.494 | 7 | true | — |
| `SYS-010` | `rootfs` | 24.04 → 24.04 (Ubuntu host rootfs) | `exact_hit` | `PREP` | 236.283 | 261.509 | 7 | true | — |
| `SYS-011` | `rootfs` | 24.04 → 24.04 (Ubuntu host rootfs) | `exact_hit` | `PREP` | 5.157 | 5.937 | 7 | true | — |
| `TSK-001` | `task_harness` | cold → v1 (rollout harness) | `artifact_cold` | `TRANSITION` | 0.495 | 0.538 | 7 | true | — |
| `TSK-002` | `task_harness` | cold → v1 (rollout harness) | `artifact_cold` | `TRANSITION` | 0.449 | 0.648 | 7 | true | — |
| `TSK-003` | `task_harness` | cold → v1 (rollout harness) | `process_cold` | `EXECUTION` | 120.284 | 131.261 | 7 | true | — |
| `TSK-004` | `task_harness` | cold → v1 (rollout harness) | `process_cold` | `EXECUTION` | 116.751 | 129.457 | 7 | true | — |
| `TSK-005` | `task_harness` | cold → v1 (rollout harness) | `artifact_cold` | `EXECUTION` | 0.900 | 0.934 | 7 | true | — |
| `TSK-006` | `task_harness` | v1 → v1 (rollout harness) | `dirty_reset` | `CLEANUP` | 101.237 | 101.276 | 7 | true | — |
| `TSK-007` | `task_harness` | v1 → v1 (rollout harness) | `dirty_reset` | `CLEANUP` | 0.074 | 0.083 | 7 | true | — |
| `TSK-008` | `task_harness` | v1 → v1 (rollout harness) | `dirty_reset` | `CLEANUP` | 1.445 | 1.873 | 7 | true | — |
| `TSK-009` | `task_harness` | v1 → v1 (rollout harness) | `dirty_reset` | `CLEANUP` | 72.120 | 80.580 | 7 | true | — |
| `TSK-010` | `task_harness` | v1 → v1 (rollout harness) | `dirty_reset` | `CLEANUP` | 0.024 | 0.025 | 7 | true | — |
| `TSK-011` | `task_harness` | v1 → v1 (rollout harness) | `dirty_reset` | `CLEANUP` | 0.018 | 0.020 | 7 | true | — |
| `TSK-012` | `task_harness` | v1 → v1 (rollout harness) | `exact_hit` | `CLEANUP` | 0.043 | 0.169 | 7 | true | — |
| `TSK-013` | `task_harness` | v1 → v1 (rollout harness) | `compatible_reuse` | `DIAGNOSTIC` | 251.582 | 332.151 | 7 | true | — |
| `TSK-014` | `task_harness` | v1 → v1 (rollout harness) | `exact_hit` | `CONTROL` | 0.001 | 0.003 | 7 | true | — |
| `TST-001` | `test_transform_cache` | cold → 30.4.2 (jest) | `process_cold` | `TRANSITION` | 588.238 | 619.148 | 7 | true | — |
| `TST-001` | `test_transform_cache` | 30.4.2 → 30.4.2 (jest) | `exact_hit` | `TRANSITION` | 566.660 | 599.864 | 7 | true | — |
| `TST-002` | `test_transform_cache` | cold → 4.1.11 (vitest) | `process_cold` | `TRANSITION` | 574.836 | 585.198 | 7 | true | — |
| `TST-002` | `test_transform_cache` | 4.1.11 → 4.1.11 (vitest) | `exact_hit` | `TRANSITION` | 584.354 | 646.018 | 7 | true | — |
| `TST-003` | `test_transform_cache` | cold → 11.8.0 (mocha) | `process_cold` | `TRANSITION` | 119.274 | 120.732 | 7 | true | — |
| `TST-003` | `test_transform_cache` | 11.8.0 → 11.8.0 (mocha) | `exact_hit` | `TRANSITION` | 124.451 | 216.513 | 7 | true | — |
| `TST-004` | `test_transform_cache` | cold → 8.0.1 (ava) | `process_cold` | `TRANSITION` | 556.927 | 576.761 | 7 | true | — |
| `TST-004` | `test_transform_cache` | 8.0.1 → 8.0.1 (ava) | `exact_hit` | `TRANSITION` | 464.696 | 575.361 | 7 | true | — |
| `TST-011` | `test_transform_cache` | v1 → v1 (transform cache \| Jest/Vitest/Babel/SWC/ts-jest) | `exact_hit` | `TRANSITION` | 565.036 | 570.567 | 7 | true | — |
| `TST-012` | `test_transform_cache` | cold → v1 (worker pool \| create/reuse/reset/leak) | `process_cold` | `TRANSITION` | 114.583 | 117.784 | 7 | true | — |
| `TST-013` | `test_transform_cache` | cold → v1 (test selection/discovery \| full/target/changed files) | `exact_hit` | `TRANSITION` | 0.804 | 0.826 | 7 | true | — |
| `TST-014` | `test_transform_cache` | cold → v1 (coverage \| V8/Istanbul、cold/warm、cleanup) | `artifact_cold` | `TRANSITION` | 677.086 | 695.580 | 7 | true | — |
| `TST-015` | `test_transform_cache` | cold → v1 (failed/timeout cleanup \| process/ports/tmp/coverage) | `failure_path` | `TRANSITION` | 101.237 | 101.277 | 7 | true | — |
| `TST-016` | `test_transform_cache` | cold → v1 (isolated comparison \| reordered vs fresh result parity) | `compatible_reuse` | `TRANSITION` | 261.512 | 342.786 | 7 | true | — |

## 最大的 20 个 Direct Cost

| Rank | Benchmark | Object / transition | Median ms | P95 ms |
|---:|---|---|---:|---:|
| 1 | `CON-004` | cold → v1 (multiple dependency views) | 11365.093 | 12391.876 |
| 2 | `DEP-019` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | 2508.758 | 2571.670 |
| 3 | `CON-005` | cold → v1 (concurrent worktrees/checkouts) | 2291.425 | 3354.500 |
| 4 | `BRW-008` | cold → Mozilla Firefox 153.0.3 (firefox) | 1872.738 | 1901.830 |
| 5 | `CON-006` | cold → v1 (concurrent BrowserContexts) | 1655.737 | 2045.696 |
| 6 | `BRW-002` | Mozilla Firefox 153.0.3 → Mozilla Firefox 153.0.3 (firefox) | 999.294 | 1082.813 |
| 7 | `NAT-010` | 1.0.0 → 1.0.0 (node-gyp hello addon) | 898.706 | 938.262 |
| 8 | `NTC-002` | cold → gcc13-python3.12 (Ubuntu build toolchain) | 790.083 | 818.529 |
| 9 | `NAT-001` | cold → 1.0.0 (node-gyp hello addon) | 785.841 | 815.756 |
| 10 | `ART-004` | cold → v1 (generic Git archive fallback | cached repo、unsupported host、SSH/HTTPS) | 764.821 | 1175.459 |
| 11 | `ART-005` | cold → v1 (direct HTTP tarball | immutable/no-integrity/404) | 761.638 | 1169.992 |
| 12 | `PM-007` | cold → 10.17.1 (pnpm) | 755.363 | 814.342 |
| 13 | `DEP-002` | cold → 11.24.0 (pnpm minimal dependency view) | 701.851 | 780.749 |
| 14 | `TST-014` | cold → v1 (coverage | V8/Istanbul、cold/warm、cleanup) | 677.086 | 695.580 |
| 15 | `PM-008` | 10.4.0 → 11.24.0 (pnpm) | 656.412 | 692.640 |
| 16 | `PM-008` | 9.4.0 → 11.24.0 (pnpm) | 633.452 | 676.846 |
| 17 | `INS-008` | cold → f4a039d5d472a10b (swesmith/Automattic__mongoose.5f57a5bb:.) | 624.605 | 662.274 |
| 18 | `PM-002` | 11.24.0 → 11.24.0 (pnpm) | 618.792 | 664.967 |
| 19 | `PM-008` | 11.24.0 → 11.24.0 (pnpm) | 612.664 | 640.655 |
| 20 | `PM-008` | 9.15.4 → 11.24.0 (pnpm) | 604.455 | 633.989 |

## 最值得复用的 20 个 Object（Cold - Reuse/Reset）

| Rank | Object | Cold benchmark / ms | Safe reuse benchmark / ms | Estimated saved ms |
|---:|---|---:|---:|---:|
| 1 | `native_binary_bundle:synthetic:node-addon:abi109` (node-gyp hello addon) | `NAT-001` / 785.841 | `NAT-002` / 116.259 | 669.582 |
| 2 | `package_manager:pnpm:default:10.17.1:linux:x86_64` (pnpm) | `PM-007` / 755.363 | `PM-002` / 349.785 | 405.578 |
| 3 | `dependency_view:Automattic__mongoose.5f57a5bb:root:f4a039d5d472a10b` (swesmith/Automattic__mongoose.5f57a5bb:.) | `INS-001` / 385.909 | `DEP-010` / 0.353 | 385.556 |
| 4 | `browser_process:chromium:151.0.7922.77:headless` (chromium) | `BRW-007` / 281.798 | `BRW-010` / 0.607 | 281.191 |
| 5 | `build_cache:synthetic:typescript:7.0.2` (typescript) | `BLD-002` / 525.485 | `BLD-002` / 251.988 | 273.497 |
| 6 | `test_transform_cache:synthetic:ava:8.0.1` (ava) | `TST-004` / 556.927 | `TST-004` / 464.696 | 92.231 |
| 7 | `test_transform_cache:synthetic:jest:30.4.2` (jest) | `TST-001` / 588.238 | `TST-001` / 566.660 | 21.578 |
| 8 | `dependency_view:fixture:yarn:3.8.7` (yarn minimal dependency view) | `DEP-004` / 374.669 | `DEP-005` / 357.662 | 17.007 |
| 9 | `database_daemon:redis:Redis server v=7.0.15 sha=00000000:0 malloc=jemalloc-5.3.0 bits=64 build=e53ff17674aa6190:default` (redis) | `DBS-001` / 14.710 | `DBS-004` / 0.071 | 14.639 |
| 10 | `home_tmp_xdg:isolated-template:v1` (isolated HOME/tmp/XDG) | `FS-005` / 14.770 | `FS-007` / 1.431 | 13.340 |
| 11 | `build_cache:synthetic:babel:7.28.4` (babel) | `BLD-004` / 240.250 | `BLD-004` / 232.898 | 7.351 |
| 12 | `dependency_view:fixture:yarn:4.0.2` (yarn minimal dependency view) | `DEP-004` / 371.879 | `DEP-005` / 367.836 | 4.043 |
| 13 | `build_cache:synthetic:rollup:4.63.1` (rollup) | `BLD-007` / 119.888 | `BLD-007` / 115.849 | 4.039 |
| 14 | `build_cache:synthetic:vite:8.2.2` (vite) | `BLD-009` / 355.514 | `BLD-009` / 351.748 | 3.767 |
| 15 | `browser_profile:chromium:151.0.7922.77:ephemeral` (chromium profile) | `BRW-013` / 5.102 | `BRW-014` / 1.524 | 3.577 |
| 16 | `dependency_view:fixture:yarn:4.12.0` (yarn minimal dependency view) | `DEP-004` / 377.344 | `DEP-005` / 375.754 | 1.590 |
| 17 | `database_private_layer:sqlite:python-stdlib:task` (sqlite private layer) | `DBS-010` / 1.478 | `DBS-008` / 0.023 | 1.455 |
| 18 | `dependency_view:fixture:yarn:3.2.3` (yarn minimal dependency view) | `DEP-004` / 381.055 | `DEP-005` / 379.874 | 1.181 |
| 19 | `project_server:synthetic:http:v1` (semantic HTTP fixture) | `SRV-001` / 2.093 | `SRV-003` / 1.006 | 1.087 |
| 20 | `database_clean_snapshot:sqlite:python-stdlib:minimal` (sqlite clean snapshot) | `DBS-005` / 0.443 | `DBS-006` / 0.434 | 0.009 |
