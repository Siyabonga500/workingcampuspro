import os
import re
import secrets
import uuid
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

import click
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func

from models import (
    CATEGORIES,
    DUT_CAMPUSES,
    GENDERS,
    LOW_STOCK_THRESHOLD,
    OPEN_ORDER_STATUSES,
    ORDER_STATUSES,
    PRODUCT_GENDERS,
    Order,
    OrderItem,
    Product,
    ProductImage,
    User,
    db,
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
SEED_IMAGE_DIR = BASE_DIR / "seed_images"
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_IMAGE_SIDE = 1200

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^(\+27|0)\d{9}$")
MIN_PASSWORD_LENGTH = 8


def _load_secret_key(instance_path):
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    key_file = Path(instance_path) / "secret_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    return key_file.read_text().strip()


app = Flask(__name__)
os.makedirs(app.instance_path, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.config.update(
    SECRET_KEY=_load_secret_key(app.instance_path),
    SQLALCHEMY_DATABASE_URI=os.environ.get(
        "DATABASE_URL", f"sqlite:///{Path(app.instance_path) / 'unipro.db'}"
    ),
    MAX_CONTENT_LENGTH=40 * 1024 * 1024,
)
db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "info"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# --- CSRF protection -------------------------------------------------------


def csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]


@app.before_request
def check_csrf():
    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        if not secrets.compare_digest(token, session.get("_csrf_token", "")):
            abort(400, "Invalid or missing CSRF token. Please reload the page.")


@app.context_processor
def inject_globals():
    return {
        "csrf_token": csrf_token,
        "DUT_CAMPUSES": DUT_CAMPUSES,
        "CATEGORIES": CATEGORIES,
        "cart_count": sum(get_cart().values()),
    }


# --- Helpers ---------------------------------------------------------------


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def is_safe_next(target):
    if not target:
        return False
    parsed = urlparse(target)
    return (
        not parsed.scheme
        and not parsed.netloc
        and target.startswith("/")
        and not target.startswith(("//", "/\\"))
    )

def validate_profile_form(form):
    """Validate the personal details shared by sign-up and profile editing."""
    errors = []
    data = {
        "name": form.get("name", "").strip(),
        "surname": form.get("surname", "").strip(),
        "gender": form.get("gender", ""),
        "phone": re.sub(r"[\s\-()]", "", form.get("phone", "")),
        "residence_address": form.get("residence_address", "").strip(),
        "campus": form.get("campus", ""),
    }
    if not data["name"]:
        errors.append("Name is required.")
    if not data["surname"]:
        errors.append("Surname is required.")
    if data["gender"] not in GENDERS:
        errors.append("Select your gender.")
    if not PHONE_RE.match(data["phone"]):
        errors.append("Enter a valid South African phone number, e.g. 0631234567 or +27631234567.")
    if not data["residence_address"]:
        errors.append("Residence address is required.")
    if data["campus"] not in DUT_CAMPUSES:
        errors.append("Select your DUT campus.")
    return data, errors


def validate_new_password(password, confirm):
    if len(password) < MIN_PASSWORD_LENGTH:
        return [f"Password must be at least {MIN_PASSWORD_LENGTH} characters."]
    if password != confirm:
        return ["Passwords do not match."]
    return []


# --- Cart (stored in the session as {product_id: quantity}) ---------------


def get_cart():
    cart = session.get("cart", {})
    return cart if isinstance(cart, dict) else {}


def save_cart(cart):
    session["cart"] = {k: v for k, v in cart.items() if v > 0}


def cart_lines():
    """Return (lines, total) for the current cart, dropping removed products."""
    cart = get_cart()
    lines = []
    total = Decimal("0.00")
    if cart:
        products = Product.query.filter(Product.id.in_([int(pid) for pid in cart])).all()
        for product in products:
            quantity = cart[str(product.id)]
            line_total = product.price * quantity
            total += line_total
            lines.append({"product": product, "quantity": quantity, "line_total": line_total})
    return lines, total



def save_image(source):
    """Normalise an uploaded image (orientation, size, format) and store it.

    `source` is a path or file-like object. Returns the stored filename, or
    raises ValueError if the file is not a usable image.
    """
    try:
        with Image.open(source) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            filename = f"{uuid.uuid4().hex}.webp"
            img.save(UPLOAD_DIR / filename, "WEBP", quality=82, method=4)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("not a valid image") from exc
    return filename


def delete_image_file(filename):
    path = UPLOAD_DIR / filename
    if path.is_file():
        path.unlink()


def attach_uploaded_images(product, files):
    errors = []
    position = len(product.images)
    for file in files:
        if not file or not file.filename:
            continue
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            errors.append(f"{file.filename}: unsupported file type.")
            continue
        try:
            filename = save_image(file.stream)
        except ValueError:
            errors.append(f"{file.filename}: could not be read as an image.")
            continue
        product.images.append(ProductImage(filename=filename, position=position))
        position += 1
    return errors


def validate_product_form(form):
    errors = []
    data = {
        "name": form.get("name", "").strip(),
        "description": form.get("description", "").strip(),
        "category": form.get("category", ""),
        "gender": form.get("gender", ""),
        "campus": form.get("campus", ""),
    }
    if not data["name"]:
        errors.append("Product name is required.")
    if data["category"] not in CATEGORIES:
        errors.append("Choose a valid category.")
    if data["gender"] not in PRODUCT_GENDERS:
        errors.append("Choose a valid gender.")
    if data["campus"] not in DUT_CAMPUSES:
        errors.append("Choose a valid campus.")
    try:
        data["price"] = Decimal(form.get("price", "")).quantize(Decimal("0.01"))
        if data["price"] < 0:
            raise InvalidOperation
    except InvalidOperation:
        errors.append("Price must be a positive number.")
    try:
        data["quantity"] = int(form.get("quantity", ""))
        if data["quantity"] < 0:
            raise ValueError
    except ValueError:
        errors.append("Quantity must be a whole number of 0 or more.")
    return data, errors


# --- Public routes ---------------------------------------------------------


@app.route("/")
def index():
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("index.html", products=products)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    form = request.form
    if request.method == "POST":
        data, errors = validate_profile_form(form)
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")
        if not EMAIL_RE.match(email):
            errors.insert(0, "Enter a valid email address.")
        elif User.query.filter_by(email=email).first():
            errors.insert(0, "An account with that email already exists.")
        errors += validate_new_password(password, form.get("confirm_password", ""))

        if errors:
            for error in errors:
                flash(error, "error")
        else:
            user = User(email=email, **data)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash(f"Welcome to UniPro, {user.name}! Your account has been created.", "success")
            return redirect(url_for("index"))

    return render_template("register.html", form=form, genders=GENDERS)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user, remember=bool(request.form.get("remember")))
            flash(f"Welcome back, {user.name}!", "success")
            next_url = request.args.get("next")
            if is_safe_next(next_url):
                return redirect(next_url)
            return redirect(url_for("admin_dashboard" if user.is_admin else "account_dashboard"))
        flash("Incorrect email or password.", "error")

    return render_template("login.html", form=request.form)


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# --- Cart & checkout -------------------------------------------------------


