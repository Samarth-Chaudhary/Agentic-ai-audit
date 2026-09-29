"""Olist Brazilian E-Commerce dataset loader and query engine.

Reads authentic transaction, order, item, payment, and product category records
from the real Olist dataset (CC BY-NC-SA 4.0 / Public Domain).
Stores and indexes rows in SQLite (`data/olist/olist.db`) for high-performance,
fully reproducible offline queries and tests.
"""

from __future__ import annotations

import csv
import io
import sqlite3
import urllib.request
from pathlib import Path
from typing import Any

from project.logging import get_logger

logger = get_logger(__name__, component="olist_loader")

# Official Olist public repository endpoints for seeding/verification
OLIST_BASE_URL = "https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets"


class OlistDataLoader:
    """Manages queries and loading for authentic Olist e-commerce dataset records."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or Path(__file__).resolve().parent.parent.parent / "data" / "olist" / "olist.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            self.seed_from_source(max_orders=2000)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        """Fetch a single order by its authentic 32-character hexadecimal ID."""
        clean_id = order_id.strip().lower()
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT order_id, customer_id, order_status,
                       order_purchase_timestamp, order_approved_at,
                       order_delivered_carrier_date, order_delivered_customer_date,
                       order_estimated_delivery_date
                FROM orders
                WHERE order_id = ?
                """,
                (clean_id,),
            )
            order_row = cur.fetchone()
            if not order_row:
                return None

            # Fetch payments
            cur.execute(
                """
                SELECT payment_sequential, payment_type, payment_installments, payment_value
                FROM order_payments
                WHERE order_id = ?
                ORDER BY payment_sequential ASC
                """,
                (clean_id,),
            )
            payments = [
                {
                    "sequential": int(p["payment_sequential"]),
                    "type": p["payment_type"],
                    "installments": int(p["payment_installments"]),
                    "value": round(float(p["payment_value"]), 2),
                }
                for p in cur.fetchall()
            ]

            # Fetch items with category translations
            cur.execute(
                """
                SELECT oi.order_item_id, oi.product_id, oi.price, oi.freight_value,
                       p.product_category_name,
                       COALESCE(ct.product_category_name_english, p.product_category_name) as category_english
                FROM order_items oi
                LEFT JOIN products p ON oi.product_id = p.product_id
                LEFT JOIN category_translation ct ON p.product_category_name = ct.product_category_name
                WHERE oi.order_id = ?
                ORDER BY oi.order_item_id ASC
                """,
                (clean_id,),
            )
            items = [
                {
                    "item_id": int(i["order_item_id"]),
                    "product_id": i["product_id"],
                    "price": round(float(i["price"]), 2),
                    "freight": round(float(i["freight_value"]), 2),
                    "category": i["category_english"] or "general_merchandise",
                    "category_pt": i["product_category_name"] or "",
                }
                for i in cur.fetchall()
            ]

        total_payment = sum(p["value"] for p in payments)
        if not total_payment and items:
            total_payment = sum(i["price"] + i["freight"] for i in items)

        status_raw = (order_row["order_status"] or "").lower()
        status_norm = status_raw.upper()

        # Business logic for refunds:
        # DELIVERED orders are eligible for return/refund
        # SHIPPED / INVOICED / PROCESSING are in-transit and ineligible until delivery
        # CANCELED orders cannot be refunded
        refund_eligible = status_raw == "delivered"
        refundable_amount = round(total_payment, 2) if refund_eligible else 0.0

        return {
            "order_id": order_row["order_id"],
            "customer_id": order_row["customer_id"],
            "status": status_norm,
            "purchase_date": order_row["order_purchase_timestamp"],
            "delivery_date": order_row["order_delivered_customer_date"],
            "estimated_delivery_date": order_row["order_estimated_delivery_date"],
            "order_total": round(total_payment, 2),
            "currency": "BRL",
            "refund_eligible": refund_eligible,
            "refundable_amount": refundable_amount,
            "items": items,
            "payments": payments,
            "data_source": "olist_ecommerce_dataset",
            "is_synthetic": False,
        }

    def list_orders(self, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
        """List real orders matching an optional status filter."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            if status:
                cur.execute(
                    "SELECT order_id FROM orders WHERE LOWER(order_status) = ? LIMIT ?",
                    (status.strip().lower(), limit),
                )
            else:
                cur.execute("SELECT order_id FROM orders LIMIT ?", (limit,))
            rows = cur.fetchall()

        results: list[dict[str, Any]] = []
        for r in rows:
            order = self.get_order(r["order_id"])
            if order:
                results.append(order)
        return results

    def seed_from_source(self, max_orders: int = 5000) -> None:
        """Download raw CSVs from official Olist GitHub repo and populate SQLite database."""
        logger.info(f"Seeding Olist database at {self.db_path} from {OLIST_BASE_URL}...")
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                customer_id TEXT,
                order_status TEXT,
                order_purchase_timestamp TEXT,
                order_approved_at TEXT,
                order_delivered_carrier_date TEXT,
                order_delivered_customer_date TEXT,
                order_estimated_delivery_date TEXT
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS order_items (
                order_id TEXT,
                order_item_id INTEGER,
                product_id TEXT,
                seller_id TEXT,
                shipping_limit_date TEXT,
                price REAL,
                freight_value REAL
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS order_payments (
                order_id TEXT,
                payment_sequential INTEGER,
                payment_type TEXT,
                payment_installments INTEGER,
                payment_value REAL
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS category_translation (
                product_category_name TEXT PRIMARY KEY,
                product_category_name_english TEXT
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS products (
                product_id TEXT PRIMARY KEY,
                product_category_name TEXT,
                product_weight_g REAL
            )""")

            # Translations
            try:
                url_cat = f"{OLIST_BASE_URL}/product_category_name_translation.csv"
                req = urllib.request.Request(url_cat, headers={"User-Agent": "Mozilla/5.0"})
                raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8-sig", errors="ignore")
                reader = csv.DictReader(io.StringIO(raw))
                trans = [(r["product_category_name"], r["product_category_name_english"]) for r in reader if "product_category_name" in r]
                cur.executemany("INSERT OR REPLACE INTO category_translation VALUES (?, ?)", trans)
            except Exception as e:
                logger.warning(f"Could not load category translations: {e}")

            # Orders
            order_ids: set[str] = set()
            try:
                url_orders = f"{OLIST_BASE_URL}/olist_orders_dataset.csv"
                req = urllib.request.Request(url_orders, headers={"User-Agent": "Mozilla/5.0"})
                raw_orders = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="ignore")
                reader_orders = csv.DictReader(io.StringIO(raw_orders))
                order_rows = []
                for i, r in enumerate(reader_orders):
                    if i >= max_orders:
                        break
                    oid = r["order_id"]
                    order_ids.add(oid)
                    order_rows.append((
                        oid,
                        r.get("customer_id", ""),
                        r.get("order_status", ""),
                        r.get("order_purchase_timestamp", ""),
                        r.get("order_approved_at", ""),
                        r.get("order_delivered_carrier_date", ""),
                        r.get("order_delivered_customer_date", ""),
                        r.get("order_estimated_delivery_date", ""),
                    ))
                cur.executemany("INSERT OR REPLACE INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", order_rows)
            except Exception as e:
                logger.warning(f"Could not load orders: {e}")

            # Payments
            try:
                url_payments = f"{OLIST_BASE_URL}/olist_order_payments_dataset.csv"
                raw_payments = urllib.request.urlopen(urllib.request.Request(url_payments, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode("utf-8", errors="ignore")
                reader_payments = csv.DictReader(io.StringIO(raw_payments))
                payment_rows = [
                    (
                        r["order_id"],
                        int(r.get("payment_sequential", 1)),
                        r.get("payment_type", ""),
                        int(r.get("payment_installments", 1)),
                        float(r.get("payment_value", 0.0)),
                    )
                    for r in reader_payments
                    if r["order_id"] in order_ids
                ]
                cur.executemany("INSERT INTO order_payments VALUES (?, ?, ?, ?, ?)", payment_rows)
            except Exception as e:
                logger.warning(f"Could not load payments: {e}")

            # Items
            product_ids: set[str] = set()
            try:
                url_items = f"{OLIST_BASE_URL}/olist_order_items_dataset.csv"
                raw_items = urllib.request.urlopen(urllib.request.Request(url_items, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode("utf-8", errors="ignore")
                reader_items = csv.DictReader(io.StringIO(raw_items))
                item_rows = []
                for r in reader_items:
                    if r["order_id"] in order_ids:
                        product_ids.add(r["product_id"])
                        item_rows.append((
                            r["order_id"],
                            int(r.get("order_item_id", 1)),
                            r["product_id"],
                            r.get("seller_id", ""),
                            r.get("shipping_limit_date", ""),
                            float(r.get("price", 0.0)),
                            float(r.get("freight_value", 0.0)),
                        ))
                cur.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?, ?, ?)", item_rows)
            except Exception as e:
                logger.warning(f"Could not load items: {e}")

            # Products
            try:
                url_products = f"{OLIST_BASE_URL}/olist_products_dataset.csv"
                raw_products = urllib.request.urlopen(urllib.request.Request(url_products, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode("utf-8", errors="ignore")
                reader_products = csv.DictReader(io.StringIO(raw_products))
                product_rows = [
                    (
                        r["product_id"],
                        r.get("product_category_name", ""),
                        float(r.get("product_weight_g") or 0.0),
                    )
                    for r in reader_products
                    if r["product_id"] in product_ids
                ]
                cur.executemany("INSERT OR REPLACE INTO products VALUES (?, ?, ?)", product_rows)
            except Exception as e:
                logger.warning(f"Could not load products: {e}")

            # Indices
            cur.execute("CREATE INDEX IF NOT EXISTS idx_order_items_oid ON order_items (order_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_order_payments_oid ON order_payments (order_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_products_pid ON products (product_id)")
            conn.commit()
            logger.info("Olist database seeded successfully.")
