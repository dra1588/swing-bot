"""Append-only paper-trading fills ledger and P&L computed only from it.

The same file is copied into each trading repo (no cross-repo imports). Keep the
copies identical; LEDGER_VERSION identifies the revision.

- One row per fill. Rows can never be updated or deleted (database triggers
  refuse it); a correction is a new row with correction_of set.
- fill_id is unique, so a retried write can never create a duplicate.
- `price` is the effective fill price including any modelled costs; `cost` and
  `fee` hold explicit costs not already in the price. `bid`/`ask` record the
  quote seen at the time, when known.
- A sell (or mark) at 3x or more, or a third or less, of the position's average
  cost records a suspect_corporate_action row; P&L excludes that position until
  a "reviewed" correction row clears it. The ledger never guesses a split ratio.
  Prediction markets (prices are probabilities, 5x moves are normal) pass
  corporate_actions=False to switch this off.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

LEDGER_VERSION = "1"
SUSPECT_RATIO = 3.0
COLUMNS = ("fill_id", "bot", "book", "position_id", "symbol", "side", "qty", "price",
           "bid", "ask", "cost", "fee", "ts", "reason", "source", "signal_key",
           "paper", "correction_of", "backfilled", "flags")
SIDES = ("BUY", "SELL", "FLAG")


def utc_iso(value=None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def storage_warning(path, volume_env="RAILWAY_VOLUME_MOUNT_PATH"):
    """A message if `path` is not inside the mounted Railway volume (history lost on redeploy)."""
    volume = os.environ.get(volume_env)
    absolute = os.path.abspath(str(path))
    if not volume:
        return f"no {volume_env}: {absolute} is not on a persistent volume"
    if not absolute.startswith(os.path.abspath(volume) + os.sep):
        return f"{absolute} is outside the volume {volume}; it is lost on redeploy"
    return None


class FillsLedger:
    def __init__(self, path, bot, corporate_actions=True):
        self.path = str(path)
        self.bot = bot
        self.corporate_actions = corporate_actions
        parent = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS fills (
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          fill_id TEXT NOT NULL UNIQUE, bot TEXT NOT NULL, book TEXT NOT NULL,
          position_id TEXT NOT NULL, symbol TEXT NOT NULL,
          side TEXT NOT NULL CHECK(side IN ('BUY','SELL','FLAG')),
          qty REAL NOT NULL CHECK(qty >= 0), price REAL NOT NULL CHECK(price >= 0),
          bid REAL, ask REAL, cost REAL NOT NULL DEFAULT 0, fee REAL NOT NULL DEFAULT 0,
          ts TEXT NOT NULL, reason TEXT NOT NULL, source TEXT, signal_key TEXT,
          paper INTEGER NOT NULL DEFAULT 1, correction_of TEXT,
          backfilled INTEGER NOT NULL DEFAULT 0, flags TEXT);
        CREATE INDEX IF NOT EXISTS fills_book ON fills(book, position_id);
        CREATE TRIGGER IF NOT EXISTS fills_no_update BEFORE UPDATE ON fills
          BEGIN SELECT RAISE(ABORT, 'fills ledger is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS fills_no_delete BEFORE DELETE ON fills
          BEGIN SELECT RAISE(ABORT, 'fills ledger is append-only'); END;
        """)
        self.db.commit()

    # ------------------------------------------------------------------ writes
    def _position_cost(self, book, position_id):
        qty = cost = 0.0
        for side, q, p in self.db.execute(
                "SELECT side, qty, price FROM fills WHERE book=? AND position_id=? ORDER BY seq",
                (book, position_id)):
            if side == "BUY":
                cost += q * p
                qty += q
            elif side == "SELL" and qty > 0:
                cost -= cost / qty * min(q, qty)
                qty -= min(q, qty)
        return qty, (cost / qty if qty > 1e-12 else None)

    def record(self, *, fill_id, book, position_id, symbol, side, qty, price, ts=None,
               reason, bid=None, ask=None, cost=0.0, fee=0.0, source=None,
               signal_key=None, paper=True, correction_of=None, backfilled=False,
               flags=None) -> bool:
        """Insert one fill. Returns False if this fill_id was already recorded."""
        side = str(side).upper()
        if side not in SIDES:
            raise ValueError(f"side must be one of {SIDES}")
        row = (str(fill_id), self.bot, book, str(position_id), str(symbol), side,
               float(qty), float(price), bid, ask, float(cost or 0), float(fee or 0),
               utc_iso(ts), reason, source, signal_key, 1 if paper else 0,
               correction_of, 1 if backfilled else 0,
               json.dumps(sorted(flags)) if flags else None)
        with self._lock:
            if side == "SELL":
                _, avg = self._position_cost(book, str(position_id))
            cur = self.db.execute(
                f"INSERT OR IGNORE INTO fills({','.join(COLUMNS)}) VALUES({','.join('?' * len(COLUMNS))})",
                row)
            inserted = cur.rowcount == 1
            if (inserted and side == "SELL" and self.corporate_actions and avg
                    and self._suspect(avg, float(price))):
                self._flag(book, str(position_id), str(symbol), float(price), utc_iso(ts),
                           f"sell at {price} vs average cost {round(avg, 6)}", paper, backfilled)
            self.db.commit()
        return inserted

    @staticmethod
    def _suspect(reference, price):
        return reference > 0 and price > 0 and (
            price >= reference * SUSPECT_RATIO or price <= reference / SUSPECT_RATIO)

    def _flag(self, book, position_id, symbol, price, ts, note, paper, backfilled=False):
        self.db.execute(
            f"INSERT OR IGNORE INTO fills({','.join(COLUMNS)}) VALUES({','.join('?' * len(COLUMNS))})",
            (f"flag:{book}:{position_id}:corporate_action", self.bot, book, position_id, symbol,
             "FLAG", 0.0, price, None, None, 0.0, 0.0, ts, "suspect_corporate_action",
             note, None, 1 if paper else 0, None, 1 if backfilled else 0, None))

    def check_mark(self, book, position_id, symbol, mark, ts=None, paper=True) -> bool:
        """Flag an open position whose mark has jumped 3x or fallen to a third of its cost."""
        if not self.corporate_actions:
            return False
        with self._lock:
            qty, avg = self._position_cost(book, str(position_id))
            if qty > 1e-12 and avg and self._suspect(avg, float(mark)):
                self._flag(book, str(position_id), str(symbol), float(mark), utc_iso(ts),
                           f"mark {mark} vs average cost {round(avg, 6)}", paper)
                self.db.commit()
                return True
        return False

    def _review_events(self, book, position_id):
        return [r for r in self.rows(book) if r["position_id"] == str(position_id) and r["side"] == "FLAG"
                and r["reason"] in ("reviewed", "review_revoked")]

    def mark_reviewed(self, book, position_id, note, ts=None):
        """Clear a corporate-action flag after a person has checked the position.

        The first review keeps its original row id, so reruns stay no-ops. A review after a
        revoke gets a new id: every decision stays in the ledger as its own row."""
        flag_id = f"flag:{book}:{position_id}:corporate_action"
        with self._lock:
            n = len(self._review_events(book, position_id))
            row_id = f"reviewed:{flag_id}" if n == 0 else f"reviewed:{flag_id}:{n}"
            self.db.execute(
                f"INSERT OR IGNORE INTO fills({','.join(COLUMNS)}) VALUES({','.join('?' * len(COLUMNS))})",
                (row_id, self.bot, book, str(position_id), "", "FLAG", 0.0, 0.0,
                 None, None, 0.0, 0.0, utc_iso(ts), "reviewed", note, None, 1, flag_id, 0, None))
            self.db.commit()

    def revoke_review(self, book, position_id, note, ts=None) -> bool:
        """Undo a review that was a mistake: the position is excluded again. Nothing is deleted;
        a new 'review_revoked' row records who undid what and why. False if it is not reviewed."""
        flag_id = f"flag:{book}:{position_id}:corporate_action"
        with self._lock:
            events = self._review_events(book, position_id)
            if not events or events[-1]["reason"] != "reviewed":
                return False
            self.db.execute(
                f"INSERT OR IGNORE INTO fills({','.join(COLUMNS)}) VALUES({','.join('?' * len(COLUMNS))})",
                (f"revoked:{flag_id}:{len(events)}", self.bot, book, str(position_id), "", "FLAG", 0.0, 0.0,
                 None, None, 0.0, 0.0, utc_iso(ts), "review_revoked", note, None, 1,
                 events[-1]["fill_id"], 0, None))
            self.db.commit()
        return True

    # ------------------------------------------------------------------- reads
    def rows(self, book=None, since_seq=0):
        sql = f"SELECT seq,{','.join(COLUMNS)} FROM fills WHERE seq > ?"
        args = [since_seq]
        if book:
            sql += " AND book = ?"
            args.append(book)
        cur = self.db.execute(sql + " ORDER BY seq", args)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def books(self):
        return [b for (b,) in self.db.execute("SELECT DISTINCT book FROM fills ORDER BY book")]

    def report(self, book, start_capital=0.0, marks=None, book_cash=None, book_realised=None,
               paper_only=True):
        """P&L for one book from its fills. marks: {symbol: bid} for open positions.

        Reconciliation compares the book's own figures with the ledger: its cash
        (book_cash) when it keeps cash, otherwise its recorded realised P&L
        (book_realised). Differences over 1 cent are reported, never adjusted."""
        marks = marks or {}
        positions, flagged, cleared = {}, set(), set()
        for r in self.rows(book):
            if paper_only and not r["paper"]:
                continue
            pid = r["position_id"]
            if r["side"] == "FLAG":
                if r["reason"] == "suspect_corporate_action":
                    flagged.add(pid)
                elif r["reason"] == "reviewed":
                    cleared.add(pid)
                elif r["reason"] == "review_revoked":
                    cleared.discard(pid)       # rows are read in order: the latest decision wins
                continue
            p = positions.setdefault(pid, {
                "position_id": pid, "symbol": r["symbol"], "source": r["source"],
                "qty": 0.0, "cost_basis": 0.0, "bought": 0.0, "realised": 0.0, "costs": 0.0,
                "opened_at": r["ts"], "closed_at": None, "backfilled": bool(r["backfilled"])})
            explicit = r["cost"] + r["fee"]
            p["costs"] += explicit
            if r["side"] == "BUY":
                p["cost_basis"] += r["qty"] * r["price"]
                p["bought"] += r["qty"] * r["price"]
                p["qty"] += r["qty"]
                p["realised"] -= explicit
            else:
                q = min(r["qty"], p["qty"])
                avg = p["cost_basis"] / p["qty"] if p["qty"] > 1e-12 else 0.0
                p["realised"] += q * (r["price"] - avg) - explicit
                p["cost_basis"] -= avg * q
                p["qty"] -= q
                if p["qty"] <= 1e-9:
                    p["qty"], p["cost_basis"], p["closed_at"] = 0.0, 0.0, r["ts"]
        excluded = sorted(flagged - cleared)
        counted = {pid: p for pid, p in positions.items() if pid not in excluded}
        done = sorted((p for p in counted.values() if p["closed_at"]), key=lambda p: p["closed_at"])
        open_ = [p for p in counted.values() if not p["closed_at"]]
        realised = sum(p["realised"] for p in counted.values())
        unrealised, unmarked, unmarked_cost = 0.0, [], 0.0
        for p in open_:
            mark = marks.get(p["symbol"])
            if mark is None:
                unmarked.append(p["symbol"])
                unmarked_cost += p["cost_basis"]
                continue
            unrealised += p["qty"] * float(mark) - p["cost_basis"]
        returns = [p["realised"] / p["bought"] * 100 for p in done if p["bought"] > 0]
        equity, peak, drawdown = 0.0, 0.0, 0.0
        for p in done:
            equity += p["realised"]
            peak = max(peak, equity)
            drawdown = min(drawdown, equity - peak)
        by_day, by_source = {}, {}
        for p in done:
            day = p["closed_at"][:10]
            for bucket, key in ((by_day, day), (by_source, p["source"] or "unknown")):
                row = bucket.setdefault(key, {"positions": 0, "wins": 0, "realised": 0.0})
                row["positions"] += 1
                row["wins"] += int(p["realised"] > 0)
                row["realised"] = round(row["realised"] + p["realised"], 4)
        open_cost = sum(p["cost_basis"] for p in open_)
        ledger_cash = float(start_capital) + realised - open_cost
        reconciliation = None
        if book_cash is not None:
            diff = round(float(book_cash) - ledger_cash, 4)
            reconciliation = {"basis": "cash", "book_cash": round(float(book_cash), 2),
                              "ledger_cash": round(ledger_cash, 2), "difference": diff,
                              "ok": abs(diff) <= 0.01}
        elif book_realised is not None:
            ledger_all = sum(p["realised"] for p in positions.values())
            diff = round(float(book_realised) - ledger_all, 4)
            reconciliation = {"basis": "realised_pnl", "book_realised": round(float(book_realised), 2),
                              "ledger_realised": round(ledger_all, 2), "difference": diff,
                              "ok": abs(diff) <= 0.01}
        return {
            "book": book, "bot": self.bot, "paper": True, "ledger_version": LEDGER_VERSION,
            "label": "paper, not real money",
            "realised_pnl": round(realised, 2), "unrealised_pnl": round(unrealised, 2),
            "total_pnl": round(realised + unrealised, 2),
            # False when some open positions have no price: the total then leaves them out.
            "total_pnl_complete": not unmarked,
            "unmarked_cost_basis": round(unmarked_cost, 2),
            # Realised splits into fully closed positions and partial exits on open ones;
            # win rate and average return cover the closed positions only.
            "realised_completed": round(sum(p["realised"] for p in done), 2),
            "realised_partial_open": round(sum(p["realised"] for p in open_), 2),
            "completed_positions": len(done), "open_positions": len(open_),
            "unmarked_open_positions": sorted(set(unmarked)),
            "wins": sum(p["realised"] > 0 for p in done),
            "win_rate_per_position": round(100 * sum(p["realised"] > 0 for p in done) / len(done), 1) if done else None,
            "avg_return_pct": round(sum(returns) / len(returns), 3) if returns else None,
            "largest_win": round(max((p["realised"] for p in done), default=0.0), 2),
            "largest_loss": round(min((p["realised"] for p in done), default=0.0), 2),
            "max_drawdown": round(drawdown, 2),
            "costs_paid": round(sum(p["costs"] for p in counted.values()), 2),
            "open_cost_basis": round(open_cost, 2),
            "excluded_corporate_action_positions": excluded,
            "backfilled_positions": sum(p["backfilled"] for p in counted.values()),
            "by_day": by_day, "by_source": by_source,
            "reconciliation": reconciliation,
        }

    # ----------------------------------------------------------------- exports
    def export(self, reports=None):
        """All fills as CSV plus a manifest (row count, max seq, sha256) and reports."""
        rows = self.rows()
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=["seq", *COLUMNS], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        text = buffer.getvalue()
        return {
            "bot": self.bot, "ledger_version": LEDGER_VERSION, "exported_at": utc_iso(),
            "manifest": {"rows": len(rows), "max_seq": rows[-1]["seq"] if rows else 0,
                         "sha256": hashlib.sha256(text.encode()).hexdigest()},
            "fills_csv": text, "reports": reports or {},
        }


