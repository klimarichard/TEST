# CarTracker

A personal car expense tracking web app built with Flask. Track fuel, repairs, tolls, insurance, and gadgets across multiple cars — with multi-user sharing, live currency conversion, charts, and email expiry reminders.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![Flask](https://img.shields.io/badge/Flask-3.0-green)
![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-purple)

---

## Features

### Expense Tracking
- **5 expense types:** Fuel, Repair, Toll, Insurance, Gadget
- **Multi-currency support** with live exchange rates (via [Frankfurter API](https://www.frankfurter.app/)) and real-time CZK conversion hint while filling in the form
- All amounts stored in original currency + converted CZK for consistent charts and totals
- **Fuel-specific fields:** liters, odometer, price/liter (auto-calculated), fuel station location, transaction time
- **Toll & Insurance expiry dates** with optional email reminders (configurable 1–30 days in advance)
- Notes field on every expense

### Fuel Station Autocomplete
Start typing a fuel station name and the app suggests stations from your previous entries across all your cars.

### Charts & Analytics (per car)
- Monthly spending by category (stacked bar)
- Expense breakdown by type (doughnut)
- **Fuel efficiency** (L/100 km) over time — filterable by date range, with overall average (total litres ÷ total km)

### Dashboard
- Spending totals, expense count, and this month's spend at a glance
- Quick **Add Expense** button — goes directly to the form if you have one active car, or shows a car picker modal if you have several
- Monthly spending chart and category breakdown

### Multi-User & Car Sharing
- Users can **own** cars (full control) or be **shared** on cars (add own expenses, edit/delete only their own)
- Car owners can share/unshare with any registered user
- Per-user car visibility: mark any car as **not used** to hide it from your own dashboard without affecting other users
- Owners can additionally hide a car from **all shared users** at once

### Admin
- Separate admin role for user management (create, edit, delete users)
- Admin overview of all expenses across all users and cars, with filtering by user, car, and expense type
- Admins cannot own cars or expenses — strictly a management role

### Filters & Export
- Filter expenses by car and/or expense type on both the user expense list and the admin overview
- **Export to Excel** (.xlsx) — respects active filters so you export exactly what you see
- Expiring/expired toll and insurance highlighted with warning banners on the car detail page

### UX
- **Dark mode** — follows your OS preference on login/setup; toggleable per-user when logged in (preference saved in DB)
- Fully responsive — works on mobile
- Light/dark-aware table headers, badges, and charts

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, Flask 3 |
| Database | SQLite (dev) / PostgreSQL (production) |
| ORM & migrations | Flask-SQLAlchemy, Flask-Migrate (Alembic) |
| Auth | Flask-Login, Werkzeug password hashing |
| Forms & CSRF | Flask-WTF |
| Email | Flask-Mail (generic SMTP) |
| Scheduling | APScheduler (daily expiry notification job) |
| Frontend | Bootstrap 5.3, Bootstrap Icons, Chart.js 4 |
| Export | openpyxl |
| Exchange rates | [Frankfurter API](https://www.frankfurter.app/) (1-hour cache) |
| Deployment | Railway (Procfile + railway.toml) |

---

## Getting Started (local)

### Prerequisites
- Python 3.10+
- A virtual environment (recommended)

### Install

```bash
git clone https://github.com/klimarichard/TEST.git
cd TEST
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
```

### Run

```bash
python -m flask db upgrade          # create / migrate the database
python -m flask run --port 5001 --debug
```

Open [http://127.0.0.1:5001](http://127.0.0.1:5001).

On first run, if no admin exists, you will be prompted to create one through the setup page, or use the CLI:

```bash
python -m flask create-admin USERNAME EMAIL PASSWORD
```

---

## Deployment (Railway)

1. Create a new Railway project and link this repository
2. Add a **PostgreSQL** database service and link it to the web service — Railway injects `DATABASE_URL` automatically
3. Set the following environment variables on the web service:

| Variable | Description |
|---|---|
| `SECRET_KEY` | A long random secret string |
| `MAIL_SERVER` | SMTP server hostname |
| `MAIL_PORT` | SMTP port (typically `587`) |
| `MAIL_USE_TLS` | `true` or `false` |
| `MAIL_USERNAME` | SMTP login username |
| `MAIL_PASSWORD` | SMTP password or app password |
| `MAIL_DEFAULT_SENDER` | From address for notification emails |

The `Procfile` runs `flask db upgrade` before starting gunicorn, so migrations apply automatically on every deploy.

---

## Project Structure

```
app.py                  # All models, routes, helpers, and CLI commands
templates/
  base.html             # Shared layout (navbar, dark mode, CSRF injection)
  dashboard.html
  login.html
  setup.html
  account.html
  cars/
    list.html           # Car list with hidden cars section
    detail.html         # Per-car charts, expense table, expiry warnings
    form.html
    share.html
  expenses/
    form.html           # Single form for all 5 expense types
    list.html
  admin/
    index.html
    overview.html       # All-expenses view with filters
    user_detail.html
    user_form.html
  errors/
    403.html
    404.html
static/css/style.css    # Custom styles on top of Bootstrap
migrations/             # Alembic migration files
```

---

## Authorization Summary

| Action | Owner | Shared User | Admin |
|---|---|---|---|
| View car & expenses | ✅ | ✅ | ✅ |
| Add expense | ✅ | ✅ | ❌ |
| Edit / delete own expense | ✅ | ✅ | ❌ |
| Edit / delete others' expenses | ✅ | ❌ | ❌ |
| Edit / delete car | ✅ | ❌ | ❌ |
| Manage shares | ✅ | ❌ | ❌ |
| Manage users | ❌ | ❌ | ✅ |
| Hide car globally for shared users | ✅ | ❌ | ❌ |
