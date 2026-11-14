"""
Daily Indian-stock portfolio agent.

Flow:
  1. Read holdings from portfolio.csv
  2. Fetch last two closes from Yahoo Finance (NSE/BSE) and compute P&L  -> plain code
  3. Fetch a news headline for each of the day's big movers
  4. Send the report to Telegram

Environment variables:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   required (unless DRY_RUN=true)
  DRY_RUN=true                           print the message instead of sending it
  FORCE_SEND=true                        send even if the market was closed today
"""

import csv
import html
import os
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

IST = ZoneInfo("Asia/Kolkata")
PORTFOLIO_FILE = Path(__file__).parent / "portfolio.csv"
BIG_MOVE_PCT = 2.0        # a move worth a headline
TELEGRAM_LIMIT = 4000     # Telegram's cap is 4096 characters per message


def env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------- portfolio

def load_portfolio() -> list[dict]:
    holdings = []
    with open(PORTFOLIO_FILE, newline="") as f:
        for row in csv.DictReader(f):
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol or symbol.startswith("#"):
                continue
            exchange = (row.get("exchange") or "NSE").strip().upper()
            holdings.append({
                "symbol": symbol,
                "name": (row.get("name") or symbol).strip(),
                "ticker": symbol + (".BO" if exchange == "BSE" else ".NS"),
                "qty": float(row["quantity"]),
                "avg": float(row["avg_price"]),
            })
    if not holdings:
        sys.exit("portfolio.csv has no holdings")
    return holdings


# ------------------------------------------------------------------- prices

def fetch_closes(ticker: str):
    """Return (last_close, previous_close, date_of_last_close) or None."""
    import yfinance as yf
    for _ in range(3):
        try:
            closes = yf.Ticker(ticker).history(period="7d")["Close"].dropna()
            if len(closes) >= 2:
                return float(closes.iloc[-1]), float(closes.iloc[-2]), closes.index[-1].date()
        except Exception as e:  # Yahoo is flaky; retry
            print(f"  retrying {ticker}: {e}", file=sys.stderr)
    return None


def build_snapshot(holdings: list[dict], fetch=fetch_closes) -> dict:
    rows, failed, last_date = [], [], None
    for h in holdings:
        got = fetch(h["ticker"])
        if not got:
            failed.append(h["symbol"])
            continue
        ltp, prev, day = got
        last_date = max(last_date, day) if last_date else day
        invested, value = h["qty"] * h["avg"], h["qty"] * ltp
        rows.append({
            "symbol": h["symbol"], "name": h["name"], "qty": h["qty"],
            "ltp": ltp, "avg": h["avg"],
            "day_pct": (ltp - prev) / prev * 100,
            "day_pnl": h["qty"] * (ltp - prev),
            "invested": invested, "value": value,
            "total_pnl": value - invested,
            "total_pct": (value - invested) / invested * 100,
        })
    if not rows:
        sys.exit("Could not fetch a price for any holding")

    invested = sum(r["invested"] for r in rows)
    value = sum(r["value"] for r in rows)
    day_pnl = sum(r["day_pnl"] for r in rows)
    prev_value = value - day_pnl
    rows.sort(key=lambda r: r["day_pct"], reverse=True)
    return {
        "date": last_date, "rows": rows, "failed": failed,
        "invested": invested, "value": value,
        "day_pnl": day_pnl, "day_pct": day_pnl / prev_value * 100,
        "total_pnl": value - invested, "total_pct": (value - invested) / invested * 100,
    }


# --------------------------------------------------------------------- news

def get_news(query: str, limit: int = 5) -> list[dict]:
    """Recent headlines from Google News (India edition). No API key needed."""
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(f"{query} when:2d") + "&hl=en-IN&gl=IN&ceid=IN:en")
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        items = ET.fromstring(resp.content).findall("./channel/item")[:limit]
    except Exception as e:
        print(f"  news lookup failed for {query!r}: {e}", file=sys.stderr)
        return []
    return [{"title": i.findtext("title", ""), "link": i.findtext("link", ""),
             "published": i.findtext("pubDate", "")} for i in items]


