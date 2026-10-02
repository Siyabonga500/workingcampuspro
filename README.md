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
- **Admin area** (`/admin`): admins can add, edit and delete items, upload
  several photos per item, remove photos, view registered users and grant or
  remove admin access. Uploaded photos are auto-rotated, resized to max
  1200px and converted to WebP so the home page loads quickly.

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
