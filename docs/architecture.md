# Architecture / معماری

The project uses a small layered design. Telegram handlers parse updates and render Persian responses. Services enforce voting rules independently of Telegram. SQLAlchemy models and the async session factory own persistence. The export module translates stored results into an XLSX workbook.

The vote uniqueness key is `(survey_id, person_id, user_id)`, allowing a person to be rated once by a voter in each survey while allowing new votes in other surveys. `SurveyPerson` scopes candidates to a survey. `survey_status` evaluates persisted start/end instants against UTC-aware current time; ISO inputs with offsets are recommended. Anonymous is a reporting policy: voter identity stays in storage for uniqueness but is omitted from XLSX output.

This deliberately avoids a separate web app and complex dependency injection. SQLite supports simple single-process deployments; PostgreSQL is available through the async driver for larger deployments. Schema migration tooling and a richer admin conversation state machine should be added before long-lived production upgrades.
