# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
pip install -r requirements.txt
python3 -m flask run --port 5001 --debug   # --debug enables auto-reload for code and templates
```

Apply database migrations before first run (also creates the DB if it doesn't exist):
```bash
python3 -m flask db upgrade
```

To create the first admin user:
```bash
python3 -m flask create-admin USERNAME EMAIL PASSWORD
```

### Schema changes workflow

When you add or change a model, generate a migration and apply it:
```bash
python3 -m flask db migrate -m "describe the change"
python3 -m flask db upgrade
```

Commit the generated file in `migrations/versions/` alongside the code change. Railway runs `flask db upgrade` automatically on every deploy (see `Procfile`).

Use `python3 -m flask` instead of `flask` — the `flask` binary is not on PATH.

## Git workflow

- **Always create a new branch** before making changes (`git checkout -b <branch-name>`)
- **Commit and push** the branch when done
- **Never merge** into main without explicit instruction from the user

## Architecture

Everything lives in `app.py` — models, routes, helpers, CLI commands, and DB bootstrap. There are no blueprints.

### Data model

```
User ──< Car          (owner)
User ──< CarShare >── Car   (shared access)
User ──< Expense
Car  ──< Expense
Expense ──1 FuelDetail | RepairDetail | TollDetail | InsuranceDetail | GadgetDetail
```

Each `Expense` row has a base `expense_type` field and exactly one type-specific detail child row. All monetary amounts are stored twice: `amount` + `currency` (original) and `amount_czk` (converted, used for all charts and totals).

### Authorization rules

- Car **owner**: full access — edit/delete car, manage shares, edit/delete any expense on that car
- **Shared user**: can add new expenses and edit/delete only their own expenses on that car
- **Admin**: can create/edit/delete users only (not a superuser for cars/expenses)

### Exchange rates

Live rates are fetched from `api.frankfurter.app` and cached in the module-level `_rate_cache` dict for 1 hour. The `/api/exchange-rate?from=EUR` endpoint exposes this to the frontend for the live CZK conversion hint on the expense form.

### Templates

All templates extend `templates/base.html`. The `inject_globals()` context processor injects `now`, `TYPE_COLORS`, `TYPE_LABELS`, `TYPE_ICONS`, and `EXPENSE_TYPES` into every template. Use the `| czk` Jinja2 filter to format amounts (outputs e.g. `1 234 Kč` with narrow no-break space as thousands separator).

The expense form (`templates/expenses/form.html`) is a single page that handles all five expense types — JavaScript shows/hides the relevant field section via `switchType(type)`. For fuel, `price_per_liter` is computed client-side from `amount ÷ liters`; the server recomputes it as a fallback in `_apply_type_detail()`.

Charts use Chart.js (CDN). Car detail page has three charts: stacked monthly bar, type doughnut, and fuel efficiency line. Dashboard has monthly bar and type doughnut.

## Deployment

Configured for Railway via `Procfile` and `railway.toml`. Set a `SECRET_KEY` environment variable in Railway before deploying. The app uses SQLite — if migrating to PostgreSQL, set `DATABASE_URL` env var.