def mover_headlines(snap: dict) -> list[dict]:
    """One headline for each of the day's big movers."""
    movers = sorted(snap["rows"], key=lambda r: abs(r["day_pct"]), reverse=True)[:3]
    out = []
    for r in movers:
        if abs(r["day_pct"]) >= BIG_MOVE_PCT:
            out.extend(get_news(f"{r['name']} share", limit=1))
    return out


# --------------------------------------------------------------- formatting

def inr(x: float, sign: bool = False) -> str:
    """Indian digit grouping: 1234567 -> 12,34,567"""
    n = str(abs(round(x)))
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        n = ",".join(([head] if head else []) + groups + [tail])
    prefix = "-" if x < 0 else ("+" if sign else "")
    return f"{prefix}₹{n}"


def pct(x: float) -> str:
    return f"{x:+.2f}%"


def dot(x: float) -> str:
    return "🟢" if x >= 0 else "🔴"


def format_message(snap: dict, headlines: list[dict]) -> str:
    rows = snap["rows"]
    lines = [
        f"📊 <b>Portfolio update · {snap['date'].strftime('%a, %d %b %Y')}</b>",
        "",
        f"Value: <b>{inr(snap['value'])}</b>  (invested {inr(snap['invested'])})",
        f"{dot(snap['day_pnl'])} Today: <b>{inr(snap['day_pnl'], sign=True)}</b> ({pct(snap['day_pct'])})",
        f"{dot(snap['total_pnl'])} Overall: <b>{inr(snap['total_pnl'], sign=True)}</b> ({pct(snap['total_pct'])})",
        "",
    ]

    gainers = [r for r in rows if r["day_pct"] > 0][:3]
    losers = [r for r in reversed(rows) if r["day_pct"] < 0][:3]
    if gainers:
        lines.append("<b>Top gainers</b>")
        lines += [f"🟢 {r['symbol']} {pct(r['day_pct'])} ({inr(r['day_pnl'], sign=True)})" for r in gainers]
    if losers:
        lines.append("<b>Top losers</b>")
        lines += [f"🔴 {r['symbol']} {pct(r['day_pct'])} ({inr(r['day_pnl'], sign=True)})" for r in losers]

    table = [f"{'Stock':<11}{'LTP':>9}{'Day%':>8}{'P&L%':>8}"]
    table += [f"{r['symbol'][:10]:<11}{r['ltp']:>9.1f}{r['day_pct']:>+8.2f}{r['total_pct']:>+8.1f}" for r in rows]
    lines += ["", "<b>All holdings</b>", "<pre>" + html.escape("\n".join(table)) + "</pre>"]

    if headlines:
        lines += ["", "<b>Headlines</b>"]
        lines += [f'• <a href="{html.escape(h["link"], quote=True)}">{html.escape(h["title"])}</a>'
                  for h in headlines[:5]]
    if snap["failed"]:
        lines += ["", "⚠️ No price found for: " + ", ".join(snap["failed"])]
    return "\n".join(lines)


# ----------------------------------------------------------------- telegram

def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    chunks, current = [], ""
    for block in text.split("\n\n"):       # sections never split inside a tag
        if current and len(current) + len(block) + 2 > limit:
            chunks.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    return chunks + [current]


def send_telegram(text: str) -> None:
    token, chat_id = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    for chunk in split_message(text):
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage", timeout=30,
            json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
        )
        if not resp.ok:
            sys.exit(f"Telegram rejected the message: {resp.status_code} {resp.text}")


# --------------------------------------------------------------------- main

def main() -> None:
    snap = build_snapshot(load_portfolio())
    today = datetime.now(IST).date()

    if snap["date"] != today and not env_flag("FORCE_SEND"):
        print(f"Market was closed today ({today}); last session was {snap['date']}. Nothing sent.")
        return

    message = format_message(snap, mover_headlines(snap))
    if env_flag("DRY_RUN"):
        print(message)
    else:
        send_telegram(message)
        print("Sent.")


if __name__ == "__main__":
    main()
