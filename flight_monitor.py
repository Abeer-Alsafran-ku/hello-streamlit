#!/usr/bin/env python3
"""
Flight Price Monitor
====================
Background script that reads flight_watchlist.json, checks current prices for
each entry, and sends an email notification when a price drops below the
user-defined threshold.

Usage
-----
    python flight_monitor.py               # run once, then exit
    python flight_monitor.py --daemon      # loop continuously (respects per-entry interval)

Environment variables
---------------------
Required for live flight data:
    AMADEUS_CLIENT_ID       – Amadeus API client ID
    AMADEUS_CLIENT_SECRET   – Amadeus API client secret

Required for email notifications:
    SMTP_HOST               – SMTP server hostname  (default: smtp.gmail.com)
    SMTP_PORT               – SMTP server port      (default: 587)
    SMTP_USER               – SMTP login username / sender address
    SMTP_PASSWORD           – SMTP login password or app password

Optional:
    WATCHLIST_FILE          – Path to watchlist JSON  (default: flight_watchlist.json)
    MONITOR_LOG_FILE        – Path to log file        (default: flight_monitor.log)
"""

import argparse
import json
import logging
import os
import smtplib
import sys
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Configuration ─────────────────────────────────────────────────────────────

WATCHLIST_FILE = os.environ.get("WATCHLIST_FILE", "flight_watchlist.json")
LOG_FILE = os.environ.get("MONITOR_LOG_FILE", "flight_monitor.log")

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

INTERVAL_MAP = {
    "15 minutes": 15 * 60,
    "30 minutes": 30 * 60,
    "1 hour": 60 * 60,
    "3 hours": 3 * 60 * 60,
    "6 hours": 6 * 60 * 60,
    "12 hours": 12 * 60 * 60,
    "24 hours": 24 * 60 * 60,
}
DEFAULT_INTERVAL = 60 * 60  # 1 hour

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger(__name__)


# ── Flight search ─────────────────────────────────────────────────────────────

def search_flights_amadeus(origin: str, destination: str, dep_date: str, adults: int = 1):
    """Return list of price dicts using Amadeus API, or None on failure."""
    try:
        from amadeus import Client, ResponseError  # type: ignore

        amadeus = Client(
            client_id=os.environ["AMADEUS_CLIENT_ID"],
            client_secret=os.environ["AMADEUS_CLIENT_SECRET"],
        )
        response = amadeus.shopping.flight_offers_search.get(
            originLocationCode=origin,
            destinationLocationCode=destination,
            departureDate=dep_date,
            adults=adults,
            max=10,
            currencyCode="USD",
        )
        results = []
        for offer in response.data:
            price = float(offer["price"]["grandTotal"])
            itinerary = offer["itineraries"][0]
            segments = itinerary["segments"]
            first_seg = segments[0]
            last_seg = segments[-1]
            results.append(
                {
                    "airline": first_seg["carrierCode"],
                    "departure": first_seg["departure"]["at"],
                    "arrival": last_seg["arrival"]["at"],
                    "stops": len(segments) - 1,
                    "price": price,
                }
            )
        return sorted(results, key=lambda x: x["price"])
    except ImportError:
        log.warning("amadeus package not installed; falling back to demo data.")
        return None
    except KeyError:
        log.warning("AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET not set; using demo data.")
        return None
    except Exception as exc:  # noqa: BLE001
        log.error("Amadeus API error: %s", exc)
        return None


def search_flights_demo(origin: str, destination: str, dep_date: str):
    """Deterministic demo prices seeded by route + date."""
    import hashlib
    import random

    seed = int(hashlib.md5(f"{origin}{destination}{dep_date}".encode()).hexdigest(), 16) % (2**31)
    rng = random.Random(seed)
    airlines = ["AA", "UA", "DL", "BA", "LH", "EK", "SQ", "QF", "AF", "KL"]
    base_price = rng.randint(150, 900)
    results = []
    for i in range(8):
        price = round(base_price + rng.uniform(-50, 300) * (i * 0.3 + 1), 2)
        results.append({"airline": rng.choice(airlines), "price": price})
    return sorted(results, key=lambda x: x["price"])


def get_lowest_price(origin: str, destination: str, dep_date: str, adults: int = 1) -> float:
    results = search_flights_amadeus(origin, destination, dep_date, adults)
    if results is None:
        results = search_flights_demo(origin, destination, dep_date)
    if not results:
        raise RuntimeError("No flight results returned.")
    return results[0]["price"]


# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(to_address: str, subject: str, html_body: str) -> bool:
    """Send an HTML email via SMTP. Returns True on success."""
    if not SMTP_USER or not SMTP_PASSWORD:
        log.warning("SMTP_USER / SMTP_PASSWORD not configured – skipping email send.")
        log.info("Would have sent to %s: %s", to_address, subject)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to_address
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to_address, msg.as_string())
        log.info("Email sent to %s (%s)", to_address, subject)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("Failed to send email to %s: %s", to_address, exc)
        return False


