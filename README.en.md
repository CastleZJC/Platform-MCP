# Platform-MCP

> Internal MCP (Model Context Protocol) capability platform
> Dual Skills: Database (SQL execution) + Server (Linux SSH/SFTP) — 11 MCP tools in total, invoked remotely by callers such as Claude Code, equipped with a Web management portal and full-chain audit

**Language**: [中文](README.md) | English

## Project Overview

Platform-MCP is an internal MCP service platform providing:

- **Database Skill (5 tools)**: execute local SQL files / SQL text / risk validation / list datasources / async status query
- **Server Skill (6 tools)**: Linux remote shell execution / SFTP upload & download / command risk validation / list servers / async status query
- **Dual-transport MCP Server**: stdio (environment variable) + streamable-http (header) dual entry
- **API Key authentication**: dual storage (key_hash SHA-256 for verification + key_encrypted AES-GCM for admin reveal)
- **Web management portal**: datasource management + server management + user management + API Key management + audit logs + profile settings
- **Permission control**: admin/developer dual roles, developer forbidden on PROD; server and datasource permissions independent
- **Risk engine**: shared 4 levels for SQL and shell (LOW/MEDIUM/HIGH/CRITICAL); HIGH+ requires `confirm_token` anti-replay second confirmation
- **Chinese/English bilingual (V3.0 M1)**: frontend-wide vue-i18n keying + backend resource dictionary + MCP tool descriptions in both languages; switching in profile settings takes effect after re-login (no process restart)
- **Runtime config center (V3.0 M1)**: known-key registry (12 keys, effect semantics relogin/immediate, credential values write-only) + 30s snapshot cache; non-restart items such as default locale / session timeout / log level are managed uniformly on the system config page

## Quick Start

### Prerequisites

- Python 3.11.9
- PostgreSQL 16.4 (system database)
- Oracle 11g / MySQL 5.6 (target databases, optional)

### Backend Startup

```bash
# 1. Install dependencies
pip install -e ".[dev]"

# 2. Create local config (database.url required)
cp settings.yml.example settings.yml
# Edit settings.yml, replace <password> / HOST with your actual PostgreSQL values

# 3. Prepare PostgreSQL: create database + user
createdb platform_mcp
psql -d platform_mcp -c "CREATE USER pmcp WITH PASSWORD '<your-password>';"

# 4. Set Alembic DB URL (for migrations; can be persisted in ~/.bashrc)
export PLATFORM_DB_URL="postgresql://pmcp:<password>@localhost:5432/platform_mcp"

# 5. Generate crypto key + Alembic upgrade + check seed users
python scripts/_setup_local.py

# 6. Seed database + server skills into pmcp_skill table
python scripts/_seed_skill.py

# 7. Start FastAPI Web (default port 8000)
python -m platform_mcp.main

# 8. Start MCP Server (mode determined by settings.mcp.transport)
python -m platform_mcp.mcp_server
```

### Frontend Startup

```bash
cd platform-mcp-frontend
npm install
npm run dev    # default port 5173 (auto-increment if taken)
```

Visit `http://localhost:5173`, default account: `admin` / `admin123`

### Database Initialization

```bash
# Generate encryption key + Alembic upgrade + check seed users
python scripts/_setup_local.py

# Seed database skill into pmcp_skill table
python scripts/_seed_skill.py
```

## Tech Stack

**Backend**: Python 3.11.9 + FastAPI 0.115.0 + SQLAlchemy 2.0.35 + Alembic 1.13.2 + oracledb 2.4.1 + aiomysql 0.2.0 + asyncssh 2.17.0 (Server Skill SSH/SFTP)

**Frontend**: Vue 3.5.34 + Vite 8.0.12 + TypeScript 6.0.2 + Element Plus 2.8.1 + Pinia 2.2.2 + Axios 1.7.4 + vue-i18n 9.14.5 (Chinese/English bilingual)

**Databases**: PostgreSQL 16.4 (system), Oracle 11g / MySQL 5.6 (targets)

## Architecture (Simplified)

```
Claude Code ──stdio(env PLATFORM_MCP_API_KEY)──▶ MCP Server ──┐
           ╲                                        ├──▶ PostgreSQL (system DB, ORM)
            ╲                                       │    Oracle / MySQL (Database Skill targets)
Claude Code ──HTTP(header PLATFORM_MCP_API_KEY)──▶ ──┤    Linux SSH/SFTP (Server Skill targets)
                                                │
Browser ──HTTP(session cookie)──▶ FastAPI Web ──┘
```