@app.route("/cart")
def cart():
    lines, total = cart_lines()
    default_campus = current_user.campus if current_user.is_authenticated else ""
    return render_template("cart.html", lines=lines, total=total, default_campus=default_campus)


@app.route("/cart/add/<int:product_id>", methods=["POST"])
def cart_add(product_id):
    product = db.get_or_404(Product, product_id)
    cart = get_cart()
    key = str(product.id)
    if cart.get(key, 0) + 1 > product.quantity:
        flash(f"Sorry, there are no more “{product.name}” in stock.", "error")
    else:
        cart[key] = cart.get(key, 0) + 1
        save_cart(cart)
        flash(f"“{product.name}” added to your cart.", "success")
    return redirect(url_for("index", _anchor=f"product-{product.id}"))


@app.route("/cart/update/<int:product_id>", methods=["POST"])
def cart_update(product_id):
    cart = get_cart()
    key = str(product_id)
    product = db.session.get(Product, product_id)
    try:
        quantity = int(request.form.get("quantity", 0))
    except ValueError:
        quantity = 0
    if product is None or quantity <= 0:
        cart.pop(key, None)
    else:
        if quantity > product.quantity:
            flash(f"Only {product.quantity} “{product.name}” in stock.", "error")
            quantity = product.quantity
        cart[key] = quantity
    save_cart(cart)
    return redirect(url_for("cart"))


