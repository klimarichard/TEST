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
User ──< Car               (owner)
User ──< CarShare >── Car  (shared access)
User ──< Expense
User ──< DismissedWarning  (permanently dismissed expiry banners)
Car  ──< Expense
Expense ──1 FuelDetail | RepairDetail | TollDetail | InsuranceDetail | GadgetDetail | InspectionDetail
UserCarHidden              (per-user car visibility toggle)
```

**User** fields: `username`, `email`, `password_hash`, `is_admin`, `theme` (`'light'`/`'dark'`), `pending_username` + `pending_username_at` (username change request workflow).

**Car** fields: `name`, `make`, `model_name`, `year`, `license_plate`, `owner_id`, `hidden_from_shared` (owner hides from all shared users globally).

**UserCarHidden**: per-user record to hide a car from their own dashboard/list without affecting others.

**Expense**: `car_id`, `user_id`, `date`, `amount`, `currency`, `amount_czk`, `expense_type`, `notes`. All monetary amounts stored twice: `amount` + `currency` (original) and `amount_czk` (converted, used for all charts/totals).

**DismissedWarning**: per-user, per-expense record for permanently dismissed expiry banners (session-based dismissal also supported via Flask session).

**Detail models** (each has an `expense_id` FK):
- `FuelDetail`: `liters`, `price_per_liter`, `odometer`, `station_location`, `transaction_time`
- `RepairDetail`: `description`
- `TollDetail`: `route`, `toll_type`, `expiration_date`, `notify_before_expiry`, `notify_days_before`, `notification_sent`
- `InsuranceDetail`: `insurance_type`, `provider`, `expiration_date`, `notify_before_expiry`, `notify_days_before`, `notification_sent`
- `GadgetDetail`: `gadget_type`
- `InspectionDetail`: `workshop`, `odometer`, `expiration_date`, `notify_before_expiry`, `notify_days_before`, `notification_sent`

`TollDetail`, `InsuranceDetail`, and `InspectionDetail` all have `is_expiring_soon` (within 30 days) and `is_expired` properties.

### Authorization rules

- Car **owner**: full access — edit/delete car, manage shares, edit/delete any expense on that car
- **Shared user**: can add new expenses and edit/delete only their own expenses on that car
- **Admin**: can create/edit/delete users only (not a superuser for cars/expenses); redirected away from car/expense routes
- `admin_required` decorator enforces admin-only routes; `expense.can_edit(user)` and `car.is_accessible_by(user)` enforce object-level access

### Car visibility

- `User.get_accessible_cars()` — all cars the user owns or is shared on
- `User.get_visible_cars()` — accessible cars minus: ones the user personally hidden (`UserCarHidden`) or the owner hid globally (`Car.hidden_from_shared`)
- `User.get_hidden_cars()` — hidden cars with `can_restore` flag (only personally hidden ones can be unhidden by the user)
- Dashboard stats use all accessible cars; the car grid uses only visible cars

### Exchange rates

Live rates fetched from `api.frankfurter.app`, cached in module-level `_rate_cache` dict for 1 hour. `/api/exchange-rate?from=EUR` exposes this to the frontend for the live CZK conversion hint on the expense form.

Supported currencies: `CZK, EUR, USD, GBP, CHF, PLN, HUF, NOK, SEK, DKK`

### Expiry notifications

`send_expiry_notifications()` runs via APScheduler daily at 08:00 (background thread, skipped in Werkzeug reloader child process). It checks `TollDetail`, `InsuranceDetail`, and `InspectionDetail` rows where `notify_before_expiry=True`, `notification_sent=False`, and `expiration_date - today == notify_days_before`. Sends email via Flask-Mail and marks `notification_sent=True`.

Mail configured via env vars: `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`.

### Constants

- `EXPENSE_TYPES = ['fuel', 'repair', 'toll', 'insurance', 'gadget', 'inspection']`
- `POLICY_TYPES = ['toll', 'insurance', 'inspection']` — types that have expiry/policy semantics
- `TOLL_TYPES` — dropdown choices for toll type
- `INSURANCE_TYPES` — dropdown choices for insurance type
- `TYPE_LABELS`, `TYPE_ICONS`, `TYPE_COLORS` — display metadata per expense type

### Templates

All templates extend `templates/base.html`. The `inject_globals()` context processor injects `now`, `TYPE_COLORS`, `TYPE_LABELS`, `TYPE_ICONS`, `EXPENSE_TYPES`, and `pending_username_count` (pending username change requests, admin only) into every template.

Use the `| czk` Jinja2 filter to format amounts (outputs e.g. `1 234 Kč` with narrow no-break space as thousands separator).

**Template structure:**
```
templates/
  base.html
  login.html          — login form; redirects to setup if no users exist
  setup.html          — first-run admin account creation wizard
  account.html        — email/password/username change; theme toggle (POST /account/theme → 204)
  active.html         — active policies view (tolls, insurance, inspections) for regular users and admin
  dashboard.html      — car grid + summary stats + monthly bar + type doughnut
  admin/
    index.html        — user list + pending username change requests
    user_form.html    — create/edit user form
    user_detail.html  — user profile with owned/shared cars and expense list
    overview.html     — filterable all-expenses view with expense detail modal
  cars/
    list.html         — visible cars + hidden cars restore section
    form.html         — create/edit car
    detail.html       — expense list + 3 charts + toll/insurance/inspection warnings (dismissible)
    share.html        — manage shared users
  expenses/
    form.html         — single form for all 6 expense types; JS switchType() shows/hides sections
    list.html         — filterable expense list with totals
  errors/
    403.html, 404.html
