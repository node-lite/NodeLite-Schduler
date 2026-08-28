# Measurement Environment Gaps

The following benchmark IDs have no fabricated latency value. They remain explicit gaps for a capable host.

| Benchmark ID | Status | Required capability / reason |
|---|---|---|
| `ART-007` | `manual_review` | system package network measurement requires an isolated apt rootfs |
| `BLD-010` | `unsupported` | Next.js fixture was not materialized in the first host run |
| `BLD-011` | `unsupported` | Nx daemon fixture was not materialized in the first host run |
| `BLD-012` | `unsupported` | Turborepo fixture was not materialized in the first host run |
| `BLD-013` | `unsupported` | Gulp/Grunt watch fixture was not materialized in the first host run |
| `BLD-014` | `unsupported` | Lerna/preconstruct/manypkg fixture was not materialized in the first host run |
| `BLD-015` | `unsupported` | Changesets/Rush fixture was not materialized in the first host run |
| `BLD-018` | `unsupported` | protoc is not installed |
| `BLD-019` | `unsupported` | Prisma engine fixture is not installed |
| `BRW-003` | `unsupported` | WebKit binary is not installed |
| `BRW-009` | `unsupported` | WebKit binary is not installed |
| `DB-001` | `unsupported` | MongoDB binary is not installed and Docker daemon access is denied |
| `DB-002` | `unsupported` | PostgreSQL binary is not installed and Docker daemon access is denied |
| `DB-003` | `unsupported` | MySQL binary is not installed and Docker daemon access is denied |
| `DB-006` | `unsupported` | mongodb-memory-server binary cache is not installed |
| `DBS-012` | `unsupported` | only one measurable DB daemon version (Redis 7.0.15) is installed |
| `DEP-017` | `unsupported` | no semantically valid runner is available in the current measurement environment |
| `FAIL-010` | `blocked` | safe isolated disk/inode quota is unavailable; filling the shared 44 TB filesystem is prohibited |
| `FAIL-011` | `blocked` | isolated writable cgroup/OOM fixture is unavailable |
| `NAT-003` | `unsupported` | canvas native binding fixture is not installed |
| `NAT-008` | `unsupported` | Prisma engine fixture is not installed |
| `NAT-009` | `unsupported` | native gRPC binding fixture is not installed |
| `NET-001` | `blocked` | unshare(CLONE_NEWNET) is denied by the host |
| `NET-002` | `blocked` | unshare(CLONE_NEWNET) is denied by the host |
| `NTC-004` | `unsupported` | Clang/LLVM executable is not installed |
| `NTC-006` | `unsupported` | Ninja executable is not installed |
| `NTC-007` | `unsupported` | Rust/Cargo toolchain is not installed |
| `NTC-011` | `unsupported` | ccache/sccache executable is not installed |
| `PM-006` | `unsupported` | Corepack executable is not installed |
| `PMC-008` | `unsupported` | no isolated quota filesystem for eviction/near-full measurement |
| `PRE-009` | `manual_review` | exact npm lock-only resolution needs per-profile temporary checkouts and is not reconstructed by this host fixture |
| `PRE-010` | `manual_review` | exact pnpm lock-only resolution needs per-profile temporary checkouts and is not reconstructed by this host fixture |
| `PRE-011` | `manual_review` | exact Yarn Classic resolution needs per-profile temporary checkouts and is not reconstructed by this host fixture |
| `PRE-012` | `manual_review` | exact Yarn Berry update-lockfile needs project-local config replay and per-profile temporary checkouts |
| `PRE-013` | `manual_review` | exact Bun resolution needs project-local Bun lock semantics replay |
| `PRE-019` | `manual_review` | Bun text/binary lock parser variants need dedicated fixture corpus |
| `RUN-006` | `unsupported` | Deno executable/cache is not installed |
| `SYS-001` | `blocked` | Docker daemon access is denied; image acquisition cannot be measured on this host |
| `SYS-002` | `blocked` | Docker daemon access is denied; rootfs unpack/snapshot cannot be measured |
| `SYS-003` | `blocked` | mount/container privileges are unavailable for rootfs attach |
| `SYS-004` | `blocked` | mount/container privileges are unavailable for rootfs unmount/reset |
| `SYS-005` | `blocked` | apt index refresh mutates shared host package state and root/container isolation is unavailable |
| `SYS-006` | `blocked` | apt install mutates shared host package state and root/container isolation is unavailable |
| `SYS-009` | `blocked` | no glibc/musl rootfs pair and Docker daemon access is denied |
| `TST-005` | `unsupported` | Karma launcher fixture is not installed |
| `TST-006` | `unsupported` | Nightwatch/WebDriver fixture is not installed |
| `TST-007` | `unsupported` | Cypress binary cache is empty |
| `TST-008` | `unsupported` | Playwright driver/browser cache is empty |
| `TST-009` | `unsupported` | Puppeteer driver fixture is not installed |
| `TST-010` | `unsupported` | Selenium/WebDriver fixture is not installed |
| `PM/PMC` | `object_gap` | `package_manager:npm:default:unknown:linux:x86_64` is retained from CTDP resolution tool_version, but no exact executable/cache path/version is available for latency measurement. |
| `PM/PMC` | `object_gap` | `package_manager:yarn:berry:unknown:linux:x86_64` is retained from CTDP resolution tool_version, but no exact executable/cache path/version is available for latency measurement. |
| `PM/PMC` | `object_gap` | `pm_native_cache:yarn:berry:unknown` is retained from CTDP warm-cache policy, but no exact executable/cache path/version is available for latency measurement. |
