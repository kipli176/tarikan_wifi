import sqlite3
import requests
from requests.auth import HTTPBasicAuth

ROUTER_BASE_URL = "https://localhost/"   # ganti
ROUTER_USER = "admin"                 # ganti
ROUTER_PASS = "rahasi"              # ganti
SQLITE_DB_PATH = "wifi.db"       # ganti bila perlu

VERIFY_TLS = False  # True kalau sertifikat valid, False kalau self-signed (testing)

DEFAULT_ADDRESS = "winduaji"
DEFAULT_MONTHLY_FEE = 150000


def fetch_ppp_active_names() -> set[str]:
    """
    Ambil username PPP yang sedang aktif dari RouterOS v7 REST API.
    """
    url = f"{ROUTER_BASE_URL}/rest/ppp/active"
    params = {".proplist": "name"}  # kita cuma butuh name

    r = requests.get(
        url,
        params=params,
        auth=HTTPBasicAuth(ROUTER_USER, ROUTER_PASS),
        verify=VERIFY_TLS,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError(f"Unexpected JSON type: {type(data)}")

    names = set()
    for row in data:
        name = (row.get("name") or "").strip()
        if name:
            names.add(name)
    return names


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS customers (
      id          TEXT PRIMARY KEY,
      name        TEXT NOT NULL,
      address     TEXT,
      monthly_fee INTEGER NOT NULL CHECK(monthly_fee >= 0),
      active      INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
    )
    """)
    # cegah duplikat berdasarkan name
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_customers_name ON customers(name)")
    conn.commit()


def get_next_id(conn: sqlite3.Connection) -> int:
    """
    Karena id bertipe TEXT, kita cast ke integer untuk cari max.
    Jika tabel kosong -> 1
    """
    cur = conn.execute("SELECT COALESCE(MAX(CAST(id AS INTEGER)), 0) FROM customers")
    max_id = cur.fetchone()[0]
    return int(max_id) + 1


def sync_active_to_customers(active_names: set[str]) -> None:
    conn = sqlite3.connect(SQLITE_DB_PATH)
    try:
        ensure_schema(conn)
        conn.execute("BEGIN")

        # 1) set semua offline dulu
        conn.execute("UPDATE customers SET active=0")

        # 2) ambil mapping name -> id yang sudah ada
        cur = conn.execute("SELECT id, name FROM customers")
        existing = {name: cid for (cid, name) in cur.fetchall()}

        next_id = get_next_id(conn)

        # 3) update/insert untuk yang online
        for name in active_names:
            if name in existing:
                conn.execute("UPDATE customers SET active=1 WHERE name=?", (name,))
            else:
                # insert baru dengan id urut, address default, monthly_fee default
                conn.execute(
                    """
                    INSERT INTO customers (id, name, address, monthly_fee, active)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (str(next_id), name, DEFAULT_ADDRESS, DEFAULT_MONTHLY_FEE),
                )
                next_id += 1

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    active_names = fetch_ppp_active_names()
    print(f"PPP active users: {len(active_names)}")

    sync_active_to_customers(active_names)
    print("Sync selesai. address default, id urut, active ter-update.")


if __name__ == "__main__":
    main()