@app.route("/checkout", methods=["POST"])
@login_required
def checkout():
    lines, total = cart_lines()
    if not lines:
        flash("Your cart is empty.", "error")
        return redirect(url_for("cart"))

    campus = request.form.get("collection_campus", "")
    if campus not in DUT_CAMPUSES:
        flash("Choose the campus where you will collect your order.", "error")
        return redirect(url_for("cart"))

    for line in lines:
        if line["quantity"] > line["product"].quantity:
            flash(
                f"Only {line['product'].quantity} “{line['product'].name}” left. "
                "Please update your cart.",
                "error",
            )
            return redirect(url_for("cart"))

    order = Order(
        user=current_user,
        collection_campus=campus,
        notes=request.form.get("notes", "").strip()[:500],
        total=total,
    )
    for line in lines:
        product = line["product"]
        product.quantity -= line["quantity"]
        order.items.append(
            OrderItem(
                product=product,
                product_name=product.name,
                unit_price=product.price,
                quantity=line["quantity"],
            )
        )
    db.session.add(order)
    db.session.commit()
    save_cart({})
    flash(f"Order {order.reference} placed! We'll let you know when it's ready.", "success")
    return redirect(url_for("account_order", order_id=order.id))


def restock(order):
    for item in order.items:
        if item.product is not None:
            item.product.quantity += item.quantity


# --- Customer dashboard ----------------------------------------------------


@app.route("/account/")
@login_required
def account_dashboard():
    orders = current_user.orders.order_by(Order.created_at.desc()).all()
    active = [o for o in orders if o.status in OPEN_ORDER_STATUSES]
    stats = {
        "orders": len(orders),
        "active": len(active),
        "spent": sum((o.total for o in orders if o.status != "cancelled"), Decimal("0.00")),
        "cart": sum(get_cart().values()),
    }
    return render_template(
        "account/dashboard.html",
        stats=stats,
        active_orders=active,
        recent_orders=orders[:5],
    )


@app.route("/account/orders")
@login_required
def account_orders():
    orders = current_user.orders.order_by(Order.created_at.desc()).all()
    return render_template("account/orders.html", orders=orders)


@app.route("/account/orders/<int:order_id>")
@login_required
def account_order(order_id):
    order = db.get_or_404(Order, order_id)
    if order.user_id != current_user.id:
        abort(404)
    return render_template("account/order_detail.html", order=order)


@app.route("/account/orders/<int:order_id>/cancel", methods=["POST"])
@login_required
def account_cancel_order(order_id):
    order = db.get_or_404(Order, order_id)
    if order.user_id != current_user.id:
        abort(404)
    if not order.can_cancel:
        flash("This order can no longer be cancelled. Please contact us.", "error")
    else:
        order.status = "cancelled"
        restock(order)
        db.session.commit()
        flash(f"Order {order.reference} was cancelled.", "success")
    return redirect(url_for("account_order", order_id=order.id))


@app.route("/account/profile", methods=["GET", "POST"])
@login_required
def account_profile():
    if request.method == "POST":
        data, errors = validate_profile_form(request.form)
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("account/profile.html", form=request.form, genders=GENDERS)
        for key, value in data.items():
            setattr(current_user, key, value)
        db.session.commit()
        flash("Your profile was updated.", "success")
        return redirect(url_for("account_profile"))

    form = {
        "name": current_user.name,
        "surname": current_user.surname,
        "gender": current_user.gender,
        "phone": current_user.phone,
        "residence_address": current_user.residence_address,
        "campus": current_user.campus,
    }
    return render_template("account/profile.html", form=form, genders=GENDERS)


@app.route("/account/password", methods=["POST"])
@login_required
def account_password():
    if not current_user.check_password(request.form.get("current_password", "")):
        flash("Your current password is incorrect.", "error")
    else:
        password = request.form.get("new_password", "")
        errors = validate_new_password(password, request.form.get("confirm_password", ""))
        if errors:
            for error in errors:
                flash(error, "error")
        else:
            current_user.set_password(password)
            db.session.commit()
            flash("Your password was changed.", "success")
    return redirect(url_for("account_profile"))


# --- Admin routes ----------------------------------------------------------


