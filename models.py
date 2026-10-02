from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

DUT_CAMPUSES = [
    "Steve Biko Campus (Durban)",
    "Ritson Campus (Durban)",
    "ML Sultan Campus (Durban)",
    "City Campus (Durban)",
    "Brickfield Campus (Durban)",
    "Riverside Campus (Pietermaritzburg)",
    "Indumiso Campus (Pietermaritzburg)",
]

GENDERS = ["Male", "Female", "Other", "Prefer not to say"]

CATEGORIES = {
    "sneakers": "Sneakers",
    "tshirt": "T-Shirts",
    "trousers": "Trousers",
    "hoodie": "Hoodies",
    "jacket": "Jackets",
    "accessories": "Accessories",
}

PRODUCT_GENDERS = {"men": "Men", "women": "Women", "unisex": "Unisex"}

LOW_STOCK_THRESHOLD = 3


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    surname = db.Column(db.String(80), nullable=False)
    gender = db.Column(db.String(30), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    residence_address = db.Column(db.String(255), nullable=False)
    campus = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def full_name(self):
        return f"{self.name} {self.surname}"


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, default="")
    category = db.Column(db.String(30), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    gender = db.Column(db.String(10), nullable=False, default="unisex")
    campus = db.Column(db.String(80), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    images = db.relationship(
        "ProductImage",
        backref="product",
        order_by="ProductImage.position",
        cascade="all, delete-orphan",
    )

    @property
    def status(self):
        if self.quantity <= 0:
            return "out-of-stock"
        if self.quantity <= LOW_STOCK_THRESHOLD:
            return "low-stock"
        return "in-stock"

    @property
    def status_label(self):
        return {
            "in-stock": "In Stock",
            "low-stock": "Low Stock",
            "out-of-stock": "Out of Stock",
        }[self.status]

    @property
    def category_label(self):
        return CATEGORIES.get(self.category, self.category.title())

    @property
    def gender_label(self):
        return PRODUCT_GENDERS.get(self.gender, self.gender.title())


class ProductImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)


ORDER_STATUSES = {
    "pending": "Pending",
    "confirmed": "Confirmed",
    "ready": "Ready for collection",
    "completed": "Completed",
    "cancelled": "Cancelled",
}

OPEN_ORDER_STATUSES = ("pending", "confirmed", "ready")


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    collection_campus = db.Column(db.String(80), nullable=False)
    notes = db.Column(db.Text, default="")
    total = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    user = db.relationship("User", backref=db.backref("orders", lazy="dynamic"))
    items = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan")

    @property
    def reference(self):
        return f"UP{self.id:05d}"

    @property
    def status_label(self):
        return ORDER_STATUSES.get(self.status, self.status.title())

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items)

    @property
    def can_cancel(self):
        return self.status == "pending"


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    # Kept nullable so orders survive when an admin deletes the product.
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True)
    product_name = db.Column(db.String(120), nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    product = db.relationship("Product")

    @property
    def line_total(self):
        return self.unit_price * self.quantity
