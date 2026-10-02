# UniPro Marketplace

A Flask web app for selling clothing and sneakers to students on
Durban University of Technology (DUT) campuses.

## Features

- **Shop home page** with an image slider for each item (multiple angles),
  category filters, stock status and campus badges.
- **User accounts**: students register with their email address and provide
  name, surname, gender, phone number, residence address, DUT campus
  (Steve Biko, Ritson, ML Sultan, City, Brickfield, Riverside, Indumiso),
  password and confirm password. Passwords are stored hashed.
- **Cart & orders**: anyone can add items to the cart; customers log in to
  place an order and choose the DUT campus where they'll collect it
  (payment on collection). Stock is reserved when the order is placed and
  returned if it is cancelled.
- **Customer dashboard** (`/account`): active-order tracking (Placed →
  Confirmed → Ready → Collected), order history with details, total spent,
  cart summary, editable profile and password change. Pending orders can be
  cancelled by the customer.
- **Admin dashboard** (`/admin`): revenue, open orders, customers and stock
  at a glance; orders by status, sales by collection campus, recent orders,
  stock alerts, best sellers and new customers.
  - **Orders**: filter by status, view customer contact details and update
    an order's status.
  - **Items**: add, edit and delete items, upload several photos per item and
    remove photos. Photos are auto-rotated, resized to max 1200px and
    converted to WebP so the home page loads quickly.
  - **Customers**: view registered users and their order counts, and grant or
    remove admin access.

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Create your admin account (prompts for email and password)
flask --app app create-admin

flask --app app run --debug
```

Open http://127.0.0.1:5000, log in with the admin account and go to **Admin**.

On first start the database (`instance/unipro.db`) is created and the sample
sneakers in `seed_images/` are added. Set `SEED_SAMPLE_DATA=0` to start with an
empty shop.

### Configuration (environment variables)

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Session signing key. If unset, one is generated in `instance/secret_key`. |
| `DATABASE_URL` | SQLAlchemy URL. Defaults to SQLite in `instance/`. |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Optional: create/promote this admin account on start-up. |
| `SEED_SAMPLE_DATA` | Set to `0` to skip adding the sample items. |

`flask --app app create-admin --email someone@example.com` also promotes an
existing user to admin.
