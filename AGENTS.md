# FIINOPS architecture requirements

Read and follow [docs/CORE_BOUNDARY_REQUIREMENTS.md](docs/CORE_BOUNDARY_REQUIREMENTS.md)
when changing this repository. This is the user-requested boundary contract.

- Business rules, calculations, authorization and durable business scenarios belong
  in `app/application`, `app/services` and `app/schemas` using canonical `users.id`.
- Core code must not import `app/handlers`, `app/adapters`, `app/ui`, `app/max_bot`,
  `app/web`, `app/state`, aiogram, FastAPI or Starlette, even inside functions.
- Frontends authenticate platform events, resolve identity, decode commands and
  render/send results. Do not add SQL or obtain a DB pool in a frontend. Bootstrap
  may call `init_db` / `close_db`; identity integrations accept plain profile/proof
  data as specified by the contract, never messenger SDK objects.
- Financial input must use the canonical pending-input service. The financial write
  and consumption of the current revision must commit together. Do not implement
  separate Telegram/MAX workflows or put new business state in `app/state`.
- Platform compatibility signatures belong only in `app/adapters`; the core must
  never call those adapters. New interfaces call the existing canonical commands.
- Run `tests/test_core_boundaries.py` and checks appropriate to the change. Financial
  integrations require disposable PostgreSQL DBs and `RUN_DATABASE_TESTS=1`; skipped
  integration tests are not evidence of financial correctness.
- Schema updates preserve documents and financial history. Document coordinated
  adapter upgrades where old writers are incompatible; never reset production data.
