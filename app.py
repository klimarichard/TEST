import os
import click
import requests
from datetime import datetime, date
from functools import wraps
from flask import (Flask, render_template, redirect, url_for, request,
                   flash, jsonify, abort)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                         login_required, current_user)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash

# ─────────────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-secret-key-in-production')

# Railway provides postgres:// but SQLAlchemy requires postgresql://
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///carexpenses.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owned_cars = db.relationship('Car', backref='owner', lazy=True)
    shared_cars = db.relationship('CarShare', backref='user', lazy=True)
    expenses = db.relationship('Expense', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_accessible_cars(self):
        owned = Car.query.filter_by(owner_id=self.id).all()
        shared_ids = [s.car_id for s in self.shared_cars]
        shared = Car.query.filter(Car.id.in_(shared_ids)).all() if shared_ids else []
        seen, result = set(), []
        for c in owned + shared:
            if c.id not in seen:
                seen.add(c.id)
                result.append(c)
        return result


class Car(db.Model):
    __tablename__ = 'cars'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    make = db.Column(db.String(80))
    model_name = db.Column(db.String(80))
    year = db.Column(db.Integer)
    license_plate = db.Column(db.String(20))
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    shares = db.relationship('CarShare', backref='car', lazy=True, cascade='all, delete-orphan')
    expenses = db.relationship('Expense', backref='car', lazy=True, cascade='all, delete-orphan')

    def is_accessible_by(self, user):
        return (self.owner_id == user.id or
                CarShare.query.filter_by(car_id=self.id, user_id=user.id).first() is not None)

    @property
    def display_name(self):
        parts = [self.name]
        if self.make and self.model_name:
            parts.append(f'({self.make} {self.model_name})')
        elif self.make:
            parts.append(f'({self.make})')
        return ' '.join(parts)


class CarShare(db.Model):
    __tablename__ = 'car_shares'
    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey('cars.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('car_id', 'user_id'),)


EXPENSE_TYPES = ['fuel', 'repair', 'toll', 'insurance', 'gadget']
TYPE_LABELS = {
    'fuel': 'Fuel', 'repair': 'Repair', 'toll': 'Toll',
    'insurance': 'Insurance', 'gadget': 'Gadget',
}
TYPE_ICONS = {
    'fuel': 'bi-fuel-pump', 'repair': 'bi-wrench-adjustable',
    'toll': 'bi-signpost-2', 'insurance': 'bi-shield-check',
    'gadget': 'bi-phone',
}
TYPE_COLORS = {
    'fuel': '#0dcaf0', 'repair': '#dc3545', 'toll': '#ffc107',
    'insurance': '#198754', 'gadget': '#6f42c1',
}


class Expense(db.Model):
    __tablename__ = 'expenses'
    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey('cars.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), default='CZK')
    amount_czk = db.Column(db.Float, nullable=False)
    expense_type = db.Column(db.String(20), nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    fuel_detail = db.relationship('FuelDetail', backref='expense', uselist=False, cascade='all, delete-orphan')
    repair_detail = db.relationship('RepairDetail', backref='expense', uselist=False, cascade='all, delete-orphan')
    toll_detail = db.relationship('TollDetail', backref='expense', uselist=False, cascade='all, delete-orphan')
    insurance_detail = db.relationship('InsuranceDetail', backref='expense', uselist=False, cascade='all, delete-orphan')
    gadget_detail = db.relationship('GadgetDetail', backref='expense', uselist=False, cascade='all, delete-orphan')

    def can_edit(self, user):
        return self.user_id == user.id or self.car.owner_id == user.id

    @property
    def type_label(self):
        return TYPE_LABELS.get(self.expense_type, self.expense_type.title())

    @property
    def type_icon(self):
        return TYPE_ICONS.get(self.expense_type, 'bi-cash')

    @property
    def type_color(self):
        return TYPE_COLORS.get(self.expense_type, '#6c757d')

    @property
    def detail(self):
        return (self.fuel_detail or self.repair_detail or
                self.toll_detail or self.insurance_detail or self.gadget_detail)


class FuelDetail(db.Model):
    __tablename__ = 'fuel_details'
    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'), nullable=False)
    liters = db.Column(db.Float)
    price_per_liter = db.Column(db.Float)
    odometer = db.Column(db.Integer)
    station_location = db.Column(db.String(200))
    transaction_time = db.Column(db.Time)

    @property
    def summary(self):
        parts = []
        if self.liters:
            parts.append(f'{self.liters:.1f} L')
        if self.station_location:
            parts.append(self.station_location)
        if self.odometer:
            parts.append(f'@ {self.odometer:,} km')
        return ' · '.join(parts) if parts else '—'


class RepairDetail(db.Model):
    __tablename__ = 'repair_details'
    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'), nullable=False)
    description = db.Column(db.Text)

    @property
    def summary(self):
        return (self.description or '—')[:80]


class TollDetail(db.Model):
    __tablename__ = 'toll_details'
    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'), nullable=False)
    route = db.Column(db.String(200))
    toll_type = db.Column(db.String(50))

    @property
    def summary(self):
        parts = []
        if self.toll_type:
            parts.append(self.toll_type)
        if self.route:
            parts.append(self.route)
        return ' · '.join(parts) if parts else '—'


class InsuranceDetail(db.Model):
    __tablename__ = 'insurance_details'
    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'), nullable=False)
    insurance_type = db.Column(db.String(100))
    provider = db.Column(db.String(100))
    expiration_date = db.Column(db.Date)

    @property
    def summary(self):
        parts = []
        if self.insurance_type:
            parts.append(self.insurance_type)
        if self.provider:
            parts.append(self.provider)
        if self.expiration_date:
            parts.append(f'exp. {self.expiration_date.strftime("%d.%m.%Y")}')
        return ' · '.join(parts) if parts else '—'

    @property
    def is_expiring_soon(self):
        if not self.expiration_date:
            return False
        from datetime import timedelta
        return date.today() < self.expiration_date <= date.today() + timedelta(days=30)

    @property
    def is_expired(self):
        return bool(self.expiration_date and self.expiration_date < date.today())


class GadgetDetail(db.Model):
    __tablename__ = 'gadget_details'
    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'), nullable=False)
    gadget_type = db.Column(db.String(100))

    @property
    def summary(self):
        return self.gadget_type or '—'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login', next=request.url))
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


_rate_cache: dict = {}


def get_exchange_rate(from_currency: str, to_currency: str = 'CZK') -> float | None:
    if from_currency == to_currency:
        return 1.0
    cache_key = f'{from_currency}_{to_currency}'
    cached = _rate_cache.get(cache_key)
    if cached:
        ts, rate = cached
        if (datetime.utcnow() - ts).seconds < 3600:
            return rate
    try:
        r = requests.get(
            'https://api.frankfurter.app/latest',
            params={'from': from_currency, 'to': to_currency},
            timeout=5,
        )
        r.raise_for_status()
        rate = r.json()['rates'][to_currency]
        _rate_cache[cache_key] = (datetime.utcnow(), rate)
        return rate
    except Exception:
        return None


SUPPORTED_CURRENCIES = ['CZK', 'EUR', 'USD', 'GBP', 'CHF', 'PLN', 'HUF', 'NOK', 'SEK', 'DKK']
TOLL_TYPES = ['Highway vignette', 'Toll gate', 'Bridge toll', 'Tunnel toll', 'Parking', 'Other']
INSURANCE_TYPES = ['Liability (Povinné ručení)', 'Comprehensive (Havarijní)', 'GAP Insurance', 'Other']


@app.template_filter('czk')
def format_czk(value):
    if value is None:
        return '—'
    formatted = f'{value:,.0f}'.replace(',', '\u202f')  # narrow no-break space (CZ thousands sep)
    return f'{formatted}\u00a0Kč'


@app.context_processor
def inject_globals():
    return {
        'now': datetime.utcnow(),
        'TYPE_COLORS': TYPE_COLORS,
        'TYPE_LABELS': TYPE_LABELS,
        'TYPE_ICONS': TYPE_ICONS,
        'EXPENSE_TYPES': EXPENSE_TYPES,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Error handlers
# ─────────────────────────────────────────────────────────────────────────────

@app.errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html'), 403


@app.errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('dashboard') if current_user.is_authenticated else url_for('login'))


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if User.query.first():
        return redirect(url_for('login'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if not username or not email or not password:
            flash('All fields are required.', 'danger')
        elif password != confirm:
            flash('Passwords do not match.', 'danger')
        else:
            user = User(username=username, email=email, is_admin=True)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Admin account created. Please sign in.', 'success')
            return redirect(url_for('login'))
    return render_template('setup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if not User.query.first():
        return redirect(url_for('setup'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=bool(request.form.get('remember')))
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    from collections import defaultdict
    cars = current_user.get_accessible_cars()
    car_ids = [c.id for c in cars]

    all_expenses = (Expense.query
                    .filter(Expense.car_id.in_(car_ids))
                    .order_by(Expense.date)
                    .all()) if car_ids else []

    car_totals = {c.id: 0.0 for c in cars}
    monthly_data: dict = defaultdict(float)
    type_totals: dict = defaultdict(float)

    for e in all_expenses:
        car_totals[e.car_id] += e.amount_czk
        monthly_data[e.date.strftime('%Y-%m')] += e.amount_czk
        type_totals[e.expense_type] += e.amount_czk

    sorted_months = sorted(monthly_data.keys())[-12:]
    this_month = datetime.utcnow().strftime('%Y-%m')
    this_month_total = monthly_data.get(this_month, 0.0)
    recent_expenses = sorted(all_expenses, key=lambda e: (e.date, e.created_at), reverse=True)[:10]

    return render_template('dashboard.html',
        cars=cars,
        car_totals=car_totals,
        recent_expenses=recent_expenses,
        total_spent=sum(type_totals.values()),
        total_expense_count=len(all_expenses),
        this_month_total=this_month_total,
        chart_monthly={
            'labels': sorted_months,
            'data': [monthly_data[m] for m in sorted_months],
        },
        chart_types={
            'labels': [TYPE_LABELS.get(t, t) for t in type_totals],
            'data': list(type_totals.values()),
            'colors': [TYPE_COLORS.get(t, '#6c757d') for t in type_totals],
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cars
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/cars')
@login_required
def cars_list():
    cars = current_user.get_accessible_cars()
    return render_template('cars/list.html', cars=cars)


@app.route('/cars/new', methods=['GET', 'POST'])
@login_required
def car_new():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Car name is required.', 'danger')
            return render_template('cars/form.html', car=None)
        car = Car(
            name=name,
            make=request.form.get('make', '').strip() or None,
            model_name=request.form.get('model_name', '').strip() or None,
            year=request.form.get('year') or None,
            license_plate=request.form.get('license_plate', '').strip() or None,
            owner_id=current_user.id,
        )
        db.session.add(car)
        db.session.commit()
        flash(f'Car "{car.name}" added.', 'success')
        return redirect(url_for('car_detail', car_id=car.id))
    return render_template('cars/form.html', car=None)


@app.route('/cars/<int:car_id>')
@login_required
def car_detail(car_id):
    from collections import defaultdict
    car = Car.query.get_or_404(car_id)
    if not car.is_accessible_by(current_user):
        abort(403)

    expenses = (Expense.query
                .filter_by(car_id=car_id)
                .order_by(Expense.date.desc(), Expense.created_at.desc())
                .all())

    monthly_by_type: dict = defaultdict(lambda: defaultdict(float))
    type_totals: dict = defaultdict(float)
    for e in expenses:
        key = e.date.strftime('%Y-%m')
        monthly_by_type[key][e.expense_type] += e.amount_czk
        type_totals[e.expense_type] += e.amount_czk

    all_months = sorted(monthly_by_type.keys())[-12:]

    # Fuel efficiency L/100 km
    fuel_exps = sorted(
        [e for e in expenses
         if e.expense_type == 'fuel' and e.fuel_detail
         and e.fuel_detail.odometer and e.fuel_detail.liters],
        key=lambda e: e.fuel_detail.odometer,
    )
    eff_labels, eff_data = [], []
    for i in range(1, len(fuel_exps)):
        dist = fuel_exps[i].fuel_detail.odometer - fuel_exps[i - 1].fuel_detail.odometer
        if dist > 0:
            eff = fuel_exps[i].fuel_detail.liters / dist * 100
            eff_labels.append(fuel_exps[i].date.strftime('%d.%m.%Y'))
            eff_data.append(round(eff, 2))

    # Insurance warnings
    insurance_warnings = [
        e for e in expenses
        if e.expense_type == 'insurance' and e.insurance_detail
        and (e.insurance_detail.is_expired or e.insurance_detail.is_expiring_soon)
    ]

    return render_template('cars/detail.html',
        car=car,
        expenses=expenses,
        is_owner=(car.owner_id == current_user.id),
        total_spent=sum(e.amount_czk for e in expenses),
        insurance_warnings=insurance_warnings,
        chart_stacked={
            'labels': all_months,
            'types': EXPENSE_TYPES,
            'data': {t: [monthly_by_type[m].get(t, 0) for m in all_months] for t in EXPENSE_TYPES},
        },
        chart_types={
            'labels': [TYPE_LABELS.get(t, t) for t in type_totals],
            'data': list(type_totals.values()),
            'colors': [TYPE_COLORS.get(t, '#6c757d') for t in type_totals],
        },
        chart_fuel_eff={'labels': eff_labels, 'data': eff_data},
    )


@app.route('/cars/<int:car_id>/edit', methods=['GET', 'POST'])
@login_required
def car_edit(car_id):
    car = Car.query.get_or_404(car_id)
    if car.owner_id != current_user.id:
        abort(403)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Car name is required.', 'danger')
            return render_template('cars/form.html', car=car)
        car.name = name
        car.make = request.form.get('make', '').strip() or None
        car.model_name = request.form.get('model_name', '').strip() or None
        car.year = request.form.get('year') or None
        car.license_plate = request.form.get('license_plate', '').strip() or None
        db.session.commit()
        flash('Car updated.', 'success')
        return redirect(url_for('car_detail', car_id=car.id))
    return render_template('cars/form.html', car=car)


@app.route('/cars/<int:car_id>/delete', methods=['POST'])
@login_required
def car_delete(car_id):
    car = Car.query.get_or_404(car_id)
    if car.owner_id != current_user.id:
        abort(403)
    name = car.name
    db.session.delete(car)
    db.session.commit()
    flash(f'Car "{name}" deleted.', 'success')
    return redirect(url_for('cars_list'))


@app.route('/cars/<int:car_id>/share', methods=['GET', 'POST'])
@login_required
def car_share(car_id):
    car = Car.query.get_or_404(car_id)
    if car.owner_id != current_user.id:
        abort(403)
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            username = request.form.get('username', '').strip()
            user = User.query.filter_by(username=username).first()
            if not user:
                flash(f'User "{username}" not found.', 'danger')
            elif user.id == current_user.id:
                flash("You can't share with yourself.", 'warning')
            elif CarShare.query.filter_by(car_id=car_id, user_id=user.id).first():
                flash(f'Already shared with {user.username}.', 'warning')
            else:
                db.session.add(CarShare(car_id=car_id, user_id=user.id))
                db.session.commit()
                flash(f'Car shared with {user.username}.', 'success')
        elif action == 'remove':
            share = CarShare.query.filter_by(
                car_id=car_id,
                user_id=request.form.get('user_id', type=int),
            ).first_or_404()
            db.session.delete(share)
            db.session.commit()
            flash('Access removed.', 'success')
        return redirect(url_for('car_share', car_id=car_id))
    return render_template('cars/share.html', car=car,
                           shared_users=[s.user for s in car.shares])


# ─────────────────────────────────────────────────────────────────────────────
# Expenses
# ─────────────────────────────────────────────────────────────────────────────

def _parse_expense_form(form):
    """Parse common expense fields. Returns (data_dict, error_str)."""
    try:
        amount = float(form.get('amount', 0))
        if amount <= 0:
            return None, 'Amount must be greater than 0.'
    except (ValueError, TypeError):
        return None, 'Invalid amount.'

    currency = form.get('currency', 'CZK')
    if currency == 'CZK':
        amount_czk = amount
    else:
        rate = get_exchange_rate(currency, 'CZK')
        if rate is None:
            return None, f'Could not fetch exchange rate for {currency}. Please try again.'
        amount_czk = amount * rate

    try:
        exp_date = datetime.strptime(form.get('date', ''), '%Y-%m-%d').date()
    except ValueError:
        return None, 'Invalid date.'

    return {
        'amount': amount,
        'currency': currency,
        'amount_czk': amount_czk,
        'date': exp_date,
        'notes': form.get('notes', '').strip() or None,
    }, None


def _apply_type_detail(expense, form):
    """Create or update the type-specific detail row."""
    t = expense.expense_type

    if t == 'fuel':
        d = expense.fuel_detail or FuelDetail()
        d.expense_id = expense.id
        try:
            d.liters = float(form.get('liters') or 0) or None
            d.odometer = int(form.get('odometer') or 0) or None
            ppl = float(form.get('price_per_liter') or 0) or None
            if not ppl and d.liters and expense.amount:
                ppl = round(expense.amount / d.liters, 2)
            d.price_per_liter = ppl
        except (ValueError, TypeError):
            d.liters = d.price_per_liter = d.odometer = None
        d.station_location = form.get('station_location', '').strip() or None
        time_str = form.get('transaction_time', '').strip()
        try:
            d.transaction_time = datetime.strptime(time_str, '%H:%M').time() if time_str else None
        except ValueError:
            d.transaction_time = None
        if not expense.fuel_detail:
            db.session.add(d)

    elif t == 'repair':
        d = expense.repair_detail or RepairDetail()
        d.expense_id = expense.id
        d.description = form.get('description', '').strip() or None
        if not expense.repair_detail:
            db.session.add(d)

    elif t == 'toll':
        d = expense.toll_detail or TollDetail()
        d.expense_id = expense.id
        d.route = form.get('route', '').strip() or None
        d.toll_type = form.get('toll_type', '').strip() or None
        if not expense.toll_detail:
            db.session.add(d)

    elif t == 'insurance':
        d = expense.insurance_detail or InsuranceDetail()
        d.expense_id = expense.id
        d.insurance_type = form.get('insurance_type', '').strip() or None
        d.provider = form.get('provider', '').strip() or None
        exp_str = form.get('expiration_date', '').strip()
        try:
            d.expiration_date = datetime.strptime(exp_str, '%Y-%m-%d').date() if exp_str else None
        except ValueError:
            d.expiration_date = None
        if not expense.insurance_detail:
            db.session.add(d)

    elif t == 'gadget':
        d = expense.gadget_detail or GadgetDetail()
        d.expense_id = expense.id
        d.gadget_type = form.get('gadget_type', '').strip() or None
        if not expense.gadget_detail:
            db.session.add(d)


@app.route('/cars/<int:car_id>/expenses/new', methods=['GET', 'POST'])
@login_required
def expense_new(car_id):
    car = Car.query.get_or_404(car_id)
    if not car.is_accessible_by(current_user):
        abort(403)

    expense_type = request.args.get('type', 'fuel')
    if expense_type not in EXPENSE_TYPES:
        expense_type = 'fuel'

    if request.method == 'POST':
        expense_type = request.form.get('expense_type', 'fuel')
        if expense_type not in EXPENSE_TYPES:
            expense_type = 'fuel'
        data, error = _parse_expense_form(request.form)
        if error:
            flash(error, 'danger')
        else:
            expense = Expense(car_id=car_id, user_id=current_user.id,
                              expense_type=expense_type, **data)
            db.session.add(expense)
            db.session.flush()
            _apply_type_detail(expense, request.form)
            db.session.commit()
            flash('Expense added.', 'success')
            return redirect(url_for('car_detail', car_id=car_id))

    return render_template('expenses/form.html',
        car=car, expense=None, expense_type=expense_type,
        currencies=SUPPORTED_CURRENCIES, toll_types=TOLL_TYPES,
        insurance_types=INSURANCE_TYPES, today=date.today().isoformat(),
    )


@app.route('/expenses/<int:expense_id>/edit', methods=['GET', 'POST'])
@login_required
def expense_edit(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    if not expense.can_edit(current_user):
        abort(403)
    car = expense.car

    if request.method == 'POST':
        data, error = _parse_expense_form(request.form)
        if error:
            flash(error, 'danger')
        else:
            expense.amount = data['amount']
            expense.currency = data['currency']
            expense.amount_czk = data['amount_czk']
            expense.date = data['date']
            expense.notes = data['notes']
            _apply_type_detail(expense, request.form)
            db.session.commit()
            flash('Expense updated.', 'success')
            return redirect(url_for('car_detail', car_id=car.id))

    return render_template('expenses/form.html',
        car=car, expense=expense, expense_type=expense.expense_type,
        currencies=SUPPORTED_CURRENCIES, toll_types=TOLL_TYPES,
        insurance_types=INSURANCE_TYPES, today=date.today().isoformat(),
    )


@app.route('/expenses/<int:expense_id>/delete', methods=['POST'])
@login_required
def expense_delete(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    if not expense.can_edit(current_user):
        abort(403)
    car_id = expense.car_id
    db.session.delete(expense)
    db.session.commit()
    flash('Expense deleted.', 'success')
    return redirect(url_for('car_detail', car_id=car_id))


# ─────────────────────────────────────────────────────────────────────────────
# Admin
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin_index():
    users = User.query.order_by(User.username).all()
    return render_template('admin/index.html', users=users)


@app.route('/admin/users/new', methods=['GET', 'POST'])
@admin_required
def admin_user_new():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        is_admin = bool(request.form.get('is_admin'))

        errors = []
        if not username:
            errors.append('Username is required.')
        if not email:
            errors.append('Email is required.')
        if not password:
            errors.append('Password is required.')
        if username and User.query.filter_by(username=username).first():
            errors.append('Username already taken.')
        if email and User.query.filter_by(email=email).first():
            errors.append('Email already registered.')

        if errors:
            for e in errors:
                flash(e, 'danger')
        else:
            user = User(username=username, email=email, is_admin=is_admin)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash(f'User "{username}" created.', 'success')
            return redirect(url_for('admin_index'))

    return render_template('admin/user_form.html', user=None)


@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_user_edit(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        is_admin = bool(request.form.get('is_admin'))
        new_password = request.form.get('password', '').strip()

        errors = []
        if not username:
            errors.append('Username is required.')
        if not email:
            errors.append('Email is required.')
        existing_u = User.query.filter_by(username=username).first()
        if existing_u and existing_u.id != user.id:
            errors.append('Username already taken.')
        existing_e = User.query.filter_by(email=email).first()
        if existing_e and existing_e.id != user.id:
            errors.append('Email already registered.')

        if errors:
            for e in errors:
                flash(e, 'danger')
        else:
            user.username = username
            user.email = email
            user.is_admin = is_admin
            if new_password:
                user.set_password(new_password)
            db.session.commit()
            flash('User updated.', 'success')
            return redirect(url_for('admin_index'))

    return render_template('admin/user_form.html', user=user)


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_user_delete(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You can't delete your own account.", 'warning')
        return redirect(url_for('admin_index'))
    username = user.username
    db.session.delete(user)
    db.session.commit()
    flash(f'User "{username}" deleted.', 'success')
    return redirect(url_for('admin_index'))


# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/api/exchange-rate')
@login_required
def api_exchange_rate():
    from_currency = request.args.get('from', 'EUR')
    if from_currency not in SUPPORTED_CURRENCIES:
        return jsonify({'error': 'Unsupported currency'}), 400
    if from_currency == 'CZK':
        return jsonify({'rate': 1.0, 'from': 'CZK', 'to': 'CZK'})
    rate = get_exchange_rate(from_currency, 'CZK')
    if rate is None:
        return jsonify({'error': 'Could not fetch rate'}), 503
    return jsonify({'rate': rate, 'from': from_currency, 'to': 'CZK'})


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

@app.cli.command('init-db')
def init_db_command():
    """Create all database tables."""
    db.create_all()
    click.echo('Database initialized.')


@app.cli.command('create-admin')
@click.argument('username')
@click.argument('email')
@click.argument('password')
def create_admin_command(username, email, password):
    """Create an admin user.  Usage: flask create-admin USERNAME EMAIL PASSWORD"""
    db.create_all()
    if User.query.filter_by(username=username).first():
        click.echo(f'Error: user "{username}" already exists.', err=True)
        return
    user = User(username=username, email=email, is_admin=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo(f'Admin user "{username}" created.')


# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap DB on startup
# ─────────────────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
