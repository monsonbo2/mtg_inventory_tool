# Inventory Tool

A small CLI application for generic inventory management in a local SQLite database.
Users create an inventory first, get a small set of default fields, add any extra fields they need, and then add items into that inventory.
The CLI also supports an active inventory, so everyday item entry does not require repeating the inventory name every time.
If a user adds an item that exactly matches an existing item in the same inventory, the tool merges the new entry by increasing the existing quantity.

## Core Model

Each inventory starts with these default fields:

- `name`
- `quantity`
- `price`
- `location`
- `notes`

Users can then add custom fields such as:

- `sku`
- `supplier`
- `serial_number`
- `expiration_date`

## Quick Start

Initialize the database:

```bash
python3 main.py init-db
```

Create an inventory:

```bash
python3 main.py create-inventory \
  --name office_supplies \
  --description "General office supply inventory"
```

The inventory you create becomes the active inventory automatically. You can also switch later with:

```bash
python3 main.py use-inventory --inventory office_supplies
python3 main.py current-inventory
```

List the fields in that inventory:

```bash
python3 main.py list-fields
```

Add a custom field:

```bash
python3 main.py add-field \
  --field-name sku \
  --field-type string
```

Add another custom field:

```bash
python3 main.py add-field \
  --field-name supplier \
  --field-type string
```

Add an item:

```bash
python3 main.py add-item \
  --value name="Printer Paper" \
  --value quantity=12 \
  --value price=6.99 \
  --value location="Shelf A" \
  --value notes="Letter size" \
  --value sku=PAPER-001 \
  --value supplier=Staples
```

List items:

```bash
python3 main.py list-items
```

Show a summary:

```bash
python3 main.py summary
```

Export to CSV:

```bash
python3 main.py export-csv --output exports/office_supplies.csv
```

## Notebook

The notebook expects the project virtual environment so it can import `pandas`.
It uses a separate demo database at `notebooks/demo_inventory.db`, so the example inserts do not modify your main `inventory.db`.

Launch it with:

```bash
bash scripts/open_notebook.sh
```

If you open the notebook from another tool such as VS Code, select the kernel named `Python (.venv inventory-tool2)`.