## Directory Structure

```
Platform-MCP/
├── platform_mcp/                # Backend code
│   ├── api/                     # FastAPI routes (12 modules: auth/users/datasources/servers/api_keys/skills/groups/system_config/audit/crypto/profile/guide)
│   ├── auth/                    # Authentication & authorization + API Key
│   ├── datasource/              # Datasource management (DB Skill targets)
│   ├── server/                  # Server management (Linux SSH targets, Server Skill)
│   ├── skills/
│   │   ├── database/            # Database Skill (5 tools: SQL execution + risk control)
│   │   ├── server/              # Server Skill (6 tools: SSH/SFTP + risk control)
│   │   └── common/              # Shared risk types (risk_types + permission)
│   ├── mcp_server/              # MCP protocol + dual transport + context/audit
│   ├── audit/                   # Audit logs
│   ├── i18n/                    # Multilingual resource dictionary (zh-CN/en-US 1:1, V3.0 M1)
│   └── common/                  # Common components (database / crypto / response / runtime_config / etc.)
├── platform-mcp-frontend/       # Frontend code (Vue 3, 11 business pages incl. server/group management & system config, vue-i18n bilingual)
├── tests/                       # Backend tests (900 cases)
├── scripts/                     # Utility scripts
├── alembic/                     # Database migrations
├── documents/                   # Design documents
```

## Documentation Index

| Document | Description |
|------|------|
| `CLAUDE.md` | Claude Code working guide (project-wide principles, Chinese) |
| `documents/design/Python：# Platform-MCP 技术架构说明文档.md` | Technical architecture (authoritative source, Chinese) |
| `documents/design/Python：# Platform-MCP 代码规范.md` | Coding standards (Chinese) |
| `documents/design/Python：# Platform-MCP 部署规范.md` | Production deployment (Chinese) |
| `documents/design/Python：# Platform-MCP 测试规范文档.md` | Testing strategy (Chinese) |
| `CLAUDE.md` § 文档审核标准 | Documentation review rules (embedded in CLAUDE.md) |
| `documents/ui/Platform-MCP-portal.html` | UI prototype (single-file HTML) |

## Version Iteration

> **Baseline V1.0 = 2026-08-08**. Every subsequent production release (including hotfixes, iteration versions, and config-change rollouts) must append a row to this table — see `CLAUDE.md §部署原则 #10`.

