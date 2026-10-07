# Persian Telegram Evaluation Bot

A Persian-language Telegram bot for collecting person-by-person ratings in independent, time-bounded surveys. Python 3.11+, aiogram 3, SQLAlchemy async, SQLite by default (PostgreSQL supported through `DATABASE_URL`), and openpyxl reports.

## Features

- Persian menus and an inline survey → person → score voting flow.
- Survey-specific schedules and 1–5 default scoring, comments, anonymity, and vote editing settings.
- Application checks plus a database unique constraint preventing a second vote for the same user/person/survey.
- Admin ID allowlist, basic person and survey creation commands, aggregate statistics, and XLSX exports that omit voter identity for anonymous surveys.
- Async database models and Docker packaging.

## Architecture

`app/bot` handles Telegram interactions, `app/services` implements business rules, `app/models.py` defines persistence, `app/database.py` owns async database setup, and `app/exports` creates reports. SQLite keeps local deployment simple; switch to PostgreSQL with an async SQLAlchemy URL. See [docs/architecture.md](docs/architecture.md).

## Requirements and installation

Python 3.11 or newer is required. From the repository root:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
Copy-Item .env.example .env   # PowerShell; on Linux/macOS: cp .env.example .env
```

Edit `.env`:

| Variable | Required | Purpose |
|---|---:|---|
| `BOT_TOKEN` | yes | Token from BotFather |
| `ADMIN_USER_IDS` | yes for admin commands | Comma-separated Telegram numeric IDs |
| `DATABASE_URL` | no | Defaults to local SQLite; PostgreSQL example: `postgresql+asyncpg://user:pass@host/db` |
| `TIMEZONE` | no | Default documentation timezone (`Asia/Tehran`) |
| `LOG_LEVEL` | no | Python logging level, default `INFO` |

Create a bot with [BotFather](https://t.me/BotFather), put the token in `.env`, and get your Telegram numeric user ID from a trusted ID bot. Put that ID in `ADMIN_USER_IDS`. Do not commit `.env`.

## Run

```bash
python -m app.main
```

The schema is created on startup. No migration framework is included yet; back up the database before upgrading a populated deployment.

## Admin commands

Use `/start` first, then open **⚙️ پنل مدیریت**. Commands are restricted to IDs in `ADMIN_USER_IDS`:

```text
/addperson P-001|علی|رضایی
/addsurvey ارزیابی مهر|2026-10-08T09:00:00+03:30|2026-10-09T17:00:00+03:30|1,2
/reports
/export 1
```

Dates must be ISO-8601 and include a UTC offset. Survey people are database person IDs, shown after insertion in the database. The implementation currently provides create and report operations; edit/delete/toggle flows, full user/admin management, destructive-action confirmations, and settings UI are future work.

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

For SQLite, stop the bot and copy the database file. Restore by replacing it while the bot is stopped. For PostgreSQL, use `pg_dump`/`pg_restore`. Keep backups encrypted and access-controlled.

## Security and limitations

Secrets are environment variables; `.env`, databases, logs, and generated reports are ignored by Git. Vote uniqueness is enforced in SQL. Admin commands check the configured Telegram ID allowlist, and report callback access is checked again. Anonymous exports omit voter identifiers, while the database retains internal user IDs for duplicate prevention. Configure strong host permissions and HTTPS/secure network access to PostgreSQL. The delivered scope is a functional voting/report core, not every requested CRUD/admin lifecycle: those remaining items are listed above rather than implied complete.

## Troubleshooting

- “BOT_TOKEN is required”: copy `.env.example` to `.env` and configure it.
- Bot does not respond: check token, internet access, and that another polling process is not using the bot.
- Admin menu missing: confirm your numeric Telegram ID in `ADMIN_USER_IDS` and send `/start` again.
- SQLite write errors: ensure the database directory is writable and only one bot process uses the SQLite file.
