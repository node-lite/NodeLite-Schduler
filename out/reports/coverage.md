# NodeLite 第一阶段 Benchmark Coverage

- Catalog IDs: 316
- Accounted IDs: 316
- IDs with observations: 265
- Coverage: 100.0%
- Status counts: `blocked`=11, `manual_review`=7, `measured`=265, `not_applicable`=1, `unsupported`=32

| Benchmark ID | Group | Priority | Status | Reason |
|---|---|---|---|---|
| `CTL-001` | control | P0 | `measured` | 1 scenario(s) measured |
| `CTL-002` | control | P0 | `measured` | 1 scenario(s) measured |
| `CTL-003` | control | P0 | `measured` | 1 scenario(s) measured |
| `CTL-004` | control | P0 | `measured` | 1 scenario(s) measured |
| `CTL-005` | control | P0 | `measured` | 1 scenario(s) measured |
| `CTL-006` | control | P0 | `measured` | 1 scenario(s) measured |
| `CTL-007` | control | P0 | `measured` | 1 scenario(s) measured |
| `CTL-008` | control | P0 | `measured` | 1 scenario(s) measured |
| `CTL-009` | control | P0 | `measured` | 1 scenario(s) measured |
| `CTL-010` | control | P1 | `measured` | 1 scenario(s) measured |
| `CTL-011` | control | P1 | `measured` | 1 scenario(s) measured |
| `CTL-012` | control | P1 | `measured` | 1 scenario(s) measured |
| `PRE-001` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-002` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-003` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-004` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-005` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-006` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-007` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-008` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-009` | prep | P0-64 | `manual_review` | exact npm lock-only resolution needs per-profile temporary checkouts and is not reconstructed by this host fixture |
| `PRE-010` | prep | P0-64 | `manual_review` | exact pnpm lock-only resolution needs per-profile temporary checkouts and is not reconstructed by this host fixture |
| `PRE-011` | prep | P0-64 | `manual_review` | exact Yarn Classic resolution needs per-profile temporary checkouts and is not reconstructed by this host fixture |
| `PRE-012` | prep | P0-64 | `manual_review` | exact Yarn Berry update-lockfile needs project-local config replay and per-profile temporary checkouts |
| `PRE-013` | prep | P0-64 | `manual_review` | exact Bun resolution needs project-local Bun lock semantics replay |
| `PRE-014` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-015` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-016` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-017` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-018` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-019` | prep | P0-64 | `manual_review` | Bun text/binary lock parser variants need dedicated fixture corpus |
| `PRE-020` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-021` | prep | P0-64 | `measured` | 1 scenario(s) measured |
| `PRE-022` | prep | P1 | `measured` | 1 scenario(s) measured |
| `PRE-023` | prep | P0 | `measured` | 1 scenario(s) measured |
| `PRE-024` | prep | P0 | `measured` | 1 scenario(s) measured |
| `SRC-001` | source | P0-64 | `measured` | 1 scenario(s) measured |
| `SRC-002` | source | P0-64 | `measured` | 1 scenario(s) measured |
| `SRC-003` | source | P0-64 | `measured` | 1 scenario(s) measured |
| `SRC-004` | source | P0-64 | `not_applicable` | the 64-profile CTDP source snapshots contain no checked-out Git submodule repositories |
| `SRC-005` | source | P0 | `measured` | 1 scenario(s) measured |
| `SRC-006` | source | P0 | `measured` | 1 scenario(s) measured |
| `SRC-007` | source | P0 | `measured` | 1 scenario(s) measured |
| `SRC-008` | source | P0 | `measured` | 1 scenario(s) measured |
| `SRC-009` | source | P0 | `measured` | 1 scenario(s) measured |
| `SRC-010` | source | P0-64 | `measured` | 1 scenario(s) measured |
| `SRC-011` | source | P1 | `measured` | 1 scenario(s) measured |
| `SRC-012` | source | P1 | `measured` | 1 scenario(s) measured |
| `SRC-013` | source | P0 | `measured` | 1 scenario(s) measured |
| `ART-001` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `ART-002` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `ART-003` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `ART-004` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `ART-005` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `ART-006` | artifact | P0 | `measured` | 1 scenario(s) measured |
| `ART-007` | artifact | P1 | `manual_review` | system package network measurement requires an isolated apt rootfs |
| `ART-008` | artifact | P0 | `measured` | 1 scenario(s) measured |
| `CAS-001` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `CAS-002` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `CAS-003` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `CAS-004` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `CAS-005` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `CAS-006` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `CAS-007` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `CAS-008` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `CAS-009` | artifact | P0 | `measured` | 1 scenario(s) measured |
| `CAS-010` | artifact | P1 | `measured` | 1 scenario(s) measured |
| `REG-001` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `REG-002` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `REG-003` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `REG-004` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `REG-005` | artifact | P0-64 | `measured` | 1 scenario(s) measured |
| `REG-006` | artifact | P0 | `measured` | 1 scenario(s) measured |
| `REG-007` | artifact | P0 | `measured` | 1 scenario(s) measured |
| `REG-008` | artifact | P0 | `measured` | 1 scenario(s) measured |
| `REG-009` | artifact | P0 | `measured` | 1 scenario(s) measured |
| `RUN-001` | runtime | P0-64 | `measured` | 3 scenario(s) measured |
| `RUN-002` | runtime | P0-64 | `measured` | 3 scenario(s) measured |
| `RUN-003` | runtime | P0-64 | `measured` | 3 scenario(s) measured |
| `RUN-004` | runtime | P0-64 | `measured` | 9 scenario(s) measured |
| `RUN-005` | runtime | P0-64 | `measured` | 2 scenario(s) measured |
| `RUN-006` | runtime | P1 | `unsupported` | Deno executable/cache is not installed |
| `RUN-007` | runtime | P1 | `measured` | 1 scenario(s) measured |
| `RUN-008` | runtime | P1 | `measured` | 1 scenario(s) measured |
| `RUN-009` | runtime | P1 | `measured` | 1 scenario(s) measured |
| `RUN-010` | runtime | P1 | `measured` | 1 scenario(s) measured |
| `PM-001` | pm | P0-64 | `measured` | 1 scenario(s) measured |
| `PM-002` | pm | P0-64 | `measured` | 11 scenario(s) measured |
| `PM-003` | pm | P0-64 | `measured` | 2 scenario(s) measured |
| `PM-004` | pm | P0-64 | `measured` | 6 scenario(s) measured |
| `PM-005` | pm | P0-64 | `measured` | 2 scenario(s) measured |
| `PM-006` | pm | P0-64 | `unsupported` | Corepack executable is not installed |
| `PM-007` | pm | P1 | `measured` | 1 scenario(s) measured |
| `PM-008` | pm | P0 | `measured` | 190 scenario(s) measured |
| `PMC-001` | pm | P0-64 | `measured` | 2 scenario(s) measured |
| `PMC-002` | pm | P0-64 | `measured` | 11 scenario(s) measured |
| `PMC-003` | pm | P0-64 | `measured` | 2 scenario(s) measured |
| `PMC-004` | pm | P0-64 | `measured` | 6 scenario(s) measured |
| `PMC-005` | pm | P0-64 | `measured` | 2 scenario(s) measured |
| `PMC-006` | pm | P0 | `measured` | 1 scenario(s) measured |
| `PMC-007` | pm | P0 | `measured` | 193 scenario(s) measured |
| `PMC-008` | pm | P1 | `unsupported` | no isolated quota filesystem for eviction/near-full measurement |
| `PMC-009` | pm | P1 | `measured` | 1 scenario(s) measured |
| `DEP-001` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `DEP-002` | dependency | P0-64 | `measured` | 11 scenario(s) measured |
| `DEP-003` | dependency | P0-64 | `measured` | 2 scenario(s) measured |
| `DEP-004` | dependency | P0-64 | `measured` | 6 scenario(s) measured |
| `DEP-005` | dependency | P0 | `measured` | 6 scenario(s) measured |
| `DEP-006` | dependency | P0-64 | `measured` | 2 scenario(s) measured |
| `DEP-007` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `DEP-008` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `DEP-009` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `DEP-010` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `DEP-011` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `DEP-012` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `DEP-013` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `DEP-014` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `DEP-015` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `DEP-016` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `DEP-017` | dependency | P0 | `unsupported` | no semantically valid runner is available in the current measurement environment |
| `DEP-018` | dependency | P0 | `measured` | 1 scenario(s) measured |
| `DEP-019` | dependency | P1 | `measured` | 1 scenario(s) measured |
| `DEP-020` | dependency | P1 | `measured` | 1 scenario(s) measured |
| `INS-001` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `INS-002` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `INS-003` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `INS-004` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `INS-005` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `INS-006` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `INS-007` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `INS-008` | dependency | P0-64 | `measured` | 1 scenario(s) measured |
| `INS-009` | dependency | P0 | `measured` | 1 scenario(s) measured |
| `INS-010` | dependency | P0 | `measured` | 1 scenario(s) measured |
| `BLD-001` | build | P0-64 | `measured` | 1 scenario(s) measured |
| `BLD-002` | build | P0-64 | `measured` | 3 scenario(s) measured |
| `BLD-003` | build | P1 | `measured` | 1 scenario(s) measured |
| `BLD-004` | build | P0-64 | `measured` | 3 scenario(s) measured |
| `BLD-005` | build | P0-64 | `measured` | 3 scenario(s) measured |
| `BLD-006` | build | P0-64 | `measured` | 3 scenario(s) measured |
| `BLD-007` | build | P0-64 | `measured` | 3 scenario(s) measured |
| `BLD-008` | build | P0-64 | `measured` | 3 scenario(s) measured |
| `BLD-009` | build | P0-64 | `measured` | 3 scenario(s) measured |
| `BLD-010` | build | P0 | `unsupported` | Next.js fixture was not materialized in the first host run |
| `BLD-011` | build | P0-64 | `unsupported` | Nx daemon fixture was not materialized in the first host run |
| `BLD-012` | build | P0-64 | `unsupported` | Turborepo fixture was not materialized in the first host run |
| `BLD-013` | build | P1 | `unsupported` | Gulp/Grunt watch fixture was not materialized in the first host run |
| `BLD-014` | build | P0-64 | `unsupported` | Lerna/preconstruct/manypkg fixture was not materialized in the first host run |
| `BLD-015` | build | P1 | `unsupported` | Changesets/Rush fixture was not materialized in the first host run |
| `BLD-016` | build | P0-64 | `measured` | 1 scenario(s) measured |
| `BLD-017` | build | P0-64 | `measured` | 1 scenario(s) measured |
| `BLD-018` | build | P1 | `unsupported` | protoc is not installed |
| `BLD-019` | build | P1 | `unsupported` | Prisma engine fixture is not installed |
| `BLD-020` | build | P0 | `measured` | 1 scenario(s) measured |
| `BLD-021` | build | P0 | `measured` | 1 scenario(s) measured |
| `BLD-022` | build | P0 | `measured` | 1 scenario(s) measured |
| `TST-001` | test | P0-64 | `measured` | 2 scenario(s) measured |
| `TST-002` | test | P0-64 | `measured` | 2 scenario(s) measured |
| `TST-003` | test | P0-64 | `measured` | 2 scenario(s) measured |
| `TST-004` | test | P0 | `measured` | 2 scenario(s) measured |
| `TST-005` | test | P0-64 | `unsupported` | Karma launcher fixture is not installed |
| `TST-006` | test | P0-64 | `unsupported` | Nightwatch/WebDriver fixture is not installed |
| `TST-007` | test | P0-64 | `unsupported` | Cypress binary cache is empty |
| `TST-008` | test | P0-64 | `unsupported` | Playwright driver/browser cache is empty |
| `TST-009` | test | P1 | `unsupported` | Puppeteer driver fixture is not installed |
| `TST-010` | test | P1 | `unsupported` | Selenium/WebDriver fixture is not installed |
| `TST-011` | test | P0 | `measured` | 1 scenario(s) measured |
| `TST-012` | test | P0 | `measured` | 1 scenario(s) measured |
| `TST-013` | test | P0 | `measured` | 1 scenario(s) measured |
| `TST-014` | test | P1 | `measured` | 1 scenario(s) measured |
| `TST-015` | test | P0 | `measured` | 1 scenario(s) measured |
| `TST-016` | test | P0 | `measured` | 1 scenario(s) measured |
| `BRW-001` | browser | P0-64 | `measured` | 1 scenario(s) measured |
| `BRW-002` | browser | P0 | `measured` | 1 scenario(s) measured |
| `BRW-003` | browser | P0 | `unsupported` | WebKit binary is not installed |
| `BRW-004` | browser | P0-64 | `measured` | 1 scenario(s) measured |
| `BRW-005` | browser | P0-64 | `measured` | 1 scenario(s) measured |
| `BRW-006` | browser | P0-64 | `measured` | 1 scenario(s) measured |
| `BRW-007` | browser | P0-64 | `measured` | 1 scenario(s) measured |
| `BRW-008` | browser | P0 | `measured` | 1 scenario(s) measured |
| `BRW-009` | browser | P0 | `unsupported` | WebKit binary is not installed |
| `BRW-010` | browser | P0-64 | `measured` | 1 scenario(s) measured |
| `BRW-011` | browser | P0-64 | `measured` | 1 scenario(s) measured |
| `BRW-012` | browser | P0-64 | `measured` | 1 scenario(s) measured |
| `BRW-013` | browser | P0-64 | `measured` | 1 scenario(s) measured |
| `BRW-014` | browser | P0-64 | `measured` | 1 scenario(s) measured |
| `BRW-015` | browser | P0-64 | `measured` | 1 scenario(s) measured |
| `BRW-016` | browser | P0 | `measured` | 1 scenario(s) measured |
| `BRW-017` | browser | P0 | `measured` | 1 scenario(s) measured |
| `BRW-018` | browser | P0-64 | `measured` | 1 scenario(s) measured |
| `BRW-019` | browser | P0 | `measured` | 1 scenario(s) measured |
| `GUI-001` | browser | P0 | `measured` | 1 scenario(s) measured |
| `GUI-002` | browser | P0 | `measured` | 1 scenario(s) measured |
| `GUI-003` | browser | P0 | `measured` | 1 scenario(s) measured |
| `GUI-004` | browser | P1 | `measured` | 1 scenario(s) measured |
| `GUI-005` | browser | P1 | `measured` | 1 scenario(s) measured |
| `GUI-006` | browser | P1 | `measured` | 1 scenario(s) measured |
| `DB-001` | database | P0-64 | `unsupported` | MongoDB binary is not installed and Docker daemon access is denied |
| `DB-002` | database | P0 | `unsupported` | PostgreSQL binary is not installed and Docker daemon access is denied |
| `DB-003` | database | P0 | `unsupported` | MySQL binary is not installed and Docker daemon access is denied |
| `DB-004` | database | P0 | `measured` | 1 scenario(s) measured |
| `DB-005` | database | P0-64 | `measured` | 1 scenario(s) measured |
| `DB-006` | database | P0-64 | `unsupported` | mongodb-memory-server binary cache is not installed |
| `DBS-001` | database | P0 | `measured` | 1 scenario(s) measured |
| `DBS-002` | database | P0 | `measured` | 1 scenario(s) measured |
| `DBS-003` | database | P0 | `measured` | 1 scenario(s) measured |
| `DBS-004` | database | P0 | `measured` | 1 scenario(s) measured |
| `DBS-005` | database | P0 | `measured` | 1 scenario(s) measured |
| `DBS-006` | database | P0 | `measured` | 1 scenario(s) measured |
| `DBS-007` | database | P0 | `measured` | 1 scenario(s) measured |
| `DBS-008` | database | P0 | `measured` | 1 scenario(s) measured |
| `DBS-009` | database | P0 | `measured` | 1 scenario(s) measured |
| `DBS-010` | database | P0 | `measured` | 1 scenario(s) measured |
| `DBS-011` | database | P0 | `measured` | 1 scenario(s) measured |
| `DBS-012` | database | P0 | `unsupported` | only one measurable DB daemon version (Redis 7.0.15) is installed |
| `DBS-013` | database | P0 | `measured` | 1 scenario(s) measured |
| `NAT-001` | native | P0 | `measured` | 1 scenario(s) measured |
| `NAT-002` | native | P0 | `measured` | 1 scenario(s) measured |
| `NAT-003` | native | P0-64 | `unsupported` | canvas native binding fixture is not installed |
| `NAT-004` | native | P0-64 | `measured` | 1 scenario(s) measured |
| `NAT-005` | native | P0-64 | `measured` | 1 scenario(s) measured |
| `NAT-006` | native | P0-64 | `measured` | 1 scenario(s) measured |
| `NAT-007` | native | P0-64 | `measured` | 1 scenario(s) measured |
| `NAT-008` | native | P1 | `unsupported` | Prisma engine fixture is not installed |
| `NAT-009` | native | P1 | `unsupported` | native gRPC binding fixture is not installed |
| `NAT-010` | native | P0 | `measured` | 1 scenario(s) measured |
| `NTC-001` | native | P0-64 | `measured` | 1 scenario(s) measured |
| `NTC-002` | native | P0-64 | `measured` | 1 scenario(s) measured |
| `NTC-003` | native | P0-64 | `measured` | 1 scenario(s) measured |
| `NTC-004` | native | P1 | `unsupported` | Clang/LLVM executable is not installed |
| `NTC-005` | native | P1 | `measured` | 1 scenario(s) measured |
| `NTC-006` | native | P1 | `unsupported` | Ninja executable is not installed |
| `NTC-007` | native | P1 | `unsupported` | Rust/Cargo toolchain is not installed |
| `NTC-008` | native | P1 | `measured` | 1 scenario(s) measured |
| `NTC-009` | native | P1 | `measured` | 1 scenario(s) measured |
| `NTC-010` | native | P1 | `measured` | 1 scenario(s) measured |
| `NTC-011` | native | P1 | `unsupported` | ccache/sccache executable is not installed |
| `NTC-012` | native | P0 | `measured` | 1 scenario(s) measured |
| `SYS-001` | system | P0 | `blocked` | Docker daemon access is denied; image acquisition cannot be measured on this host |
| `SYS-002` | system | P0 | `blocked` | Docker daemon access is denied; rootfs unpack/snapshot cannot be measured |
| `SYS-003` | system | P0 | `blocked` | mount/container privileges are unavailable for rootfs attach |
| `SYS-004` | system | P0 | `blocked` | mount/container privileges are unavailable for rootfs unmount/reset |
| `SYS-005` | system | P1 | `blocked` | apt index refresh mutates shared host package state and root/container isolation is unavailable |
| `SYS-006` | system | P1 | `blocked` | apt install mutates shared host package state and root/container isolation is unavailable |
| `SYS-007` | system | P1 | `measured` | 1 scenario(s) measured |
| `SYS-008` | system | P1 | `measured` | 1 scenario(s) measured |
| `SYS-009` | system | P1 | `blocked` | no glibc/musl rootfs pair and Docker daemon access is denied |
| `SYS-010` | system | P1 | `measured` | 1 scenario(s) measured |
| `SYS-011` | system | P1 | `measured` | 1 scenario(s) measured |
| `FS-001` | filesystem | P0 | `measured` | 1 scenario(s) measured |
| `FS-002` | filesystem | P0 | `measured` | 1 scenario(s) measured |
| `FS-003` | filesystem | P0 | `measured` | 1 scenario(s) measured |
| `FS-004` | filesystem | P1 | `measured` | 1 scenario(s) measured |
| `FS-005` | filesystem | P0 | `measured` | 1 scenario(s) measured |
| `FS-006` | filesystem | P0 | `measured` | 1 scenario(s) measured |
| `FS-007` | filesystem | P0 | `measured` | 1 scenario(s) measured |
| `FS-008` | filesystem | P0 | `measured` | 1 scenario(s) measured |
| `FS-009` | filesystem | P0 | `measured` | 1 scenario(s) measured |
| `FS-010` | filesystem | P1 | `measured` | 1 scenario(s) measured |
| `NET-001` | network | P0 | `blocked` | unshare(CLONE_NEWNET) is denied by the host |
| `NET-002` | network | P0 | `blocked` | unshare(CLONE_NEWNET) is denied by the host |
| `NET-003` | network | P0 | `measured` | 1 scenario(s) measured |
| `NET-004` | network | P0 | `measured` | 1 scenario(s) measured |
| `NET-005` | network | P0 | `measured` | 1 scenario(s) measured |
| `NET-006` | network | P0 | `measured` | 1 scenario(s) measured |
| `NET-007` | network | P1 | `measured` | 1 scenario(s) measured |
| `NET-008` | network | P0 | `measured` | 1 scenario(s) measured |
| `NET-009` | network | P0 | `measured` | 1 scenario(s) measured |
| `NET-010` | network | P0 | `measured` | 1 scenario(s) measured |
| `SRV-001` | server | P0 | `measured` | 1 scenario(s) measured |
| `SRV-002` | server | P0 | `measured` | 1 scenario(s) measured |
| `SRV-003` | server | P0 | `measured` | 1 scenario(s) measured |
| `SRV-004` | server | P0 | `measured` | 1 scenario(s) measured |
| `SRV-005` | server | P0 | `measured` | 1 scenario(s) measured |
| `SRV-006` | server | P0 | `measured` | 1 scenario(s) measured |
| `SRV-007` | server | P0 | `measured` | 1 scenario(s) measured |
| `SRV-008` | server | P0 | `measured` | 1 scenario(s) measured |
| `SRV-009` | server | P0 | `measured` | 1 scenario(s) measured |
| `SRV-010` | server | P1 | `measured` | 1 scenario(s) measured |
| `TSK-001` | task | P0 | `measured` | 1 scenario(s) measured |
| `TSK-002` | task | P0 | `measured` | 1 scenario(s) measured |
| `TSK-003` | task | P0 | `measured` | 1 scenario(s) measured |
| `TSK-004` | task | P0 | `measured` | 1 scenario(s) measured |
| `TSK-005` | task | P0 | `measured` | 1 scenario(s) measured |
| `TSK-006` | task | P0 | `measured` | 1 scenario(s) measured |
| `TSK-007` | task | P0 | `measured` | 1 scenario(s) measured |
| `TSK-008` | task | P0 | `measured` | 1 scenario(s) measured |
| `TSK-009` | task | P0 | `measured` | 1 scenario(s) measured |
| `TSK-010` | task | P0 | `measured` | 1 scenario(s) measured |
| `TSK-011` | task | P0 | `measured` | 1 scenario(s) measured |
| `TSK-012` | task | P0 | `measured` | 1 scenario(s) measured |
| `TSK-013` | task | P0 | `measured` | 1 scenario(s) measured |
| `TSK-014` | task | P0 | `measured` | 1 scenario(s) measured |
| `FAIL-001` | failure | P0-64 | `measured` | 1 scenario(s) measured |
| `FAIL-002` | failure | P0-64 | `measured` | 1 scenario(s) measured |
| `FAIL-003` | failure | P0-64 | `measured` | 1 scenario(s) measured |
| `FAIL-004` | failure | P0-64 | `measured` | 1 scenario(s) measured |
| `FAIL-005` | failure | P0-64 | `measured` | 1 scenario(s) measured |
| `FAIL-006` | failure | P0-64 | `measured` | 1 scenario(s) measured |
| `FAIL-007` | failure | P0-64 | `measured` | 1 scenario(s) measured |
| `FAIL-008` | failure | P0 | `measured` | 1 scenario(s) measured |
| `FAIL-009` | failure | P0 | `measured` | 1 scenario(s) measured |
| `FAIL-010` | failure | P0 | `blocked` | safe isolated disk/inode quota is unavailable; filling the shared 44 TB filesystem is prohibited |
| `FAIL-011` | failure | P0 | `blocked` | isolated writable cgroup/OOM fixture is unavailable |
| `FAIL-012` | failure | P0 | `measured` | 1 scenario(s) measured |
| `FAIL-013` | failure | P0 | `measured` | 1 scenario(s) measured |
| `FAIL-014` | failure | P1 | `measured` | 1 scenario(s) measured |
| `CON-001` | contention | P0 | `measured` | 1 scenario(s) measured |
| `CON-002` | contention | P0 | `measured` | 1 scenario(s) measured |
| `CON-003` | contention | P0 | `measured` | 1 scenario(s) measured |
| `CON-004` | contention | P0 | `measured` | 1 scenario(s) measured |
| `CON-005` | contention | P1 | `measured` | 1 scenario(s) measured |
| `CON-006` | contention | P1 | `measured` | 1 scenario(s) measured |
| `CON-007` | contention | P1 | `measured` | 1 scenario(s) measured |
| `CON-008` | contention | P1 | `measured` | 1 scenario(s) measured |
| `CON-009` | contention | P1 | `measured` | 1 scenario(s) measured |
| `CON-010` | contention | P1 | `measured` | 1 scenario(s) measured |