@app.route("/admin/")
@admin_required
def admin_dashboard():
    sold = Order.status != "cancelled"
    status_counts = dict(
        db.session.query(Order.status, func.count(Order.id)).group_by(Order.status).all()
    )
    stats = {
        "revenue": db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(sold).scalar(),
        "orders": sum(status_counts.values()),
        "open_orders": sum(status_counts.get(s, 0) for s in OPEN_ORDER_STATUSES),
        "customers": User.query.filter_by(is_admin=False).count(),
        "products": Product.query.count(),
        "low_stock": Product.query.filter(Product.quantity <= LOW_STOCK_THRESHOLD).count(),
    }
    orders_by_status = [
        (key, label, status_counts.get(key, 0)) for key, label in ORDER_STATUSES.items()
    ]
    sales_by_campus = (
        db.session.query(Order.collection_campus, func.sum(Order.total), func.count(Order.id))
        .filter(sold)
        .group_by(Order.collection_campus)
        .order_by(func.sum(Order.total).desc())
        .all()
    )
    top_products = (
        db.session.query(OrderItem.product_name, func.sum(OrderItem.quantity))
        .join(Order)
        .filter(sold)
        .group_by(OrderItem.product_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
        .all()
    )
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        orders_by_status=orders_by_status,
        max_status=max([c for _, _, c in orders_by_status] + [1]),
        sales_by_campus=sales_by_campus,
        max_campus=max([float(t) for _, t, _ in sales_by_campus] + [1]),
        top_products=top_products,
        recent_orders=Order.query.order_by(Order.created_at.desc()).limit(6).all(),
        low_stock=Product.query.filter(Product.quantity <= LOW_STOCK_THRESHOLD)
        .order_by(Product.quantity)
        .all(),
        new_customers=User.query.filter_by(is_admin=False)
        .order_by(User.created_at.desc())
        .limit(5)
        .all(),
    )


@app.route("/admin/products")
@admin_required
def admin_products():
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("admin/products.html", products=products)


@app.route("/admin/products/new", methods=["GET", "POST"])
@admin_required
def admin_new_product():
    form = request.form
    if request.method == "POST":
        data, errors = validate_product_form(form)
        if not errors:
            product = Product(**data)
            errors += attach_uploaded_images(product, request.files.getlist("images"))
            db.session.add(product)
            db.session.commit()
            for error in errors:
                flash(error, "error")
            flash(f"“{product.name}” was added.", "success")
            return redirect(url_for("admin_products"))
        for error in errors:
            flash(error, "error")
    return render_template(
        "admin/product_form.html", form=form, product=None, product_genders=PRODUCT_GENDERS
    )


@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_product(product_id):
    product = db.get_or_404(Product, product_id)
    form = request.form
    if request.method == "POST":
        data, errors = validate_product_form(form)
        if not errors:
            for key, value in data.items():
                setattr(product, key, value)
            errors += attach_uploaded_images(product, request.files.getlist("images"))
            db.session.commit()
            for error in errors:
                flash(error, "error")
            flash(f"“{product.name}” was updated.", "success")
            return redirect(url_for("admin_edit_product", product_id=product.id))
        for error in errors:
            flash(error, "error")
    else:
        form = {
            "name": product.name,
            "description": product.description,
            "category": product.category,
            "gender": product.gender,
            "campus": product.campus,
            "price": f"{product.price:.2f}",
            "quantity": product.quantity,
        }
    return render_template(
        "admin/product_form.html", form=form, product=product, product_genders=PRODUCT_GENDERS
    )