def verify_export(payload) -> list[str]:
    """Problems with an export (empty list = complete and intact)."""
    problems = []
    manifest = payload.get("manifest") or {}
    text = payload.get("fills_csv") or ""
    if hashlib.sha256(text.encode()).hexdigest() != manifest.get("sha256"):
        problems.append("checksum mismatch")
    count = max(0, len(text.strip().splitlines()) - 1) if text.strip() else 0
    if count != manifest.get("rows"):
        problems.append(f"row count {count} != manifest {manifest.get('rows')}")
    return problems


def pnl_panel_html(api_path="api/pnl", title="Paper P&L"):
    """The same P&L page for every bot: one row per book, read from its /api/pnl."""
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>""" + title + """</title><style>
:root{--bg:#0b1220;--card:#121b2e;--line:#24324a;--ink:#e6edf6;--dim:#93a3b8;--ok:#22c55e;--bad:#ef4444;--warn:#f59e0b}
@media (prefers-color-scheme:light){:root{--bg:#f6f8fb;--card:#fff;--line:#d9e0ea;--ink:#142033;--dim:#5b6b80}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px system-ui,sans-serif;padding:20px max(16px,env(safe-area-inset-left))}
h1{font-size:20px;margin:0 0 4px}.sub{color:var(--dim);margin:0 0 16px}.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line);border-radius:10px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
th{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.05em}th:first-child,td:first-child{text-align:left}
.pos{color:var(--ok)}.neg{color:var(--bad)}.warn{color:var(--warn)}.note{color:var(--dim);margin-top:12px;max-width:70ch}
</style></head><body><h1>""" + title + """</h1><p class="sub">Paper, not real money. Every figure is computed from the append-only fills ledger.</p>
<p id="warn" class="warn"></p><div class="wrap"><table><thead><tr><th>Book</th><th>Total</th><th>Realised</th><th>Open</th>
<th>Closed</th><th>Win rate*</th><th>Avg return</th><th>Max drawdown</th><th>Costs</th><th>Reconciled</th><th>Excluded</th></tr></thead>
<tbody id="rows"><tr><td colspan="11">Loading…</td></tr></tbody></table></div>
<p class="note">* Win rate counts completed positions, not partial exits. "Excluded" positions had a price jump of 3x or a fall to a third (possible
reverse split) and stay out of every total until reviewed. A total marked * leaves out open positions that have no current price.
Realised includes partial exits on positions that are still open (hover for the split); win rate covers closed positions only. Books that trade the same signals (for example trials_fixed and
trials_risk_adjusted) are alternatives: compare them, never add them.</p><p id="extra" class="note"></p>
<script>
const money=v=>v==null?'—':(v<0?'-$':'$')+Math.abs(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const cls=v=>v>0?'pos':v<0?'neg':'';
async function load(){try{const d=await (await fetch('""" + api_path + """',{cache:'no-store'})).json();
document.getElementById('warn').textContent=d.storage_warning?'Storage warning: '+d.storage_warning:'';
const books=Object.values(d.books||{});
document.getElementById('rows').innerHTML=books.length?books.map(b=>{const r=b.reconciliation;
const rec=!r?'—':r.ok?'<span class="pos">yes</span>':'<span class="neg">NO, off by '+money(r.difference)+'</span>';
return `<tr><td><b>${b.book}</b></td><td class="${cls(b.total_pnl)}">${money(b.total_pnl)}${b.total_pnl_complete===false?'<span class="warn" title="Open positions without a price are left out">*</span>':''}</td><td class="${cls(b.realised_pnl)}" title="Closed positions ${money(b.realised_completed)}; partial exits on open positions ${money(b.realised_partial_open)}">${money(b.realised_pnl)}</td>
<td class="${cls(b.unrealised_pnl)}">${b.unmarked_open_positions.length?'<span class="warn">unknown: '+b.unmarked_open_positions.length+' not priced ('+money(b.unmarked_cost_basis)+' at cost)</span>':money(b.unrealised_pnl)}</td><td>${b.completed_positions} (${b.open_positions} open)</td>
<td>${b.win_rate_per_position==null?'—':b.win_rate_per_position+'%'}</td><td>${b.avg_return_pct==null?'—':b.avg_return_pct.toFixed(2)+'%'}</td>
<td class="neg">${money(b.max_drawdown)}</td><td>${money(b.costs_paid)}</td><td>${rec}</td><td>${b.excluded_corporate_action_positions.length||'—'}</td></tr>`}).join('')
:'<tr><td colspan="11">No fills recorded yet.</td></tr>';
document.getElementById('extra').textContent=(d.note||'')+(d.backfill?' Backfill: '+d.backfill.state+'.':'');
}catch(e){document.getElementById('rows').innerHTML='<tr><td colspan="11" class="neg">P&L unavailable</td></tr>'}}
load();setInterval(load,30000);</script></body></html>"""
