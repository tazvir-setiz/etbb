# Persian Telegram Evaluation Bot

A Persian-language bot for collecting person-by-person ratings in independent, time-bounded surveys. Run the same code on Telegram or Bale by setting `BOT_PLATFORM`. Python 3.11+, aiogram 3, SQLAlchemy async, SQLite by default (PostgreSQL supported through `DATABASE_URL`), and openpyxl reports.

## Features

- Persian menus and an inline survey → person → score voting flow.
- Survey-specific schedules and 1–5 default scoring, comments, anonymity, and vote editing settings.
- Application checks plus a database unique constraint preventing a second vote for the same user/person/survey.
- Admin ID allowlist, basic person and survey creation commands, aggregate statistics, and XLSX exports that omit voter identity for anonymous surveys.
- Async database models and Docker packaging.
- One codebase and database schema for Telegram and Bale; platform-scoped user identities.

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

Use `/start` first, then open **⚙️ پنل مدیریت**. Commands are restricted to IDs in `ADMIN_USER_IDS`:

```text
/addperson P-001|علی|رضایی
/addsurvey ارزیابی مهر|2026-10-08T09:00:00+03:30|2026-10-09T17:00:00+03:30|1,2
/reports
/export 1
```

Dates must be ISO-8601; timestamps without an offset use `TIMEZONE`. Survey people are database person IDs. Scheduled surveys without votes can be edited from the admin detail view. Scheduled or active surveys can be cancelled after a separate confirmation; existing votes and reports are retained.

## Tests and lint

```bash
python -m pytest
python -m ruff check app tests
```

## Docker

Create `.env` first, then:

```bash
docker compose up --build -d
```

The compose file mounts `./data`, while the default database URL writes to the container working directory; for persistent SQLite storage set `DATABASE_URL=sqlite+aiosqlite:////data/survey_bot.db` in `.env`. Use PostgreSQL for multi-instance deployments.

## Excel reports

An administrator runs `/export <survey-id>`. The XLSX contains summary and individual score sheets. Anonymous surveys exclude voter name and Telegram ID from the workbook. Keep report files private; Telegram delivery is restricted to configured administrators.

## Backup and restore

For SQLite, stop the bot and copy the database file. Restore by replacing it while the bot is stopped. For PostgreSQL, use `pg_dump`/`pg_restore`. Keep backups encrypted and access-controlled. Startup runs `alembic upgrade head`; test upgrades against a restored copy before using an existing production database. Do not downgrade the initial baseline; restore a verified backup to roll back.

## Security and limitations

Secrets are environment variables; `.env`, databases, logs, and generated reports are ignored by Git. Vote uniqueness is enforced in SQL. Admin commands check the configured Telegram ID allowlist, and report callback access is checked again. Anonymous exports omit voter identifiers, while the database retains internal user IDs for duplicate prevention. Configure strong host permissions and HTTPS/secure network access to PostgreSQL. The delivered scope is a functional voting/report core, not every requested CRUD/admin lifecycle: those remaining items are listed above rather than implied complete.

## Troubleshooting

- “BOT_TOKEN is required”: copy `.env.example` to `.env` and configure it.
- Bot does not respond: check token, internet access, and that another polling process is not using the bot.
- Admin menu missing: confirm your numeric Telegram ID in `ADMIN_USER_IDS` and send `/start` again.
- SQLite write errors: ensure the database directory is writable and only one bot process uses the SQLite file.
