# Architecture / معماری

The bot UI is split into participant and admin routers under `app/bot/routers`. Admins get a separate dashboard from `/start`, with an explicit switch to participant mode. Admin callback actions and multi-step form messages recheck the configured admin IDs. Keyboards are kept separately in `app/bot/keyboards.py`; the admin router handles people search, pagination, soft deactivation, survey creation, reports, and exports. Participant voting remains in its own router. SQLAlchemy models and the async session factory own persistence. The export module translates stored results into an XLSX workbook.

Person and survey creation use aiogram FSM state, which currently uses the dispatcher's default in-memory storage. An interrupted form is lost if the bot restarts; durable drafts and database migrations are a follow-up before long-lived production upgrades.

The vote uniqueness key is `(survey_id, person_id, user_id)`, allowing a person to be rated once by a voter in each survey while allowing new votes in other surveys. `SurveyPerson` scopes candidates to a survey. `survey_status` evaluates persisted start/end instants against UTC-aware current time; ISO inputs with offsets are recommended. Anonymous is a reporting policy: voter identity stays in storage for uniqueness but is omitted from XLSX output.

This deliberately avoids a separate web app and complex dependency injection. SQLite supports simple single-process deployments; PostgreSQL is available through the async driver for larger deployments. Schema migration tooling and a richer admin conversation state machine should be added before long-lived production upgrades.
