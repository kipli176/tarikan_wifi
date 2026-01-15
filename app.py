from flask import Flask, g, request, redirect, url_for, render_template_string, abort
import sqlite3
from datetime import date

app = Flask(__name__)
DB_PATH = "wifi.db"

# =========================
# Helpers (irit koding)
# =========================
def db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn:
        conn.close()

def exec1(sql, params=()):
    cur = db().execute(sql, params)
    db().commit()
    return cur

def query(sql, params=()):
    return db().execute(sql, params).fetchall()

def query_one(sql, params=()):
    return db().execute(sql, params).fetchone()

def today_ym():
    return date.today().strftime("%Y-%m")

def today_ymd():
    return date.today().strftime("%Y-%m-%d")

def money(n):
    try:
        n = int(n)
    except:
        n = 0
    return f"Rp{n:,}".replace(",", ".")

def init_db():
    db().executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS customers (
      id          TEXT PRIMARY KEY,
      name        TEXT NOT NULL,
      address     TEXT,
      monthly_fee INTEGER NOT NULL CHECK(monthly_fee >= 0),
      active      INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
    );

    CREATE TABLE IF NOT EXISTS cash_batches (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      period      TEXT NOT NULL,
      batch_date  TEXT NOT NULL,            -- YYYY-MM-DD
      collector   TEXT NOT NULL,
      count       INTEGER NOT NULL DEFAULT 0 CHECK(count >= 0),
      total_cash  INTEGER NOT NULL DEFAULT 0 CHECK(total_cash >= 0),
      status      TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','APPROVED')),
      approved_by TEXT,
      approved_at TEXT,
      created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS invoices (
      id            INTEGER PRIMARY KEY AUTOINCREMENT,
      period        TEXT NOT NULL,          -- YYYY-MM
      customer_id   TEXT NOT NULL,
      amount        INTEGER NOT NULL CHECK(amount >= 0),

      status        TEXT NOT NULL DEFAULT 'UNPAID' CHECK(status IN ('UNPAID','PAID')),
      method        TEXT CHECK(method IN ('CASH','TRANSFER')),
      paid_at       TEXT,
      collector     TEXT,

      cash_verified INTEGER NOT NULL DEFAULT 0 CHECK(cash_verified IN (0,1)),
      cash_batch_id INTEGER,
      locked        INTEGER NOT NULL DEFAULT 0 CHECK(locked IN (0,1)),

      created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

      FOREIGN KEY(customer_id) REFERENCES customers(id) ON UPDATE CASCADE ON DELETE RESTRICT,
      FOREIGN KEY(cash_batch_id) REFERENCES cash_batches(id) ON UPDATE CASCADE ON DELETE SET NULL,

      UNIQUE(period, customer_id)
    );

    CREATE INDEX IF NOT EXISTS idx_invoices_period_status ON invoices(period, status);
    CREATE INDEX IF NOT EXISTS idx_invoices_paid_at ON invoices(paid_at);
    CREATE INDEX IF NOT EXISTS idx_batches_period_date ON cash_batches(period, batch_date);
    """)

def seed_demo_if_empty():
    c = query_one("SELECT COUNT(*) AS n FROM customers")
    if c and c["n"] == 0:
        with db():
            for i in range(1, 101):
                cid = f"{i:03d}"
                db().execute(
                    "INSERT INTO customers(id,name,address,monthly_fee,active) VALUES (?,?,?,?,1)",
                    (cid, f"Pelanggan {cid}", "", 150000)
                )
        db().commit()

def ensure_invoices(period: str):
    exec1("""
      INSERT OR IGNORE INTO invoices(period, customer_id, amount)
      SELECT ?, c.id, c.monthly_fee
      FROM customers c
      WHERE c.active = 1
    """, (period,))

# =========================
# Templates (Tailwind)
# =========================
BASE_HEAD = """
<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <title>{{title}}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 text-slate-900">
<div class="min-h-screen">
"""

BASE_FOOT = """
</div>
</body>
</html>
"""

PETUGAS_HTML = BASE_HEAD + r"""
<style>
  /* minor: improve tap highlight on mobile */
  * { -webkit-tap-highlight-color: transparent; }
</style>

<div class="min-h-screen bg-slate-950 text-slate-100">
  <div class="mx-auto max-w-5xl">

    <!-- Top App Bar -->
    <header class="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/85 backdrop-blur">
      <div class="px-4 pt-4 pb-3">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <div class="text-xl font-black tracking-tight">📲 Penagihan</div>
              <span class="inline-flex items-center rounded-full bg-slate-900 px-2.5 py-1 text-xs font-black text-slate-200 border border-slate-800">
                📅 {{period}}
              </span>
            </div>
            <div class="mt-1 text-sm text-slate-300 truncate">
              👤 Petugas: <b class="font-extrabold text-slate-100">{{collector}}</b>
            </div>
          </div>

          <div class="flex items-center gap-2">
            <button id="autoPrintBtn"
              class="rounded-xl border border-slate-800 bg-slate-900 px-3 py-2 text-sm font-black text-slate-100 shadow-sm active:scale-[0.99]">
              🖨️ <span class="hidden sm:inline">Auto</span>
              <span id="apText" class="ml-1 rounded-lg bg-slate-100 px-2 py-1 text-xs text-slate-950 font-black">OFF</span>
            </button>

            <a class="rounded-xl bg-slate-100 px-3 py-2 text-sm font-black text-slate-950 shadow-sm active:scale-[0.99]"
               href="/">
              🏠 <span class="sm:inline">Home</span>
            </a>
          </div>
        </div>

        {% if msg %}
        <div class="mt-3 rounded-2xl border border-slate-800 bg-slate-900 p-3">
          <div class="flex items-start gap-2">
            <div class="mt-0.5">📣</div>
            <div class="font-extrabold leading-snug text-slate-50">{{msg}}</div>
          </div>
        </div>
        {% endif %}

        <!-- Search -->
        <form method="get" action="/" class="mt-3 flex gap-2">
          <input type="hidden" name="period" value="{{period}}">
          <input type="hidden" name="collector" value="{{collector}}">
          <input name="q" value="{{q}}" placeholder="🔎 Cari ID / Nama…"
            class="w-full rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3 text-base font-semibold text-slate-100 outline-none placeholder:text-slate-500 focus:border-slate-600">
          <button class="shrink-0 rounded-2xl bg-indigo-500 px-4 py-3 text-base font-black text-white shadow-sm active:scale-[0.99]">
            Cari
          </button>
        </form>

        <!-- Quick Summary -->
        <div class="mt-3 grid grid-cols-3 gap-2">
          <div class="rounded-2xl border border-slate-800 bg-slate-900 p-3">
            <div class="text-xs text-slate-400 font-semibold">🟠 Belum</div>
            <div class="mt-1 text-lg font-black">{{rows|length}}</div>
          </div>
          <div class="rounded-2xl border border-slate-800 bg-slate-900 p-3">
            <div class="text-xs text-slate-400 font-semibold">🟢 Hari ini</div>
            <div class="mt-1 text-lg font-black">{{marked_today|length}}</div>
          </div>
          <div class="rounded-2xl border border-slate-800 bg-slate-900 p-3">
            <div class="text-xs text-slate-400 font-semibold">🧺 CASH siap setor</div>
            <div class="mt-1 text-lg font-black">{{cash_today_count}}</div>
            <div class="text-xs text-slate-300 font-bold">{{cash_today_total}}</div>
          </div>
        </div>

        <!-- Tabs -->
        <nav class="mt-3 grid grid-cols-3 gap-2">
          <button type="button" onclick="showTab('tab-unpaid')"
            class="tabBtn rounded-2xl border border-slate-800 bg-slate-900 px-3 py-3 text-sm font-black active:scale-[0.99]"
            data-tab="tab-unpaid">🟠 Belum</button>
          <button type="button" onclick="showTab('tab-today')"
            class="tabBtn rounded-2xl border border-slate-800 bg-slate-900 px-3 py-3 text-sm font-black active:scale-[0.99]"
            data-tab="tab-today">🟢 Hari ini</button>
          <button type="button" onclick="showTab('tab-cash')"
            class="tabBtn rounded-2xl border border-slate-800 bg-slate-900 px-3 py-3 text-sm font-black active:scale-[0.99]"
            data-tab="tab-cash">🧺 Setoran</button>
        </nav>
      </div>
    </header>

    <main class="px-4 py-4 pb-28">

      <!-- TAB: BELUM -->
      <section id="tab-unpaid" class="tabPanel">
        <div class="rounded-2xl border border-slate-800 bg-slate-900 p-4">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="text-lg font-black">🟠 Belum Lunas</div>
              <div class="mt-1 text-sm text-slate-300">Tap pelanggan → pilih 💵 CASH atau 🏦 TRANSFER.</div>
            </div>
            <span class="rounded-full bg-slate-950 px-3 py-1 text-sm font-black text-slate-200 border border-slate-800">
              {{rows|length}} 👥
            </span>
          </div>

          <div class="mt-3 divide-y divide-slate-800">
            {% for r in rows %}
            <button type="button"
              onclick="openPayModal('{{r.id}}','{{r.name}}','{{r.amount_fmt}}')"
              class="w-full py-3 text-left active:scale-[0.999]">
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-3 min-w-0">
                  <div class="flex h-11 w-11 items-center justify-center rounded-2xl bg-slate-950 text-sm font-black text-slate-200 border border-slate-800">
                    {{ loop.index }}
                  </div>
                  <div class="min-w-0">
                    <div class="truncate text-base font-black text-slate-50">{{r.name}}</div>
                    <div class="truncate text-xs text-slate-400">{{r.address or "—"}}</div>
                  </div>
                </div>
                <div class="shrink-0 text-right">
                  <div class="text-base font-black text-slate-50">{{r.amount_fmt}}</div>
                  <div class="mt-1 inline-flex items-center rounded-full bg-indigo-500/15 px-2 py-0.5 text-xs font-bold text-indigo-200 border border-indigo-500/25">
                    👉 Tap untuk bayar
                  </div>
                </div>
              </div>
            </button>
            {% endfor %}

            {% if rows|length == 0 %}
            <div class="py-10 text-center">
              <div class="text-3xl">🎉</div>
              <div class="mt-2 text-base font-black">Tidak ada data</div>
              <div class="mt-1 text-sm text-slate-300">Semua lunas atau hasil pencarian kosong.</div>
              <a class="inline-flex mt-4 rounded-2xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm font-black text-slate-100"
                 href="/?period={{period}}&collector={{collector}}">♻️ Reset</a>
            </div>
            {% endif %}
          </div>
        </div>
      </section>

      <!-- TAB: HARI INI -->
      <section id="tab-today" class="tabPanel hidden">
        {# hitung total cash/transfer hari ini #}
        {% set ns = namespace(cash_cnt=0, cash_sum=0, tr_cnt=0, tr_sum=0) %}
        {% for m in marked_today %}
          {% if m.method == 'CASH' %}
            {% set ns.cash_cnt = ns.cash_cnt + 1 %}
            {% set ns.cash_sum = ns.cash_sum + (m.amount or 0) %}
          {% else %}
            {% set ns.tr_cnt = ns.tr_cnt + 1 %}
            {% set ns.tr_sum = ns.tr_sum + (m.amount or 0) %}
          {% endif %}
        {% endfor %}

        <div class="rounded-2xl border border-slate-800 bg-slate-900 p-4">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="text-lg font-black">🟢 Hari Ini</div>
              <div class="mt-1 text-sm text-slate-300">Ringkasan + daftar transaksi yang bisa di-print / dibatalkan.</div>
            </div>
            <span class="rounded-full bg-slate-950 px-3 py-1 text-sm font-black text-slate-200 border border-slate-800">
              {{marked_today|length}} 🧾
            </span>
          </div>

          <!-- Summary money (requested: total CASH) -->
          <div class="mt-4 grid grid-cols-3 gap-2">
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <div class="text-xs text-slate-400 font-semibold">💵 CASH</div>
              <div class="mt-1 text-base font-black text-amber-200">{{money(ns.cash_sum)}}</div>
              <div class="text-xs text-slate-400 font-bold">{{ns.cash_cnt}} transaksi</div>
            </div>
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <div class="text-xs text-slate-400 font-semibold">🏦 TRANSFER</div>
              <div class="mt-1 text-base font-black text-emerald-200">{{money(ns.tr_sum)}}</div>
              <div class="text-xs text-slate-400 font-bold">{{ns.tr_cnt}} transaksi</div>
            </div>
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <div class="text-xs text-slate-400 font-semibold">🧮 TOTAL</div>
              <div class="mt-1 text-base font-black text-slate-50">{{money(ns.cash_sum + ns.tr_sum)}}</div>
              <div class="text-xs text-slate-400 font-bold">{{ns.cash_cnt + ns.tr_cnt}} transaksi</div>
            </div>
          </div>

          <div class="mt-4 divide-y divide-slate-800">
            {% for m in marked_today %}
            <div class="py-3">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <div class="truncate text-base font-black text-slate-50">{{m.customer_id}} • {{m.name}}</div>
                  <div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-300">
                    <span class="rounded-full bg-slate-950 px-2 py-1 font-semibold border border-slate-800">⏱️ {{m.paid_at}}</span>
                    {% if m.method == 'CASH' %}
                      <span class="rounded-full bg-amber-500/15 px-2 py-1 font-black text-amber-200 border border-amber-500/25">💵 CASH</span>
                      {% if m.cash_batch_id %}
                        <span class="rounded-full bg-slate-950 px-2 py-1 font-semibold border border-slate-800">📤 Sudah kirim</span>
                      {% else %}
                        <span class="rounded-full bg-slate-950 px-2 py-1 font-semibold border border-slate-800">🧺 Belum kirim</span>
                      {% endif %}
                    {% else %}
                      <span class="rounded-full bg-emerald-500/15 px-2 py-1 font-black text-emerald-200 border border-emerald-500/25">🏦 TRANSFER</span>
                      <span class="rounded-full bg-slate-950 px-2 py-1 font-semibold border border-slate-800">✅ Auto valid</span>
                    {% endif %}
                  </div>
                </div>
                <div class="shrink-0 text-right">
                  <div class="text-base font-black text-slate-50">{{m.amount_fmt}}</div>
                </div>
              </div>

              <div class="mt-3 flex flex-wrap gap-2">
                <a class="inline-flex items-center justify-center gap-2 rounded-2xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm font-black text-slate-100 active:scale-[0.99]"
                   href="/receipt/{{m.id}}?back={{back_url | urlencode}}">
                  🧾 Print
                </a>

                {% if m.can_undo %}
                <form method="post" action="/undo" onsubmit="return confirm('Batalkan pembayaran ini?')">
                  <input type="hidden" name="period" value="{{period}}">
                  <input type="hidden" name="collector" value="{{collector}}">
                  <input type="hidden" name="invoice_id" value="{{m.id}}">
                  <button class="inline-flex items-center justify-center gap-2 rounded-2xl bg-rose-600 px-4 py-3 text-sm font-black text-white active:scale-[0.99]">
                    🧨 Batalkan
                  </button>
                </form>
                {% else %}
                <button class="inline-flex items-center justify-center gap-2 rounded-2xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm font-black text-slate-500" disabled>
                  🔒 Terkunci
                </button>
                {% endif %}
              </div>
            </div>
            {% endfor %}

            {% if marked_today|length == 0 %}
            <div class="py-10 text-center">
              <div class="text-3xl">🕊️</div>
              <div class="mt-2 text-base font-black">Belum ada transaksi hari ini</div>
              <div class="mt-1 text-sm text-slate-300">Mulai dari tab 🟠 Belum.</div>
            </div>
            {% endif %}
          </div>
        </div>
      </section>

      <!-- TAB: SETORAN -->
      <section id="tab-cash" class="tabPanel hidden">
        <div class="rounded-2xl border border-slate-800 bg-slate-900 p-4">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="text-lg font-black">🧺 Setoran CASH</div>
              <div class="mt-1 text-sm text-slate-300">
                Kirim / update tarikan CASH untuk diverifikasi admin.
              </div>
            </div>
            <span class="rounded-full bg-slate-950 px-3 py-1 text-xs font-black text-slate-200 border border-slate-800">
              📅 {{today}}
            </span>
          </div>

          <!-- Status banner (works if you pass these vars; safe if not) -->
          {% if cash_batch_approved_meta %}
            <div class="mt-4 rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-3">
              <div class="font-black text-emerald-200">✅ Setoran hari ini sudah APPROVED</div>
              <div class="mt-1 text-xs text-emerald-200/80">{{cash_batch_approved_meta}}</div>
              <div class="mt-1 text-xs text-slate-300">🔒 Tutup buku hari ini. Lanjut transaksi besok.</div>
            </div>
          {% elif cash_batch_pending_meta %}
            <div class="mt-4 rounded-2xl border border-amber-500/30 bg-amber-500/10 p-3">
              <div class="font-black text-amber-200">🟡 Masih PENDING — boleh update</div>
              <div class="mt-1 text-xs text-amber-200/80">{{cash_batch_pending_meta}}</div>
              <div class="mt-1 text-xs text-slate-300">➕ Jika ada CASH baru, tombol di bawah akan memasukkan & memperbarui total.</div>
            </div>
          {% else %}
            <div class="mt-4 rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <div class="font-black text-slate-50">🆕 Belum ada tarikan hari ini</div>
              <div class="mt-1 text-xs text-slate-300">Klik tombol untuk membuat tarikan (PENDING).</div>
            </div>
          {% endif %}

          <!-- Big number -->
          <div class="mt-4 rounded-2xl border border-slate-800 bg-slate-950 p-4">
            <div class="text-xs font-semibold text-slate-400">💵 CASH siap disetor (belum masuk batch)</div>
            <div class="mt-2 flex items-end justify-between gap-3">
              <div>
                <div class="text-3xl font-black text-slate-50">{{cash_today_count}}</div>
                <div class="text-sm font-bold text-slate-300">orang</div>
              </div>
              <div class="text-right">
                <div class="text-2xl font-black text-amber-200">{{cash_today_total}}</div>
                <div class="text-sm font-bold text-slate-300">total</div>
              </div>
            </div>
            <div class="mt-3 text-xs text-slate-400">
              🔐 Setelah dikirim, CASH terkunci menunggu verifikasi admin.
            </div>
          </div>

          <form method="post" action="/submit_cash_batch" class="mt-4"
                onsubmit="return confirm('Kirim / Update setoran CASH hari ini?')">
            <input type="hidden" name="period" value="{{period}}">
            <input type="hidden" name="collector" value="{{collector}}">
            <input type="hidden" name="batch_date" value="{{today}}">
            <button id="btnSubmitCash"
              class="w-full rounded-2xl bg-indigo-500 px-4 py-4 text-base sm:text-lg font-black text-white shadow-sm disabled:opacity-40 active:scale-[0.99]"
              {% if cash_today_count==0 %}disabled{% endif %}>
              🚀 KIRIM / UPDATE SETORAN
            </button>
          </form>

          {% if cash_today_count==0 %}
          <div class="mt-4 rounded-2xl border border-slate-800 bg-slate-950 p-4 text-sm text-slate-200">
            ✅ Tidak ada CASH yang perlu disetor saat ini.
          </div>
          {% endif %}
        </div>
      </section>

    </main>

    <!-- Bottom Navigation -->
    <nav class="fixed bottom-0 inset-x-0 z-40 border-t border-slate-800 bg-slate-950/90 backdrop-blur">
      <div class="mx-auto max-w-5xl px-4 py-2">
        <div class="grid grid-cols-3 gap-2">
          <button type="button" onclick="showTab('tab-unpaid')"
            class="tabNav rounded-2xl px-3 py-3 text-sm font-black active:scale-[0.99]" data-tab="tab-unpaid">
            🟠 Belum
            <div class="text-xs text-slate-400 font-bold">{{rows|length}}</div>
          </button>
          <button type="button" onclick="showTab('tab-today')"
            class="tabNav rounded-2xl px-3 py-3 text-sm font-black active:scale-[0.99]" data-tab="tab-today">
            🟢 Hari ini
            <div class="text-xs text-slate-400 font-bold">{{marked_today|length}}</div>
          </button>
          <button type="button" onclick="showTab('tab-cash')"
            class="tabNav rounded-2xl px-3 py-3 text-sm font-black active:scale-[0.99]" data-tab="tab-cash">
            🧺 Setoran
            <div class="text-xs text-slate-400 font-bold">{{cash_today_count}}</div>
          </button>
        </div>
      </div>
    </nav>

  </div>
</div>

<!-- Pay Modal (bottom sheet) -->
<div id="payModal" class="fixed inset-0 z-50 hidden">
  <div class="absolute inset-0 bg-black/60" onclick="closePayModal()"></div>

  <div class="absolute inset-x-0 bottom-0 mx-auto w-full max-w-lg rounded-t-3xl bg-slate-900 p-5 shadow-2xl border border-slate-800">
    <div class="flex items-start justify-between gap-3">
      <div>
        <div class="text-base font-black text-slate-50">✅ Pilih Metode Pembayaran</div>
        <div class="mt-1 text-sm text-slate-300">Sekali tap → langsung tersimpan.</div>
      </div>
      <button type="button" onclick="closePayModal()"
        class="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm font-black text-slate-100 active:scale-[0.99]">✖️</button>
    </div>

    <div class="mt-4 rounded-2xl bg-slate-950 p-4 border border-slate-800">
      <div class="text-xs text-slate-400 font-semibold">Pelanggan</div>
      <div class="mt-1 text-lg font-black text-slate-50" id="mName">-</div>
      <div class="mt-3 text-xs text-slate-400 font-semibold">Tagihan</div>
      <div class="mt-1 text-2xl font-black text-slate-50" id="mAmount">-</div>
    </div>

    <form id="payForm" method="post" action="/pay" class="mt-4 grid gap-3">
      <input type="hidden" name="period" value="{{period}}">
      <input type="hidden" name="collector" value="{{collector}}">
      <input type="hidden" name="customer_id" id="mCustomerId" value="">
      <input type="hidden" name="method" id="mMethod" value="">
      <input type="hidden" name="print" id="mPrint" value="0">

      <button type="button" onclick="submitPay('CASH')"
        class="w-full rounded-2xl bg-amber-500 px-4 py-4 text-lg font-black text-slate-950 shadow-sm active:scale-[0.99]">
        💵 BAYAR CASH
      </button>
      <button type="button" onclick="submitPay('TRANSFER')"
        class="w-full rounded-2xl bg-emerald-500 px-4 py-4 text-lg font-black text-slate-950 shadow-sm active:scale-[0.99]">
        🏦 BAYAR TRANSFER
      </button>
      <button type="button" onclick="closePayModal()"
        class="w-full rounded-2xl border border-slate-800 bg-slate-950 px-4 py-3 text-base font-black text-slate-100 active:scale-[0.99]">
        ↩️ Batal
      </button>
    </form>

    <div class="mt-3 text-xs text-slate-400">
      💡 Setelah bayar, cek tab 🟢 Hari ini. Kalau salah, pakai 🧨 Batalkan (sebelum setoran dikirim).
    </div>
  </div>
</div>

<script>
  // Auto print toggle
  const AP_KEY = "auto_print";
  const apText = document.getElementById("apText");
  function readAP(){ return (localStorage.getItem(AP_KEY) || "0") === "1"; }
  function setAP(v){ localStorage.setItem(AP_KEY, v ? "1" : "0"); }
  function syncAP(){ apText.textContent = readAP() ? "ON" : "OFF"; }
  syncAP();
  document.getElementById("autoPrintBtn").addEventListener("click", () => { setAP(!readAP()); syncAP(); });

  // Modal
  const modal = document.getElementById("payModal");
  const mName = document.getElementById("mName");
  const mAmount = document.getElementById("mAmount");
  const mCustomerId = document.getElementById("mCustomerId");
  const mMethod = document.getElementById("mMethod");
  const mPrint = document.getElementById("mPrint");
  const payForm = document.getElementById("payForm");

  function openPayModal(id, name, amount){
    mName.textContent = id + " • " + name;
    mAmount.textContent = amount;
    mCustomerId.value = id;
    mMethod.value = "";
    mPrint.value = readAP() ? "1" : "0";
    modal.classList.remove("hidden");
  }
  function closePayModal(){
    modal.classList.add("hidden");
    window.location.href = "{{back_url}}";
  }
  function submitPay(method){
    mMethod.value = method;
    payForm.submit();
  }

  // Tabs
  function setActiveButtons(id){
    document.querySelectorAll(".tabBtn").forEach(b => {
      const active = b.dataset.tab === id;
      b.classList.toggle("bg-indigo-500", active);
      b.classList.toggle("border-indigo-500/50", active);
      b.classList.toggle("text-white", active);

      b.classList.toggle("bg-slate-900", !active);
      b.classList.toggle("border-slate-800", !active);
      b.classList.toggle("text-slate-100", !active);
    });

    document.querySelectorAll(".tabNav").forEach(b => {
      const active = b.dataset.tab === id;
      b.classList.toggle("bg-indigo-500", active);
      b.classList.toggle("text-white", active);

      b.classList.toggle("bg-slate-950", !active);
      b.classList.toggle("text-slate-100", !active);
      b.classList.toggle("border", !active);
      b.classList.toggle("border-slate-800", !active);
    });
  }

  function showTab(id){
    document.querySelectorAll(".tabPanel").forEach(el => el.classList.add("hidden"));
    document.getElementById(id).classList.remove("hidden");
    setActiveButtons(id);
    window.scrollTo({top:0, behavior:"smooth"});
  }

  // ---- Default tab logic (fix: search must open BELUM) ----
  const hasQuery = {{ 1 if q else 0 }};
  const hasMsg = {{ 1 if msg else 0 }};
  // if search => always unpaid (as you requested)
  // if not search and msg indicates payment success => show today
  // else unpaid
  const msgText = "{{msg|e}}";
  const looksLikePaid = (msgText.includes("Berhasil") || msgText.includes("dicentang"));

  if (hasQuery) {
    showTab("tab-unpaid");
  } else if (hasMsg && looksLikePaid) {
    showTab("tab-today");
  } else {
    showTab("tab-unpaid");
  }

  // Escape close modal
  document.addEventListener("keydown", (e) => {
    if(e.key === "Escape" && !modal.classList.contains("hidden")) closePayModal();
  });
</script>
""" + BASE_FOOT

ADMIN_HTML = BASE_HEAD + r"""
<div class="min-h-screen bg-slate-950 text-slate-100">
  <div class="mx-auto max-w-5xl">

    <!-- Sticky Header -->
    <header class="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/85 backdrop-blur">
      <div class="px-4 pt-4 pb-3">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <div class="text-xl font-black tracking-tight">🛡️ Admin</div>
              <span class="inline-flex items-center rounded-full bg-slate-900 px-2.5 py-1 text-xs font-black text-slate-200 border border-slate-800">
                📅 {{period}}
              </span>
            </div>
            <div class="mt-1 text-sm text-slate-300">
              ✅ TRANSFER auto valid • 💵 CASH perlu approval per tarikan
            </div>
            <div class="mt-1 text-xs text-slate-400">
              👤 Admin: <b class="font-extrabold text-slate-200">{{admin_name}}</b>
            </div>
          </div>

          <a class="rounded-xl border border-slate-800 bg-slate-900 px-3 py-2 text-sm font-black text-slate-100 active:scale-[0.99]"
             href="/?period={{period}}">
            ↩️ Petugas
          </a>
        </div>

        {% if cash_date %}
        <div class="mt-3 rounded-2xl border border-slate-800 bg-slate-900 p-3">
          <div class="flex items-start gap-2">
            <div>📌</div>
            <div class="min-w-0">
              <div class="font-black text-slate-50">Detail tanggal: {{cash_date}}</div>
              <div class="mt-1 text-xs text-slate-300">Scroll ke bagian “Detail Tanggal” di bawah.</div>
            </div>
          </div>
        </div>
        {% endif %}
      </div>
    </header>

    <main class="px-4 py-4 pb-8">

      <!-- Summary Cards -->
      <section class="grid gap-3 lg:grid-cols-2">
        <div class="rounded-2xl border border-slate-800 bg-slate-900 p-4">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="text-lg font-black">📊 Ringkasan Bulan</div>
              <div class="mt-1 text-sm text-slate-300">Rekap pembayaran pada periode ini.</div>
            </div>
            <span class="rounded-full bg-slate-950 px-3 py-1 text-xs font-black text-slate-200 border border-slate-800">
              🧾 Rekap
            </span>
          </div>

          <div class="mt-4 grid grid-cols-2 gap-2">
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <div class="text-xs text-slate-400 font-semibold">🟠 Belum bayar</div>
              <div class="mt-1 text-2xl font-black text-slate-50">{{unpaid_count}}</div>
            </div>
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <div class="text-xs text-slate-400 font-semibold">💵 CASH approved</div>
              <div class="mt-1 text-sm font-black text-amber-200">{{cash_ok_count}} • {{cash_ok_total}}</div>
            </div>
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <div class="text-xs text-slate-400 font-semibold">🏦 TRANSFER</div>
              <div class="mt-1 text-sm font-black text-emerald-200">{{transfer_count}} • {{transfer_total}}</div>
            </div>
            <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
              <div class="text-xs text-slate-400 font-semibold">🧮 TOTAL masuk</div>
              <div class="mt-1 text-sm font-black text-slate-50">{{total_paid_count}} • {{total_paid}}</div>
            </div>
          </div>
        </div>

        <!-- Pending batch list -->
        <div class="rounded-2xl border border-slate-800 bg-slate-900 p-4">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="text-lg font-black">🟡 Tarikan CASH PENDING</div>
              <div class="mt-1 text-sm text-slate-300">Klik “Detail” untuk kroscek, lalu “Setujui”.</div>
            </div>
            <span class="rounded-full bg-slate-950 px-3 py-1 text-xs font-black text-slate-200 border border-slate-800">
              {{pending_batches|length}} pending
            </span>
          </div>

          <div class="mt-4 divide-y divide-slate-800">
            {% for b in pending_batches %}
            <div class="py-3">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <div class="text-base font-black text-slate-50">📅 {{b.batch_date}} • 👤 {{b.collector}}</div>
                  <div class="mt-1 text-sm font-bold text-slate-200">{{b.count}} org • <span class="text-amber-200">{{b.total_cash_fmt}}</span></div>
                  <div class="mt-1 text-xs text-slate-400">🧾 Tarikan #{{b.id}} • Status: <b class="text-amber-200">PENDING</b></div>
                </div>

                <div class="shrink-0 flex flex-col gap-2">
                  <a class="rounded-2xl border border-slate-800 bg-slate-950 px-4 py-2 text-sm font-black text-slate-100 text-center active:scale-[0.99]"
                     href="/admin?period={{period}}&batch={{b.id}}">
                    🔎 Detail
                  </a>

                  <form method="post" action="/admin/approve"
                        onsubmit="return confirm('Setujui tarikan ini?')">
                    <input type="hidden" name="period" value="{{period}}">
                    <input type="hidden" name="batch_id" value="{{b.id}}">
                    <input type="hidden" name="admin_name" value="{{admin_name}}">
                    <button class="w-full rounded-2xl bg-emerald-500 px-4 py-2 text-sm font-black text-slate-950 active:scale-[0.99]">
                      ✅ Setujui
                    </button>
                  </form>
                </div>
              </div>
            </div>
            {% endfor %}

            {% if pending_batches|length == 0 %}
            <div class="py-10 text-center">
              <div class="text-3xl">🟢</div>
              <div class="mt-2 text-base font-black">Tidak ada pending</div>
              <div class="mt-1 text-sm text-slate-300">Semua tarikan CASH sudah diproses.</div>
            </div>
            {% endif %}
          </div>
        </div>
      </section>

      <!-- Batch detail -->
      {% if batch_detail %}
      <section class="mt-4 rounded-2xl border border-slate-800 bg-slate-900 p-4">
        <div class="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div class="text-lg font-black">🧾 Detail Tarikan #{{batch_detail_id}}</div>
            <div class="mt-1 text-sm text-slate-300">Cek daftar pelanggan + nominal.</div>
          </div>
          <span class="rounded-2xl bg-slate-950 border border-slate-800 px-3 py-2 text-xs font-black text-slate-200">
            {{batch_detail_meta}}
          </span>
        </div>

        <!-- Mobile card list -->
        <div class="mt-4 grid gap-2 sm:hidden">
          {% for r in batch_detail %}
          <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="text-sm font-black text-slate-50">{{r.id}} • {{r.name}}</div>
                <div class="mt-1 text-xs text-slate-400">⏱️ {{r.paid_at}}</div>
              </div>
              <div class="shrink-0 text-right text-sm font-black text-amber-200">{{r.amount_fmt}}</div>
            </div>
          </div>
          {% endfor %}
        </div>

        <!-- Desktop table -->
        <div class="mt-4 hidden sm:block overflow-x-auto">
          <table class="min-w-full text-left">
            <thead>
              <tr class="text-xs text-slate-400">
                <th class="py-2 pr-4">ID</th>
                <th class="py-2 pr-4">Nama</th>
                <th class="py-2 pr-4">Nominal</th>
                <th class="py-2 pr-4">Waktu</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800">
              {% for r in batch_detail %}
              <tr class="text-sm">
                <td class="py-3 pr-4 font-black text-slate-50">{{r.id}}</td>
                <td class="py-3 pr-4 text-slate-200">{{r.name}}</td>
                <td class="py-3 pr-4 font-black text-amber-200">{{r.amount_fmt}}</td>
                <td class="py-3 pr-4 text-slate-300">{{r.paid_at}}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </section>
      {% endif %}

      <!-- Approved group by date -->
      <section class="mt-4 rounded-2xl border border-slate-800 bg-slate-900 p-4">
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="text-lg font-black">📅 Approved per Tanggal</div>
            <div class="mt-1 text-sm text-slate-300">Klik tanggal untuk melihat detail transaksi (CASH approved + TRANSFER).</div>
          </div>
          <span class="rounded-full bg-slate-950 px-3 py-1 text-xs font-black text-slate-200 border border-slate-800">
            {{cash_grouped|length}} hari
          </span>
        </div>

        <div class="mt-4 divide-y divide-slate-800">
          {% for g in cash_grouped %}
          <a class="block py-3 active:scale-[0.999]"
             href="/admin?period={{period}}&cash_date={{g.batch_date}}">
            <div class="flex items-center justify-between gap-3">
              <div class="font-black text-slate-50">📌 {{g.batch_date}}</div>
              <div class="text-sm font-black text-slate-200">{{g.jumlah}} org • <span class="text-amber-200">{{g.total_fmt}}</span></div>
            </div>
            <div class="mt-1 text-xs text-slate-400">➡️ Tap untuk detail tanggal</div>
          </a>
          {% endfor %}

          {% if cash_grouped|length == 0 %}
          <div class="py-10 text-center">
            <div class="text-3xl">🗂️</div>
            <div class="mt-2 text-base font-black">Belum ada approved</div>
            <div class="mt-1 text-sm text-slate-300">Tarikan CASH yang disetujui akan muncul di sini.</div>
          </div>
          {% endif %}
        </div>
      </section>

      <!-- Detail by date -->
      {% if cash_date_detail %}
      <section class="mt-4 rounded-2xl border border-slate-800 bg-slate-900 p-4">
        <div class="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div class="text-lg font-black">🧾 Detail Tanggal</div>
            <div class="mt-1 text-sm text-slate-300">CASH yang tampil di sini hanya yang <b>approved</b>.</div>
          </div>
          <span class="rounded-2xl bg-slate-950 border border-slate-800 px-3 py-2 text-xs font-black text-slate-200">
            {{cash_date_meta}}
          </span>
        </div>

        <!-- Mobile cards -->
        <div class="mt-4 grid gap-2 sm:hidden">
          {% for r in cash_date_detail %}
          <div class="rounded-2xl border border-slate-800 bg-slate-950 p-3">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="text-sm font-black text-slate-50">{{r.customer_id}} • {{r.name}}</div>
                <div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-300">
                  {% if r.method == 'CASH' %}
                    <span class="rounded-full bg-amber-500/15 px-2 py-1 font-black text-amber-200 border border-amber-500/25">💵 CASH</span>
                  {% else %}
                    <span class="rounded-full bg-emerald-500/15 px-2 py-1 font-black text-emerald-200 border border-emerald-500/25">🏦 TRANSFER</span>
                  {% endif %}
                  <span class="rounded-full bg-slate-900 px-2 py-1 font-semibold border border-slate-800">🧾 {% if r.batch_id %}#{{r.batch_id}}{% else %}-{% endif %}</span>
                  <span class="rounded-full bg-slate-900 px-2 py-1 font-semibold border border-slate-800">👤 {{r.collector or "-"}}</span>
                </div>
                <div class="mt-1 text-xs text-slate-400">⏱️ {{r.paid_at}}</div>
              </div>
              <div class="shrink-0 text-right text-sm font-black text-slate-50">{{r.amount_fmt}}</div>
            </div>
          </div>
          {% endfor %}
        </div>

        <!-- Desktop table -->
        <div class="mt-4 hidden sm:block overflow-x-auto">
          <table class="min-w-full text-left">
            <thead>
              <tr class="text-xs text-slate-400">
                <th class="py-2 pr-4">Metode</th>
                <th class="py-2 pr-4">Batch</th>
                <th class="py-2 pr-4">Petugas</th>
                <th class="py-2 pr-4">ID</th>
                <th class="py-2 pr-4">Nama</th>
                <th class="py-2 pr-4">Nominal</th>
                <th class="py-2 pr-4">Waktu</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800">
              {% for r in cash_date_detail %}
              <tr class="text-sm">
                <td class="py-3 pr-4">
                  {% if r.method == 'CASH' %}
                    <span class="inline-flex items-center rounded-full bg-amber-500/15 px-2 py-1 font-black text-amber-200 border border-amber-500/25">💵 CASH</span>
                  {% else %}
                    <span class="inline-flex items-center rounded-full bg-emerald-500/15 px-2 py-1 font-black text-emerald-200 border border-emerald-500/25">🏦 TRANSFER</span>
                  {% endif %}
                </td>
                <td class="py-3 pr-4 font-black text-slate-200">{% if r.batch_id %}#{{r.batch_id}}{% else %}-{% endif %}</td>
                <td class="py-3 pr-4 text-slate-200">{{r.collector or "-"}}</td>
                <td class="py-3 pr-4 font-black text-slate-50">{{r.customer_id}}</td>
                <td class="py-3 pr-4 text-slate-200">{{r.name}}</td>
                <td class="py-3 pr-4 font-black text-slate-50">{{r.amount_fmt}}</td>
                <td class="py-3 pr-4 text-slate-300">{{r.paid_at}}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </section>
      {% endif %}

    </main>
  </div>
</div>
""" + BASE_FOOT


RECEIPT_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Struk</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    @media print { body { width: 58mm; } }
    body { font-family: monospace; margin: 8px; }
    .c { text-align:center; }
    .b { font-weight:700; }
    hr { border:none; border-top:1px dashed #000; margin:8px 0; }
  </style>
</head>
<body>
  <div class="c b">WIFI BULANAN</div>
  <div class="c">PEMBAYARAN</div>
  <hr>
  Periode : {{inv.period}}<br>
  ID/Nama : {{cust.id}} - {{cust.name}}<br>
  Metode  : {{inv.method}}<br>
  Waktu   : {{inv.paid_at}}<br>
  Petugas : {{inv.collector or "-"}}<br>
  <hr>
  Total   : <span class="b">{{amount}}</span><br>
  <hr>
  <div class="c">Terima kasih</div>
  <script>
    // manual print: user klik print dari browser kalau perlu.
  </script>
</body>
</html>
"""

# =========================
# Setup
# =========================
@app.before_request
def setup():
    init_db()
    seed_demo_if_empty()

# =========================
# Routes: Petugas
# =========================
@app.get("/")
def petugas():
    period = request.args.get("period") or today_ym()
    collector = request.args.get("collector") or "Petugas"
    q = (request.args.get("q") or "").strip()
    msg = request.args.get("msg") or ""

    ensure_invoices(period)

    # ---------- UNPAID list ----------
    params = [period]
    sql = """
      SELECT c.id, c.name, c.address, i.amount
      FROM invoices i
      JOIN customers c ON c.id = i.customer_id
      WHERE i.period = ?
        AND i.status = 'UNPAID'
        AND c.active = 1
    """
    if q:
        like = f"%{q}%"
        sql += " AND (c.id LIKE ? OR c.name LIKE ?) "
        params.extend([like, like])
    sql += " ORDER BY c.id"

    rows = [dict(r) for r in query(sql, params)]
    for r in rows:
        r["amount_fmt"] = money(r["amount"])

    # ---------- Marked TODAY (localtime) ----------
    marked = query("""
      SELECT i.id, i.customer_id, c.name, i.amount, i.paid_at, i.method, i.cash_batch_id, i.locked
      FROM invoices i
      JOIN customers c ON c.id = i.customer_id
      WHERE i.period = ?
        AND i.status = 'PAID'
        AND i.collector = ?
        AND date(i.paid_at,'localtime') = date('now','localtime')
      ORDER BY i.paid_at DESC
    """, (period, collector))

    marked_today = []
    for m in marked:
        mm = dict(m)
        mm["amount_fmt"] = money(m["amount"])
        can_undo = (mm["locked"] == 0) and (
            (mm["method"] == "TRANSFER") or
            (mm["method"] == "CASH" and mm["cash_batch_id"] is None)
        )
        mm["can_undo"] = can_undo
        marked_today.append(mm)

    # ---------- CASH pending TODAY (for batch) localtime ----------
    cash_today = query_one("""
      SELECT COUNT(*) AS jumlah, COALESCE(SUM(amount),0) AS total
      FROM invoices
      WHERE period = ?
        AND method = 'CASH'
        AND status = 'PAID'
        AND cash_verified = 0
        AND cash_batch_id IS NULL
        AND collector = ?
        AND date(paid_at,'localtime') = date('now','localtime')
    """, (period, collector))
    cash_today_count = int(cash_today["jumlah"] or 0)
    cash_today_total = money(cash_today["total"] or 0)

    # ---------- Batch status TODAY (PENDING / APPROVED) ----------
    today = today_ymd()

    pending_batch = query_one("""
      SELECT id, count, total_cash
      FROM cash_batches
      WHERE period=? AND batch_date=? AND collector=? AND status='PENDING'
      ORDER BY id DESC
      LIMIT 1
    """, (period, today, collector))

    approved_batch = query_one("""
      SELECT id, count, total_cash
      FROM cash_batches
      WHERE period=? AND batch_date=? AND collector=? AND status='APPROVED'
      ORDER BY id DESC
      LIMIT 1
    """, (period, today, collector))

    cash_batch_pending_id = pending_batch["id"] if pending_batch else None
    cash_batch_pending_meta = None
    if pending_batch:
        cash_batch_pending_meta = f"🟡 PENDING • Tarikan #{pending_batch['id']} • {pending_batch['count']} org • {money(pending_batch['total_cash'])}"

    cash_batch_approved_id = approved_batch["id"] if approved_batch else None
    cash_batch_approved_meta = None
    if approved_batch:
        cash_batch_approved_meta = f"✅ APPROVED • Tarikan #{approved_batch['id']} • {approved_batch['count']} org • {money(approved_batch['total_cash'])}"

    back_url = f"/?period={period}&collector={collector}"

    return render_template_string(
        PETUGAS_HTML,
        title="Petugas",
        period=period,
        collector=collector,
        q=q,
        msg=msg,
        rows=rows,
        marked_today=marked_today,
        cash_today_count=cash_today_count,
        cash_today_total=cash_today_total,
        today=today,
        back_url=back_url,
        money=money,

        # tambahan untuk UX "Setoran" yang jelas
        cash_batch_pending_id=cash_batch_pending_id,
        cash_batch_pending_meta=cash_batch_pending_meta,
        cash_batch_approved_id=cash_batch_approved_id,
        cash_batch_approved_meta=cash_batch_approved_meta,
    )

@app.post("/pay")
def pay():
    period = request.form.get("period") or today_ym()
    collector = request.form.get("collector") or "Petugas"
    customer_id = request.form.get("customer_id")
    method = request.form.get("method")
    do_print = (request.form.get("print") or "0") == "1"

    if not customer_id or method not in ("CASH", "TRANSFER"):
        return redirect(url_for("petugas", period=period, collector=collector, msg="Gagal: data tidak lengkap."))

    ensure_invoices(period)

    # --- BLOK jika hari ini sudah di-APPROVE admin (tutup buku harian) ---
    today = today_ymd()  # YYYY-MM-DD (WIB dari helper kamu)
    approved = query_one("""
        SELECT id
        FROM cash_batches
        WHERE period=? AND batch_date=? AND collector=? AND status='APPROVED'
        LIMIT 1
    """, (period, today, collector))
    if approved:
        return redirect(url_for(
            "petugas",
            period=period,
            collector=collector,
            msg=f"Sudah APPROVED hari ini (Tarikan #{approved['id']}). Lanjut besok."
        ))

    # Catatan: TRANSFER tidak langsung locked agar bisa undo sebelum penutupan
    if method == "TRANSFER":
        cur = exec1("""
          UPDATE invoices
          SET status='PAID', method='TRANSFER', paid_at=datetime('now','localtime'),
              collector=?, cash_verified=1, locked=0, cash_batch_id=NULL
          WHERE period=? AND customer_id=? AND status='UNPAID' AND locked=0
        """, (collector, period, customer_id))
    else:
        cur = exec1("""
          UPDATE invoices
          SET status='PAID', method='CASH', paid_at=datetime('now','localtime'),
              collector=?, cash_verified=0, locked=0
          WHERE period=? AND customer_id=? AND status='UNPAID' AND locked=0
        """, (collector, period, customer_id))

    if cur.rowcount != 1:
        return redirect(url_for("petugas", period=period, collector=collector, msg="SUDAH LUNAS / TIDAK BISA."))

    if do_print:
        inv = query_one("SELECT id FROM invoices WHERE period=? AND customer_id=?", (period, customer_id))
        if inv:
            back = f"/?period={period}&collector={collector}"
            return redirect(url_for("receipt", invoice_id=inv["id"], back=back))

    return redirect(url_for("petugas", period=period, collector=collector, msg="Berhasil dicentang."))


@app.post("/undo")
def undo():
    period = request.form.get("period") or today_ym()
    collector = request.form.get("collector") or "Petugas"
    invoice_id = request.form.get("invoice_id")

    if not invoice_id:
        return redirect(url_for(
            "petugas", period=period, collector=collector,
            msg="Gagal: invoice tidak ada."
        ))

    cur = exec1("""
      UPDATE invoices
      SET status='UNPAID',
          method=NULL,
          paid_at=NULL,
          collector=NULL,
          cash_verified=0,
          cash_batch_id=NULL,
          locked=0
      WHERE id=?
        AND period=?
        AND status='PAID'
        AND locked=0
        AND date(paid_at,'localtime') = date('now','localtime')
        AND (
          method='TRANSFER'
          OR (method='CASH' AND cash_batch_id IS NULL)
        )
    """, (invoice_id, period))

    if cur.rowcount != 1:
        return redirect(url_for(
            "petugas", period=period, collector=collector,
            msg="Tidak bisa dibatalkan (mungkin sudah dikirim/terkunci)."
        ))

    return redirect(url_for(
        "petugas", period=period, collector=collector,
        msg="Pembayaran dibatalkan."
    ))

@app.post("/submit_cash_batch")
def submit_cash_batch():
    period = request.form.get("period") or today_ym()
    collector = request.form.get("collector") or "Petugas"
    batch_date = request.form.get("batch_date") or today_ymd()  # YYYY-MM-DD

    ensure_invoices(period)

    con = db()
    try:
        con.execute("BEGIN")

        # 1) Kalau sudah APPROVED di tanggal tsb, tidak boleh submit lagi (harus hari lain)
        approved = query_one("""
            SELECT id
            FROM cash_batches
            WHERE period=? AND batch_date=? AND collector=? AND status='APPROVED'
        """, (period, batch_date, collector))
        if approved:
            con.execute("ROLLBACK")
            return redirect(url_for(
                "petugas",
                period=period,
                collector=collector,
                msg=f"Setoran tanggal {batch_date} sudah APPROVED (Tarikan #{approved['id']}). Tidak bisa submit lagi, pilih hari lain."
            ))

        # 2) Cari batch PENDING (kalau ada, kita UPDATE batch itu, bukan blok)
        pending = query_one("""
            SELECT id
            FROM cash_batches
            WHERE period=? AND batch_date=? AND collector=? AND status='PENDING'
        """, (period, batch_date, collector))

        if pending:
            batch_id = pending["id"]

            # 2a) Masukkan CASH baru (yang belum punya cash_batch_id) ke batch pending ini
            con.execute("""
                UPDATE invoices
                SET cash_batch_id=?, locked=1
                WHERE period=?
                  AND method='CASH'
                  AND status='PAID'
                  AND cash_verified=0
                  AND cash_batch_id IS NULL
                  AND date(paid_at,'localtime') = date(?)
            """, (batch_id, period, batch_date))

            # 2b) Rehitung ulang count & total_cash dari isi batch (paling aman)
            sums = query_one("""
                SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS total
                FROM invoices
                WHERE cash_batch_id=?
            """, (batch_id,))
            n = int(sums["n"] or 0)
            total = int(sums["total"] or 0)

            # 2c) Update metadata batch
            con.execute("""
                UPDATE cash_batches
                SET count=?, total_cash=?
                WHERE id=? AND period=? AND status='PENDING'
            """, (n, total, batch_id, period))

            # (Opsional) Lock transfer hari itu juga (kalau kamu ingin “harian tidak berubah”)
            con.execute("""
                UPDATE invoices
                SET locked=1
                WHERE period=?
                  AND method='TRANSFER'
                  AND status='PAID'
                  AND locked=0
                  AND date(paid_at,'localtime') = date(?)
            """, (period, batch_date))

            con.commit()
            return redirect(url_for(
                "petugas",
                period=period,
                collector=collector,
                msg=f"Tarikan #{batch_id} masih PENDING dan sudah di-update. Total: {n} ({money(total)})."
            ))

        # 3) Kalau tidak ada PENDING, buat batch baru (PENDING)
        row = query_one("""
            SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS total
            FROM invoices
            WHERE period=?
              AND method='CASH'
              AND status='PAID'
              AND cash_verified=0
              AND cash_batch_id IS NULL
              AND date(paid_at,'localtime') = date(?)
        """, (period, batch_date))
        n = int(row["n"] or 0)
        total = int(row["total"] or 0)

        if n == 0:
            con.execute("ROLLBACK")
            return redirect(url_for(
                "petugas",
                period=period,
                collector=collector,
                msg="Tidak ada CASH untuk disetor."
            ))

        cur = con.execute("""
            INSERT INTO cash_batches (period, batch_date, collector, count, total_cash, status)
            VALUES (?, ?, ?, ?, ?, 'PENDING')
        """, (period, batch_date, collector, n, total))
        batch_id = cur.lastrowid

        # Attach + lock invoice CASH yang masuk batch baru
        con.execute("""
            UPDATE invoices
            SET cash_batch_id=?, locked=1
            WHERE period=?
              AND method='CASH'
              AND status='PAID'
              AND cash_verified=0
              AND cash_batch_id IS NULL
              AND date(paid_at,'localtime') = date(?)
        """, (batch_id, period, batch_date))

        # (Opsional) Lock transfer hari itu juga
        con.execute("""
            UPDATE invoices
            SET locked=1
            WHERE period=?
              AND method='TRANSFER'
              AND status='PAID'
              AND locked=0
              AND date(paid_at,'localtime') = date(?)
        """, (period, batch_date))

        con.commit()
        return redirect(url_for(
            "petugas",
            period=period,
            collector=collector,
            msg=f"Setoran CASH terkirim. Tarikan #{batch_id} dibuat (PENDING)."
        ))

    except Exception:
        con.rollback()
        raise


# =========================
# Routes: Admin
# =========================
@app.get("/admin")
def admin():
    period = request.args.get("period") or today_ym()
    admin_name = request.args.get("admin") or "Admin"

    ensure_invoices(period)

    # ---- init agar aman untuk template ----
    cash_date = request.args.get("cash_date")  # YYYY-MM-DD (opsional)
    cash_date_detail = None
    cash_date_meta = ""

    # ---- pending batches (CASH yang perlu disetujui) ----
    pending = query("""
      SELECT id, batch_date, collector, count, total_cash, status
      FROM cash_batches
      WHERE period=? AND status='PENDING'
      ORDER BY batch_date, id
    """, (period,))
    pending2 = []
    for b in pending:
        bb = dict(b)
        bb["total_cash_fmt"] = money(b["total_cash"])
        pending2.append(bb)

    # ---- ringkasan bulan ----
    unpaid = query_one(
        "SELECT COUNT(*) AS n FROM invoices WHERE period=? AND status='UNPAID'",
        (period,),
    )
    unpaid_count = int(unpaid["n"] or 0)

    cash_ok = query_one("""
      SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS total
      FROM invoices
      WHERE period=? AND status='PAID' AND method='CASH' AND cash_verified=1
    """, (period,))
    cash_ok_count = int(cash_ok["n"] or 0)
    cash_ok_total = money(cash_ok["total"] or 0)

    transfer = query_one("""
      SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS total
      FROM invoices
      WHERE period=? AND status='PAID' AND method='TRANSFER'
    """, (period,))
    transfer_count = int(transfer["n"] or 0)
    transfer_total = money(transfer["total"] or 0)

    total_paid_count = cash_ok_count + transfer_count
    total_paid = money((cash_ok["total"] or 0) + (transfer["total"] or 0))

    # ---- grouping CASH approved per tanggal ----
    grouped = query("""
      SELECT batch_date, SUM(count) AS jumlah, SUM(total_cash) AS total
      FROM cash_batches
      WHERE period=? AND status='APPROVED'
      GROUP BY batch_date
      ORDER BY batch_date
    """, (period,))
    grouped2 = []
    for g1 in grouped:
        gg = dict(g1)
        gg["total_fmt"] = money(g1["total"])
        grouped2.append(gg)

    # ---- detail batch (PENDING/APPROVED) by id ----
    batch_id = request.args.get("batch")
    batch_detail = None
    batch_meta = ""
    if batch_id:
        meta = query_one("SELECT * FROM cash_batches WHERE id=? AND period=?", (batch_id, period))
        if meta:
            batch_meta = f"{meta['batch_date']} • {meta['collector']} • {meta['count']} org • {money(meta['total_cash'])}"
            detail = query("""
              SELECT c.id, c.name, i.amount, i.paid_at
              FROM invoices i JOIN customers c ON c.id=i.customer_id
              WHERE i.cash_batch_id=?
              ORDER BY i.paid_at
            """, (batch_id,))
            bd = []
            for r in detail:
                rr = dict(r)
                rr["amount_fmt"] = money(r["amount"])
                bd.append(rr)
            batch_detail = bd

    # ---- detail transaksi per tanggal (CASH approved + TRANSFER) ----
    if cash_date:
        detail = query("""
        SELECT
            date(i.paid_at,'localtime') AS trx_date,
            cb.id AS batch_id,
            cb.collector,
            c.id AS customer_id,
            c.name,
            i.method,
            i.amount,
            i.paid_at
        FROM invoices i
        JOIN customers c ON c.id = i.customer_id
        LEFT JOIN cash_batches cb ON cb.id = i.cash_batch_id
        WHERE i.period = ?
          AND i.status = 'PAID'
          AND date(i.paid_at,'localtime') = date(?)
          AND (
            i.method = 'TRANSFER'
            OR (i.method = 'CASH' AND i.cash_verified = 1)
          )
        ORDER BY i.method DESC, cb.id, i.paid_at
        """, (period, cash_date))

        cd = []
        cash_cnt = cash_sum = 0
        tr_cnt = tr_sum = 0

        for r in detail:
            rr = dict(r)
            rr["amount_fmt"] = money(r["amount"])
            cd.append(rr)

            if rr["method"] == "CASH":
                cash_cnt += 1
                cash_sum += int(rr["amount"] or 0)
            else:
                tr_cnt += 1
                tr_sum += int(rr["amount"] or 0)

        cash_date_detail = cd
        cash_date_meta = (
            f"{cash_date} • CASH {cash_cnt} ({money(cash_sum)}) • "
            f"TRANSFER {tr_cnt} ({money(tr_sum)}) • "
            f"TOTAL {cash_cnt + tr_cnt} ({money(cash_sum + tr_sum)})"
        )

    return render_template_string(
        ADMIN_HTML,
        title="Admin",
        period=period,
        admin_name=admin_name,
        pending_batches=pending2,
        unpaid_count=unpaid_count,
        cash_ok_count=cash_ok_count,
        cash_ok_total=cash_ok_total,
        transfer_count=transfer_count,
        transfer_total=transfer_total,
        total_paid_count=total_paid_count,
        total_paid=total_paid,
        cash_grouped=grouped2,
        batch_detail=batch_detail,
        batch_detail_id=batch_id,
        batch_detail_meta=batch_meta,
        cash_date=cash_date,
        cash_date_detail=cash_date_detail,
        cash_date_meta=cash_date_meta,
    )



@app.post("/admin/approve")
def admin_approve():
    period = request.form.get("period") or today_ym()
    batch_id = request.form.get("batch_id")
    admin_name = request.form.get("admin_name") or "Admin"
    if not batch_id:
        return redirect(url_for("admin", period=period))

    con = db()
    try:
        con.execute("BEGIN;")
        con.execute("""
          UPDATE cash_batches
          SET status='APPROVED', approved_by=?, approved_at=datetime('now','localtime')
          WHERE id=? AND period=? AND status='PENDING'
        """, (admin_name, batch_id, period))

        # lock invoices in that batch (CASH)
        con.execute("""
          UPDATE invoices
          SET cash_verified=1, locked=1
          WHERE cash_batch_id=?
            AND method='CASH'
            AND status='PAID'
        """, (batch_id,))
        con.commit()
    except Exception:
        con.rollback()
        raise

    return redirect(url_for("admin", period=period))

@app.get("/receipt/<int:invoice_id>")
def receipt(invoice_id: int):
    inv = query_one("SELECT * FROM invoices WHERE id=?", (invoice_id,))
    if not inv:
        abort(404)
    cust = query_one("SELECT * FROM customers WHERE id=?", (inv["customer_id"],))
    if not cust:
        abort(404)

    return render_template_string(
        RECEIPT_HTML,
        inv=inv,
        cust=cust,
        amount=money(inv["amount"]),
    )

if __name__ == "__main__":
    # host 0.0.0.0 agar bisa diakses HP dalam 1 WiFi/LAN
    app.run(host="0.0.0.0", port=5500, debug=True)
