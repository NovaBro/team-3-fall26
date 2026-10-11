# Team Project repo

NYC food / open-data search project. Raw datasets live in `database/datasets/`.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_datasets   # loads CSVs/JSON into database/nyc_food.db
.venv/bin/python manage.py runserver
```

Then open http://127.0.0.1:8000/.

## Web interface

- `/` — search restaurant inspections by name, borough, ZIP, or grade.
- `/restaurant/<camis>/` — full inspection/violation history for one restaurant.
- `/explore/` — browse the other five datasets with text search and pagination.

## Data

The SQLite database (`database/nyc_food.db`) is generated, not committed. Rebuild it
any time with `import_datasets`; the command is idempotent.

| Dataset | Imported as |
|---|---|
| `restaurant_data_set_2_*.csv` | `RestaurantInspection` |
| `DOHMH_MenuStat_(Historical)_*.csv` | `MenuItem` |
| `Good_Food_Purchasing_Data_*.csv` | `AgencyPurchase` |
| `NYC_Farmers_Markets_*.csv` | `FarmersMarket` |
| `Recognized_Shop_Healthy_Stores_*.csv` | `HealthyStore` |
| `DPR_Eateries_001.json` | `ParkEatery` |

## Tests

```bash
.venv/bin/python manage.py test
```