| Version | Date | Type | Summary | Author |
|------|------|------|------|--------|
| V3.0-M3R | 2026-09-05 | Review fix | M3 user-acceptance feedback batch (4 rounds): **(1) Plaza column slimming + admin disable** — list no longer shows version/uploader/description (version trail and uploader kept internally); RM entry moved to the action column; admin disable added (`POST /plaza/{id}/disable`, 9th endpoint; disabled skills invisible to all roles on both Web+MCP ends, version archive & audit retained, restorable by re-sharing). **(2) Skill blacklist** — "type" column removed (personal block list has no type dimension); RM actions added (plaza item reads `/plaza/{id}/readme`, personal item reads latest `/skills/{id}/versions` archive). **(3) Skill management** — audit column removed; review feedback merged into the "Share Management" sheet review log (per-version verdict + bilingual archive report detail). **(4) README bilingual purity, 3 rounds** — split_bilingual splitter for "中文 / English" paired descriptions (function/tool descriptions & review reports split per language, internal slashes not mis-split); structure rework (H1 heading removed, description = the skill's real description body, "created via MCP, no source package" boilerplate removed, requirements dependency list, file-count stat, generated_by=template footer); built-in skill descriptions via the `skill.desc.*` bilingual dictionary (RESOURCES 24→26 keys; English Description pure English). **(5) Decorator-registered skills need no review** — quick start renders 3 steps without review for `register_method=decorator`; upload/form keep the 4-step review flow. **(6) MCP guide 500 fix** — `guide.py` `status==1` int literal vs varchar state machine → `ReviewStatus.ENABLED`. Existing version archives re-generated idempotently (fields nulled → startup backfill). Verification: pytest 1385 / mypy 0 (93 files) / vitest 163 / vue-tsc 0 / build passed | castle |
| V3.0-M3 | 2026-09-04 | Iteration | V3.0 M3 Skill plaza + search + role filtering: **(1) Skill plaza** — `pmcp_skill_plaza` public pool (migration 006, database/server-involving flags invisible to general users on both Web+MCP) + `api/plaza.py` 8 endpoints (list / semantic search / detail / bilingual README / copy-to-my / block / unblock / blacklist) + `plaza_visible_to_role` shared visibility for both entries + per-user blacklist dual-entry filtering. **(2) Semantic search** — fastembed BGE-M3 `EmbeddingStore` dual implementation (pgvector / JSONB + in-memory cosine fallback) + migration 007 (`embedding` JSONB column + conditional `embedding_vec` vector(1024), auto-degraded at runtime when restricted). **(3) MCP role filtering** — registry `ToolMeta.roles`, tools 11→29 filtered by role (admin 29 / developer 28 / general user 17), dual-entry tools review_skill / query_audit_logs / update_profile / change_password. **(4) Frontend plaza page** — PlazaPage (plaza/blacklist dual tabs, semantic-search similarity column, bilingual README dialog, copy/block/unblock) + all-role top navigation + general-user landing redirect to /plaza. Verification: pytest 1340 / mypy 0 (93 files) / vitest 156 / build passed | castle |
| V3.0-M2 | 2026-09-03 | Iteration | V3.0 M2 Skill lifecycle: migration 006 (`pmcp_skill_version` versioned bilingual archive [readme/report zh+en + audit_snapshot + generated_by trace, UNIQUE(skill_id,version) immutable], `pmcp_skill_blacklist`, `pmcp_skill` adds plaza_id/origin/share_status/review_comment); 8-state varchar state machine + transition validation + personal-library visibility filtering; registry genuinely consumes `pmcp_skill.status` to filter built-in skills (erratum 5 closed); reusable review service extraction (`platform_mcp/review/`, shared with phase-3 KB); MCP dual channel (create_skill_draft with automatic plaza similarity scan / update_my_skill / submit_skill_for_review / withdraw_review / resolve_share_iteration); Web upload chain versioned upgrade + bilingual audit report/README generation (template fallback with generated_by trace); SkillPage enhancements (README dialog, share/update/iteration sheet, admin review dialog); backend i18n dictionary 16→24 keys (8 status labels added with consumers). Verification: pytest / mypy / vitest / vue-tsc all green | castle |
| V3.0-M1 | 2026-09-03 | Iteration | V3.0 M1 i18n foundation + runtime config center: **(1) Chinese/English bilingual** — frontend-wide vue-i18n keying (15 files, 129 tests, localStorage `pmcp_locale`, default Chinese), backend resource dictionary RESOURCES (23 keys × zh-CN/en-US 1:1 mirror), all 11 MCP tool descriptions in both languages, personal `pmcp_user.locale` switch applied via login snapshot (`SessionInfo.locale/ttl_seconds`) after re-login without process restart. **(2) Runtime config center** — KNOWN_KEYS registry of 14 keys (value type / effect semantics relogin|immediate / sensitive flag / i18n description), 30s snapshot cache + background periodic refresh, immediate hot-switch of `log.level` (fixed latent UnboundLocalError from missing global declaration in logsetup), login read-point refactoring (`session.timeout_minutes` TTL + `sys.default_locale` default language), registry-driven upgrade of SystemConfigPage (row-id merge / configured-vs-default state / sensitive-key masking + `confirm_sensitive` second confirmation / custom keys coexisting) + sidebar menu enabled (erratum 4 closed). Verification: stage-1 all green (pytest 900, mypy 0/80, vue-tsc 0, vitest 129) | castle |
| V3.0-M0 | 2026-09-02 | Iteration | V3.0 foundation: unified group model (`pmcp_group` + 3 member tables, migration 005, head=005, existing rows backfilled via "same env + same name merge", 5 old group tables DROPped), group filtering pushed down to manager layer effective at both Web/MCP entries (fixes MCP-layer group filtering gap), third role general user (role seed `user`), `pmcp_user.locale` column, `pmcp_skill.status` varchar state machine, group management / system config menus enabled, GroupPage rewritten for unified groups, "owning group" column on 3 pages + admin row-level group assignment, MCP identity propagation (`McpContext.identity`) | castle |
| V2.1 | 2026-08-13 | Iteration | Phase-2 first batch (commit bd178b6): Skill source upload registration (.7z/.zip ≤50MB → extract → SKILL.md frontmatter parse → 14-rule compliance audit [filesystem/database/network/credentials/structure, 🔴block/🟡warn/🟢suggest] → sanitization of internal codenames/vendor names/intranet IP references → README template generation → `pmcp_skill` pending review + `pmcp_skill_audit_report` per-rule retention + review approve→ENABLED / reject→REJECTED), group management (group ×2 + member ×2 + user_group, 5 tables; admin CRUD+assign / dev read-only; merged into unified group model in migration 005), system config CRUD API (`/system-configs`, admin only), deprecated table cleanup (migration 002 DROPped 4 permission tables), frontend SkillPage rewrite + GroupPage + SystemConfigPage (routes registered, menu enablement pending) | castle |
| V1.1.6 | 2026-08-25 | Hotfix | BUG20260824090000 file-channel PL/SQL block execution anomalies: **(1) Leading comments/BOM broke block detection** — sqlparse merged leading comments into the block statement and read_text(utf-8) did not strip BOM, so the block-head regex failed to match → trailing end; wrongly stripped (PLS-00103, same error as the 08-24 internal report) / BOM even tore the block into 2 fragments at internal semicolons; fix: strip leading noise (BOM/whitespace/line comments/block comments) before block matching + splitter shields BOM + both read points use utf-8-sig. **(2) Comment-only statements wrongly entered splits** — trailing comments were once cut into independent UNKNOWN/HIGH statements (triggering the whole-batch confirm gate, and post-confirm execution always failed, failing the whole file); fix: filter comment-only statements at split end. **(3) Oracle timeout lacked server-side session termination** — thick threads are uncancelable; timeout merely abandoned the thread and the connection was closed under the executing thread's feet, the killed session kept executing on the DB side and dragged down the shared target DB (ORA-12170 persisted for tens of minutes after the kill); fix: conn.break_() OOB-interrupt of in-flight call + thread reclamation + normal connection close (server-side session termination) + timeout result carries source_session (sid/serial). Verification: stage-1 all green (pytest 821, mypy 0/76, vue-tsc 0, vitest 116) + post local-instance restart full 11-tool integrity and 4-form targeted live tests all passed (see documents/bug/BUG20260824090000) | castle |
| V1.1.5 | 2026-08-17 | Hotfix | BUG20260817220800 execute_command silent multi-statement truncation (introduced in V1.1.0, re-discovered on V1.1.4 release day): in the `echo $$; exec <cmd>` wrapper, POSIX `exec` replaces the shell with the first command, and commands after `;`/`&&`/`||` were all silently dropped (exit 0) — production evidence: `echo A; echo B; pwd; id` echoed only A. Fix: `exec bash -c {shlex.quote(command)}` carries the full command string; audit source_session PID capture semantics unchanged. Verification: stage-1 all green (pytest 801, mypy 0/76, vue-tsc 0, vitest 117) + production live test showed full multi-statement output + five-stage chained commands executed in order (see documents/bug/BUG20260817220800) | castle |
| V1.1.4 | 2026-08-17 | Hotfix | BUG20260814163941 resumable-transfer special project + BUG20260817123100 SQL multi-statement execution anomalies: **(1) Resumable transfer** — SFTP leg `_sftp_put/get_resumable` (r+b/ab resume-append + size integrity check + 3 auto retries, cleanup on both success and exhaustion); HTTP leg chunked upload `/transfer/chunk` + `/transfer/merge` (merge size check, on failure chunks kept for supplementary upload) + Range download 206 + truncated-upload check (bytes received ≠ Content-Length → 400 + cleanup); Windows workstation paths identified upfront (error message embeds two-way curl relay guidance, PLATFORM_MCP_API_KEY). **(2) SQL multi-statement** — text/file unified `split_statements` splitting (SQL*Plus `/` fragment filtering), low-risk multi-statements executed one by one (statement_count/results[]), HIGH/CRITICAL-containing batches rejected outright `MULTI_STMT_HIGH_RISK`, confirm_token bound to sql_hash sealing off reuse with swapped SQL + retry guidance, audit error_code passed through (CONFIRM_REQUIRED also honestly recorded as error). **(3) Production smoke gap fix** — on genuine uvicorn disconnect `request.stream()` raises ClientDisconnect (not OSError) escaping the 503 with partial files left uncleaned (pytest ASGITransport graceful-end flow cannot cover it); upload/upload_chunk changed to 400 + cleanup with http.disconnect regression cases. Verification: 11-tool production live tests + special project (100MB SFTP sha256 identical on both ends / 20MB chunk relay consistent end-to-end / Range 206 / truncated 400 zero residue) + stage-4 marked-row cleanup zero residue (see both BUG documents) | castle |
| V1.0.1 | 2026-08-09 | Hotfix | Audit-log failure-record completeness enhancement (two fine-grained fixes merged as same-day hotfix): **(1) error_code mandatory capture** — `call_log.py` PmcpMcpCallLog construction adds `error_code=error_code` (before fix, 0/5 error rows in mcp_call_log had codes); `auth.py` login fail adds `error_code="11001"`; `crypto.py` encrypt/verify fail adds `error_code="15001"`; `profile.py` change-password fail adds `error_code="11004"`. **(2) result_status enum unification** — 8 sites across 6 web-layer files `'fail'` → `'error'` (auth/crypto/profile/datasources/servers) + UI `statusLabel` defensively recognizes both fail/error → failure + `audit/models.py` column comment updated to `(success/error)`. **(3) Historical data backfill** — UPDATE fail→error 2 rows + NULL error_code backfilled 6 rows by error-message pattern matching (11001/12001/10001/15001); final state zero fail residue + 100% error_code completeness on error rows. Production verification: castle.zhang's 4 login-failure records all error/11001 ✓; castle.zhang MCP failure → audit_log + mcp_call_log both tables error_code=12001 ✓ | castle |
| V1.0 | 2026-08-08 | Baseline release | Phase 1 + Server Skill Phase-2 special project full launch: 11 MCP tools (database 5 + server 6), 15 system tables, 9 frontend pages, dual-transport MCP (stdio + streamable-http), API Key dual storage (hash + encrypted) | castle |

## Testing

```bash
# Backend (1340 cases, --ignore=tests/performance scope)
python -m pytest tests/ --ignore=tests/performance --cov=platform_mcp
mypy platform_mcp/    # Type checking (added in V1.0, 93 files 0 errors)

# Frontend (156 cases)
cd platform-mcp-frontend
npm run test
```

## Configuration

| File | Purpose | Source |
|---|---|---|
| `settings.yml` | Base config (database.url etc., required) | Copy from `settings.yml.example` |
| `settings-dev.yml` | dev environment overrides (included) | Tracked; adjust `oracle_instant_client_dir` as needed |
| `settings-prod.yml` | prod environment overrides | Copy from `settings-prod.yml.example` (prod only) |
| `crypto-secret.key` | AES key (32 raw bytes) | Auto-generated by `scripts/_setup_local.py` |
| `alembic.ini` | Alembic migration config | Tracked; DB URL placeholder, overridable via `PLATFORM_DB_URL` env var |

## License

This project is open-sourced under the **MIT License**; see [LICENSE](LICENSE).

### Third-Party Open Source Licenses

This project uses the following open-source components; each component is governed by its original license:

| Category | Component | License |
|---|---|---|
| Backend frameworks | FastAPI, Pydantic, SQLAlchemy, Alembic, Uvicorn, Gunicorn, loguru | MIT |
| Database drivers | oracledb | Apache 2.0 |
|  | aiomysql | MIT |
|  | psycopg2-binary | LGPL-3.0 |
| Cryptography | cryptography | Apache-2.0 OR BSD-3-Clause |
| HTTP client | httpx | BSD-3-Clause |
| MCP protocol | mcp SDK | MIT |
| Config/tooling | PyYAML, tenacity, sqlparse | MIT / BSD / Apache-2.0 |
| Frontend frameworks | Vue, Vite, Pinia, Vue Router, Axios | MIT |
| i18n | vue-i18n | MIT |
| Type system | TypeScript | Apache-2.0 |
| UI component library | Element Plus | MIT |

### Commercial Database License Notice

Platform-MCP supports connecting to Oracle 11g and MySQL 5.6 as **target databases**. Users must obtain the appropriate database licenses and authorizations themselves; this project does not include or provide any commercial database license. The thick mode of the Oracle driver (oracledb) depends on Oracle Instant Client, which must be downloaded separately and is subject to Oracle's license agreement.