```

The expense form (`templates/expenses/form.html`) handles all six expense types — JavaScript shows/hides the relevant field section via `switchType(type)`. For fuel, `price_per_liter` is computed client-side from `amount ÷ liters`; the server recomputes it as a fallback in `_apply_type_detail()`. Past station locations are passed as `past_stations` for autocomplete. The form also supports a **renew flow**: `?renewing=<expense_id>` shows the original expense as context, and `pf_*` query params prefill field values.

Charts use Chart.js (CDN). Car detail page has three charts: stacked monthly bar, type doughnut, and fuel efficiency line (L/100 km, calculated between consecutive odometer readings). Dashboard has monthly bar and type doughnut.

**Expiry warning banners** on car detail can be dismissed per-session (`POST /warnings/<id>/dismiss`) or permanently (`POST /warnings/<id>/dismiss-permanent`, stored in `DismissedWarning`). Superseded warnings (e.g. a newer non-expired inspection exists) are filtered out automatically via `_filter_superseded_*` helpers.

### Key helpers

- `_parse_expense_form(form)` — validates and parses common expense fields, returns `(data_dict, error_str)`
- `_apply_type_detail(expense, form)` — upserts the type-specific detail row
- `_get_past_stations(user)` — returns distinct fuel station names across all accessible cars (for autocomplete)
- `_export_xlsx(expenses, include_user, filename)` — builds and streams an Excel file via openpyxl; used by `/expenses/export` and `/admin/overview/export`
- `_build_policy_entries(expenses)` — groups `POLICY_TYPES` expenses into `{type: {active: [], expired: []}}` for the active policies view
- `_filter_superseded_tolls/insurance/inspections(warnings, all_expenses)` — removes warnings superseded by a newer non-expired entry of the same type on the same car

### Routes summary

| Method | URL | Function | Notes |
|--------|-----|----------|-------|
| GET | `/` | `index` | Redirects to dashboard or login |
| GET/POST | `/setup` | `setup` | First-run only |
| GET/POST | `/login` | `login` | |
| GET | `/logout` | `logout` | |
| GET/POST | `/account` | `account` | Email, password, username change request |
| POST | `/account/theme` | `account_theme` | Returns 204 |
| GET | `/dashboard` | `dashboard` | Admin → redirects to admin_overview |
| GET | `/expenses` | `expense_list` | Filterable, car/type filters |
| GET | `/expenses/export` | `expense_export` | XLSX download |
| GET | `/cars` | `cars_list` | |
| GET/POST | `/cars/new` | `car_new` | |
| GET | `/cars/<id>` | `car_detail` | Charts, warnings, efficiency filter |
| GET/POST | `/cars/<id>/edit` | `car_edit` | |
| POST | `/cars/<id>/hide` | `car_hide` | Optional `hide_globally` for owners |
| POST | `/cars/<id>/unhide` | `car_unhide` | |
| POST | `/cars/<id>/delete` | `car_delete` | |
| GET/POST | `/cars/<id>/share` | `car_share` | add/remove shared users |
| GET/POST | `/cars/<id>/expenses/new` | `expense_new` | |
| GET/POST | `/expenses/<id>/edit` | `expense_edit` | |
| POST | `/expenses/<id>/delete` | `expense_delete` | |
| GET | `/admin` | `admin_index` | User list + pending requests |
| GET/POST | `/admin/users/new` | `admin_user_new` | |
| GET | `/admin/users/<id>` | `admin_user_detail` | |
| GET/POST | `/admin/users/<id>/edit` | `admin_user_edit` | |
| POST | `/admin/users/<id>/delete` | `admin_user_delete` | |
| POST | `/admin/requests/<id>/approve` | `admin_approve_username` | |
| POST | `/admin/requests/<id>/deny` | `admin_deny_username` | |
| GET | `/active` | `active_policies` | Active/expired tolls, insurance, inspections (user view) |
| GET | `/admin/active` | `admin_active` | Active/expired policies across all users (admin view) |
| POST | `/warnings/<id>/dismiss` | `dismiss_warning` | Session-dismiss an expiry warning banner |
| POST | `/warnings/<id>/dismiss-permanent` | `dismiss_warning_permanent` | Permanently dismiss a warning (stored in DB) |
| GET | `/admin/overview` | `admin_overview` | All expenses, filterable by user/car/type |
| GET | `/admin/overview/export` | `admin_overview_export` | XLSX with user column |
| GET | `/api/exchange-rate` | `api_exchange_rate` | `?from=EUR` → `{rate, from, to}` |

## Deployment

Configured for Railway via `Procfile` and `railway.toml`. Set `SECRET_KEY` env var in Railway before deploying. The app uses SQLite — if migrating to PostgreSQL, set `DATABASE_URL` env var (Railway provides `postgres://` which is auto-rewritten to `postgresql://`).