def build_alert_email(entry: dict, current_price: float) -> tuple[str, str]:
    origin_name = entry.get("origin_name", entry["origin"])
    dest_name = entry.get("destination_name", entry["destination"])
    threshold = entry["threshold"]
    route = f"{origin_name} ({entry['origin']}) → {dest_name} ({entry['destination']})"

    subject = f"✈️ Price Alert: {entry['origin']}→{entry['destination']} now ${current_price:.2f}"

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
      <div style="background:#1e3a5f;color:white;padding:20px;border-radius:8px 8px 0 0">
        <h2 style="margin:0">✈️ Flight Price Alert</h2>
      </div>
      <div style="background:#f9f9f9;padding:24px;border:1px solid #ddd;border-radius:0 0 8px 8px">
        <p>Good news! The price for your monitored route has dropped below your threshold.</p>
        <table style="width:100%;border-collapse:collapse">
          <tr style="background:#eaf0fb">
            <td style="padding:10px;font-weight:bold">Route</td>
            <td style="padding:10px">{route}</td>
          </tr>
          <tr>
            <td style="padding:10px;font-weight:bold">Travel Date</td>
            <td style="padding:10px">{entry['date']}</td>
          </tr>
          <tr style="background:#eaf0fb">
            <td style="padding:10px;font-weight:bold">Your Threshold</td>
            <td style="padding:10px">${threshold:.2f} USD</td>
          </tr>
          <tr>
            <td style="padding:10px;font-weight:bold">Current Lowest Price</td>
            <td style="padding:10px;color:#1a7c3c;font-size:1.4em;font-weight:bold">${current_price:.2f} USD</td>
          </tr>
          <tr style="background:#eaf0fb">
            <td style="padding:10px;font-weight:bold">Passengers</td>
            <td style="padding:10px">{entry['adults']}</td>
          </tr>
        </table>
        <p style="margin-top:20px;color:#555;font-size:0.85em">
          This alert was generated by Flight Price Tracker. Prices are subject to change.
          You will continue to receive alerts each time the price is below your threshold.
        </p>
      </div>
    </body></html>
    """
    return subject, html


# ── Watchlist helpers ─────────────────────────────────────────────────────────

def load_watchlist() -> list:
    if not os.path.exists(WATCHLIST_FILE):
        return []
    with open(WATCHLIST_FILE) as f:
        return json.load(f)


def save_watchlist(watchlist: list) -> None:
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f, indent=2)


def is_due(entry: dict) -> bool:
    last_checked = entry.get("last_checked")
    if not last_checked:
        return True
    interval_secs = INTERVAL_MAP.get(entry.get("interval", ""), DEFAULT_INTERVAL)
    last_dt = datetime.fromisoformat(last_checked)
    return datetime.now() - last_dt >= timedelta(seconds=interval_secs)


# ── Core check loop ───────────────────────────────────────────────────────────

def check_all():
    """Check every due entry in the watchlist and send alerts as needed."""
    watchlist = load_watchlist()
    if not watchlist:
        log.info("Watchlist is empty – nothing to check.")
        return

    updated = False
    now_str = datetime.now().isoformat(timespec="seconds")

    for entry in watchlist:
        if not is_due(entry):
            log.debug(
                "Skipping %s→%s (not due yet).",
                entry["origin"],
                entry["destination"],
            )
            continue

        origin = entry["origin"]
        dest = entry["destination"]
        dep_date = entry["date"]
        adults = entry.get("adults", 1)
        threshold = entry["threshold"]
        email = entry["email"]

        log.info("Checking %s → %s on %s …", origin, dest, dep_date)
        try:
            lowest = get_lowest_price(origin, dest, dep_date, adults)
        except Exception as exc:  # noqa: BLE001
            log.error("Error fetching price for %s→%s: %s", origin, dest, exc)
            continue

        log.info("  Lowest price: $%.2f  (threshold: $%.2f)", lowest, threshold)

        entry["last_checked"] = now_str
        entry["lowest_seen"] = min(entry.get("lowest_seen", lowest), lowest)
        updated = True

        if lowest <= threshold:
            log.info("  Price is at or below threshold – sending alert to %s", email)
            subject, html = build_alert_email(entry, lowest)
            send_email(email, subject, html)
        else:
            log.info("  Price above threshold – no alert sent.")

    if updated:
        save_watchlist(watchlist)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Flight price monitor")
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously, sleeping between checks (default: run once).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        metavar="SECONDS",
        help="Seconds to sleep between full watchlist scans in daemon mode (default: 300).",
    )
    args = parser.parse_args()

    log.info("Flight Price Monitor starting (daemon=%s)", args.daemon)

    if args.daemon:
        log.info("Daemon mode – press Ctrl+C to stop.")
        try:
            while True:
                check_all()
                log.info("Sleeping %d seconds …", args.interval)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            log.info("Interrupted – exiting.")
    else:
        check_all()
        log.info("Done.")


if __name__ == "__main__":
    main()
