# Persian Telegram Evaluation Bot

A Persian-language bot for collecting person-by-person ratings in independent, time-bounded surveys. Run the same code on Telegram or Bale by setting `BOT_PLATFORM`. Python 3.11+, aiogram 3, SQLAlchemy async, SQLite by default (PostgreSQL supported through `DATABASE_URL`), and openpyxl reports.

## Features

- Persian menus and an inline survey → person → score voting flow.
- Survey-specific schedules and 1–5 default scoring, comments, anonymity, and vote editing settings.
- Application checks plus a database unique constraint preventing a second vote for the same user/person/survey.
- Admin ID allowlist, basic person and survey creation commands, aggregate statistics, and XLSX exports that omit voter identity for anonymous surveys.
- Async database models and Docker packaging.
- One codebase and database schema for Telegram and Bale; platform-scoped user identities.
- CSV/XLSX bulk people import with a validation preview and explicit confirmation.
- Survey progress and anonymous aggregate counts in admin reports and Excel.

## Architecture

`app/bot` handles Telegram interactions, `app/services` implements business rules, `app/models.py` defines persistence, `app/database.py` owns async database setup, and `app/exports` creates reports. SQLite keeps local deployment simple; switch to PostgreSQL with an async SQLAlchemy URL. See [docs/architecture.md](docs/architecture.md).

## Requirements and installation

Python 3.11 through 3.14 is supported. Use a fresh virtual environment after changing Python versions. From the repository root:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
Copy-Item .env.example .env   # PowerShell; on Linux/macOS: cp .env.example .env
```

SQLAlchemy's `asyncio` extra is included so the required `greenlet` dependency is installed for async database connections.

Edit the project-root `.env` file and set `BOT_TOKEN` to the token issued by your chosen platform:

| Variable | Required | Purpose |
|---|---:|---|
| `BOT_TOKEN` | yes | Token from BotFather or Bale's پدرِ ربات |
| `BOT_PLATFORM` | no | `telegram` (default) or `bale` |
| `ADMIN_USER_IDS` | yes for admin commands | Comma-separated numeric IDs on the selected platform |
| `DATABASE_URL` | no | Defaults to local SQLite; PostgreSQL example: `postgresql+psycopg://user:pass@host/db` |
| `TIMEZONE` | no | Default documentation timezone (`Asia/Tehran`) |
| `LOG_LEVEL` | no | Python logging level, default `INFO` |

Create a bot with [Telegram BotFather](https://t.me/BotFather) or Bale's [پدرِ ربات](https://ble.ir/botfather). Set `BOT_PLATFORM=telegram` or `BOT_PLATFORM=bale`, then put the matching token in `BOT_TOKEN`. `ADMIN_USER_IDS` must contain numeric user IDs from the selected platform. Do not commit `.env`.

Bale's API closely follows Telegram's Bot API. For Bale, aiogram calls `https://tapi.bale.ai`; handlers and business logic remain the same. Run a separate process with the Bale token/config when switching platforms. Both platforms can use the same database; user identity is keyed by platform and numeric ID.

## Run

```bash
python -m app.main
```

Alembic migrations run on startup. The initial baseline creates missing tables and adopts the previous Telegram user-ID schema. For an existing database, stop the bot and make a verified backup before the first startup on this version; test the migration against a restored copy first. The baseline cannot be downgraded; restore the verified backup to roll back.

## Admin commands

Use `/start` first, then open **⚙️ پنل مدیریت**. Initial admin IDs in `ADMIN_USER_IDS` are bootstrapped as **Owner**. Owners can add new administrators, toggle roles between Owner and Admin, and remove administrator access (removing or demoting the last owner is strictly prevented). Sensitive actions (survey cancellation/creation/editing, person management, bulk import, and admin role changes) are recorded in **📜 وقایع سیستم** while preserving voter anonymity. Commands and callbacks check role authorization:

For bulk import, open **👥 مدیریت افراد** → **ورود گروهی از فایل** and send a CSV or XLSX with headers `شناسه داخلی`, `نام`, `نام خانوادگی`, and optional `توضیح`. Files are limited to 5 MB and 1,000 data rows. Review invalid rows before confirming; valid rows are committed together in one transaction.

```text
/addperson P-001|علی|رضایی
/addsurvey ارزیابی مهر|2026-10-08T09:00:00+03:30|2026-10-09T17:00:00+03:30|1,2
/reports
/export 1
```

Dates can be provided in Gregorian format (e.g., `2026-10-08 09:00` or ISO-8601) or Persian Solar / Shamsi format (e.g., `1405/07/16 09:00` with English or Persian numerals); timestamps without an offset use `TIMEZONE` (default Asia/Tehran). Survey people are database person IDs. Scheduled surveys without votes can be edited from the admin detail view. Scheduled or active surveys can be cancelled after a separate confirmation; existing votes and reports are retained.

## Tests, lint, and operational checks

```bash
# Run automated tests and linting:
python -m pytest
python -m ruff check app tests

# Run self-check for database connection and Alembic migrations:
python -m app.main --check
```

## Docker

Create `.env` based on `.env.example`, then run:

```bash
docker compose up --build -d
```

- The `Dockerfile` includes the `/data` directory, migration files, and an automated container `HEALTHCHECK`.
- The compose file mounts `./data` on the host to `/data` in the container. For persistent SQLite storage in the container, set `DATABASE_URL=sqlite+aiosqlite:////data/survey_bot.db` in `.env`.
- For multi-instance deployments, configure PostgreSQL (`DATABASE_URL=postgresql+psycopg://user:password@host:5432/dbname`).

## Excel reports

An administrator runs `/export <survey-id>`. The XLSX contains summary, individual score, and progress sheets. Anonymous surveys exclude voter identity from the workbook. Keep report files private.

## Backup and restore

- **SQLite Backup:** Stop the bot (`docker compose down` or stop process) and copy the database file (`survey_bot.db`) to a secure location.
- **SQLite Restore:** While the bot is stopped, replace the database file with your verified backup copy, run `python -m app.main --check` to verify database health, and restart the bot.
- **PostgreSQL Backup/Restore:** Use standard `pg_dump` and `pg_restore` utilities.
- **Database Migrations:** The bot automatically runs `alembic upgrade head` on startup. Always test backups on a staging copy before deploying updates to production; if rollback is required, restore your verified backup.

## Security and limitations

Secrets are environment variables; `.env`, databases, logs, and generated reports are ignored by Git. Vote uniqueness is enforced in SQL. Admin commands check the configured Telegram ID allowlist, and report callback access is checked again. Anonymous exports omit voter identifiers, while the database retains internal user IDs for duplicate prevention. Configure strong host permissions and HTTPS/secure network access to PostgreSQL. The delivered scope is a functional voting/report core, not every requested CRUD/admin lifecycle: those remaining items are listed above rather than implied complete.

## Troubleshooting

- “BOT_TOKEN is required”: copy `.env.example` to `.env` and configure it.
- Bot does not respond: check token, internet access, and that another polling process is not using the bot.
- Admin menu missing: confirm your numeric Telegram ID in `ADMIN_USER_IDS` and send `/start` again.
- SQLite write errors: ensure the database directory is writable and only one bot process uses the SQLite file.
