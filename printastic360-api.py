"""Printastic 360 production API. Run behind an HTTPS reverse proxy."""
import hmac
import json
import logging
import os
from datetime import date
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS p360_products (
    sku text PRIMARY KEY, name text NOT NULL, supplier text NOT NULL,
    url text NOT NULL, cost numeric(12,2) NOT NULL CHECK (cost >= 0),
    stock integer NOT NULL CHECK (stock >= 0)
);
CREATE TABLE IF NOT EXISTS p360_work (
    reference text NOT NULL, sku text NOT NULL REFERENCES p360_products(sku),
    customer text NOT NULL, due date NOT NULL,
    quantity integer NOT NULL CHECK (quantity > 0), notes text NOT NULL,
    completed boolean NOT NULL DEFAULT false,
    PRIMARY KEY (reference, sku)
);
"""
ORIGIN = "https://printastic-al.github.io"


def required(data, key, limit=180):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Campo inválido: {key}")
    return value.strip()


def count(data, key, minimum):
    value = data.get(key)
    if type(value) is not int or not minimum <= value <= 1_000_000:
        raise ValueError(f"Quantidade inválida: {key}")
    return value


def product(data):
    url = required(data, "url", 2048)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Indica um link HTTPS do fornecedor.")
    cost = Decimal(required(data, "cost", 20).replace(",", "."))
    if not cost.is_finite() or not 0 <= cost <= Decimal("9999999999.99") or cost != round(cost, 2):
        raise ValueError("Indica um custo válido com até duas casas decimais.")
    return (
        required(data, "sku"), required(data, "name"), required(data, "supplier"),
        url, cost, count(data, "stock", 0),
    )


def work(data):
    notes = data.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 1500:
        raise ValueError("Notas inválidas.")
    return (
        required(data, "reference"), required(data, "sku"), required(data, "customer"),
        date.fromisoformat(required(data, "due", 10)), count(data, "quantity", 1), notes.strip(),
    )


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, data=None):
        body = b"" if data is None else json.dumps(data, default=str).encode()
        self.send_response(status)
        if self.headers.get("Origin") == ORIGIN:
            self.send_header("Access-Control-Allow-Origin", ORIGIN)
        self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        if self.headers.get("Origin") == ORIGIN:
            self.send_header("Access-Control-Allow-Origin", ORIGIN)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def authorized(self):
        actual = self.headers.get("Authorization", "").encode()
        expected = ("Bearer " + os.environ["P360_TOKEN"]).encode()
        if hmac.compare_digest(actual, expected):
            return True
        self.reply(401, {"error": "Chave de acesso inválida."})
        return False

    def do_GET(self):
        if self.path != "/production":
            self.reply(404, {"error": "Página inexistente."})
            return
        if not self.authorized():
            return
        try:
            with psycopg.connect(os.environ["P360_DATABASE_URL"], row_factory=dict_row) as conn:
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                products = conn.execute("SELECT * FROM p360_products ORDER BY name, sku").fetchall()
                orders = conn.execute("SELECT * FROM p360_work WHERE NOT completed ORDER BY due, reference, sku").fetchall()
            self.reply(200, {"products": products, "orders": orders})
        except psycopg.Error:
            logging.exception("Production read failed")
            self.reply(503, {"error": "Base de dados temporariamente indisponível."})

    def do_POST(self):
        if not self.authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                raise ValueError("Pedido vazio ou demasiado grande.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Formato inválido.")
            with psycopg.connect(os.environ["P360_DATABASE_URL"]) as conn:
                if self.path == "/production/products":
                    conn.execute("""
                        INSERT INTO p360_products VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (sku) DO UPDATE SET name=excluded.name, supplier=excluded.supplier,
                        url=excluded.url, cost=excluded.cost, stock=excluded.stock
                    """, product(data))
                elif self.path == "/production/orders":
                    conn.execute("""
                        INSERT INTO p360_work (reference, sku, customer, due, quantity, notes) VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (reference,sku) DO UPDATE SET customer=excluded.customer,
                        due=excluded.due, quantity=excluded.quantity, notes=excluded.notes
                        WHERE NOT p360_work.completed
                    """, work(data))
                elif self.path == "/production/close":
                    conn.execute("""
                        WITH finished AS (
                            UPDATE p360_work SET completed=true
                            WHERE reference=%s AND sku=%s AND NOT completed
                            RETURNING sku, quantity
                        )
                        UPDATE p360_products AS product
                        SET stock=GREATEST(0, product.stock - finished.quantity)
                        FROM finished WHERE product.sku=finished.sku
                    """, (required(data, "reference"), required(data, "sku")))
                else:
                    self.reply(404, {"error": "Página inexistente."})
                    return
            self.reply(200, {"ok": True})
        except (ValueError, InvalidOperation) as exc:
            self.reply(400, {"error": str(exc)})
        except psycopg.errors.ForeignKeyViolation:
            self.reply(400, {"error": "Regista primeiro a referência do produto."})
        except psycopg.Error:
            logging.exception("Production write failed")
            self.reply(503, {"error": "Base de dados temporariamente indisponível."})


if __name__ == "__main__":
    if len(os.environ["P360_TOKEN"]) < 32:
        raise SystemExit("P360_TOKEN tem de ter pelo menos 32 caracteres.")
    with psycopg.connect(os.environ["P360_DATABASE_URL"]) as conn:
        conn.execute(SCHEMA)
    ThreadingHTTPServer(("127.0.0.1", 8310), Handler).serve_forever()