@app.route("/admin/products/<int:product_id>/delete", methods=["POST"])
@admin_required
def admin_delete_product(product_id):
    product = db.get_or_404(Product, product_id)
    filenames = [image.filename for image in product.images]
    # Keep past orders intact: they store the product name and price.
    OrderItem.query.filter_by(product_id=product.id).update({"product_id": None})
    db.session.delete(product)
    db.session.commit()
    for filename in filenames:
        delete_image_file(filename)
    flash(f"“{product.name}” was deleted.", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/images/<int:image_id>/delete", methods=["POST"])
@admin_required
def admin_delete_image(image_id):
    image = db.get_or_404(ProductImage, image_id)
    product_id = image.product_id
    filename = image.filename
    db.session.delete(image)
    db.session.commit()
    delete_image_file(filename)
    flash("Image removed.", "success")
    return redirect(url_for("admin_edit_product", product_id=product_id))


@app.route("/admin/orders")
@admin_required
def admin_orders():
    status = request.args.get("status", "")
    query = Order.query.order_by(Order.created_at.desc())
    if status in ORDER_STATUSES:
        query = query.filter_by(status=status)
    elif status == "open":
        query = query.filter(Order.status.in_(OPEN_ORDER_STATUSES))
    return render_template(
        "admin/orders.html", orders=query.all(), status=status, statuses=ORDER_STATUSES
    )


@app.route("/admin/orders/<int:order_id>", methods=["GET", "POST"])
@admin_required
def admin_order(order_id):
    order = db.get_or_404(Order, order_id)
    if request.method == "POST":
        new_status = request.form.get("status", "")
        if new_status not in ORDER_STATUSES:
            flash("Choose a valid status.", "error")
        elif order.status == "cancelled":
            flash("Cancelled orders cannot be reopened.", "error")
        elif new_status != order.status:
            if new_status == "cancelled":
                restock(order)
            order.status = new_status
            db.session.commit()
            flash(f"Order {order.reference} is now “{order.status_label}”.", "success")
        return redirect(url_for("admin_order", order_id=order.id))
    return render_template("admin/order_detail.html", order=order, statuses=ORDER_STATUSES)


@app.route("/admin/users")
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    order_counts = dict(
        db.session.query(Order.user_id, func.count(Order.id)).group_by(Order.user_id).all()
    )
    return render_template("admin/users.html", users=users, order_counts=order_counts)


@app.route("/admin/users/<int:user_id>/toggle-admin", methods=["POST"])
@admin_required
def admin_toggle_admin(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("You cannot change your own admin access.", "error")
    else:
        user.is_admin = not user.is_admin
        db.session.commit()
        state = "now an admin" if user.is_admin else "no longer an admin"
        flash(f"{user.full_name} is {state}.", "success")
    return redirect(url_for("admin_users"))


# --- Setup & CLI -----------------------------------------------------------

SAMPLE_PRODUCTS = [
    {
        "name": "Nike Air Force 1 – Blue Heel",
        "description": "Classic white leather Air Force 1 with blue heel tab and multicolour outsole.",
        "category": "sneakers",
        "price": Decimal("1000.00"),
        "gender": "unisex",
        "campus": "Steve Biko Campus (Durban)",
        "quantity": 15,
        "images": ["A1.png", "A2.png", "A3.png", "A4.png"],
    },
    {
        "name": "Nike Air Force 1 – Pastel",
        "description": "White Air Force 1 with pastel pink and blue accents.",
        "category": "sneakers",
        "price": Decimal("249.99"),
        "gender": "men",
        "campus": "Ritson Campus (Durban)",
        "quantity": 42,
        "images": ["B1.png", "B2.png", "B3.png", "B4.jpg"],
    },
    {
        "name": "Pink Stripe Platform Sneakers",
        "description": "White leather platform sneakers with pink stripes.",
        "category": "sneakers",
        "price": Decimal("899.99"),
        "gender": "women",
        "campus": "ML Sultan Campus (Durban)",
        "quantity": 3,
        "images": ["C1.png"],
    },
]


def seed_sample_products():
    for item in SAMPLE_PRODUCTS:
        data = {k: v for k, v in item.items() if k != "images"}
        product = Product(**data)
        for position, name in enumerate(item["images"]):
            source = SEED_IMAGE_DIR / name
            if source.is_file():
                product.images.append(
                    ProductImage(filename=save_image(source), position=position)
                )
        db.session.add(product)
    db.session.commit()


def ensure_admin_from_env():
    """Create or promote the admin named by ADMIN_EMAIL / ADMIN_PASSWORD."""
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not email or not password:
        return
    user = User.query.filter_by(email=email).first()
    if user is None:
        user = User(
            email=email,
            name="Admin",
            surname="UniPro",
            gender="Prefer not to say",
            phone="0000000000",
            residence_address="-",
            campus=DUT_CAMPUSES[0],
        )
        user.set_password(password)
        db.session.add(user)
    user.is_admin = True
    db.session.commit()


def init_app_data():
    with app.app_context():
        db.create_all()
        ensure_admin_from_env()
        if os.environ.get("SEED_SAMPLE_DATA", "1") != "0" and Product.query.count() == 0:
            seed_sample_products()


@app.cli.command("create-admin")
@click.option("--email", prompt=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def create_admin_command(email, password):
    """Create an admin account, or promote an existing user to admin."""
    email = email.strip().lower()
    user = User.query.filter_by(email=email).first()
    if user is None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise click.ClickException(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )
        user = User(
            email=email,
            name="Admin",
            surname="UniPro",
            gender="Prefer not to say",
            phone="0000000000",
            residence_address="-",
            campus=DUT_CAMPUSES[0],
        )
        user.set_password(password)
        db.session.add(user)
        click.echo(f"Created admin {email}.")
    else:
        click.echo(f"Promoted {email} to admin (existing password kept).")
    user.is_admin = True
    db.session.commit()


init_app_data()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
