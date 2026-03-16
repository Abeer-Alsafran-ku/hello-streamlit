import streamlit as st
import pandas as pd
import json
import os
from datetime import date, datetime, timedelta
import time

st.set_page_config(page_title="Flight Price Tracker", page_icon="✈️", layout="wide")

# ── helpers ──────────────────────────────────────────────────────────────────

WATCHLIST_FILE = "flight_watchlist.json"

AIRPORT_CODES = {
    "New York (JFK)": "JFK",
    "New York (LGA)": "LGA",
    "Los Angeles (LAX)": "LAX",
    "Chicago (ORD)": "ORD",
    "San Francisco (SFO)": "SFO",
    "Miami (MIA)": "MIA",
    "London (LHR)": "LHR",
    "London (LGW)": "LGW",
    "Paris (CDG)": "CDG",
    "Amsterdam (AMS)": "AMS",
    "Dubai (DXB)": "DXB",
    "Tokyo (NRT)": "NRT",
    "Singapore (SIN)": "SIN",
    "Sydney (SYD)": "SYD",
    "Toronto (YYZ)": "YYZ",
    "Frankfurt (FRA)": "FRA",
    "Madrid (MAD)": "MAD",
    "Rome (FCO)": "FCO",
    "Istanbul (IST)": "IST",
    "Bangkok (BKK)": "BKK",
}


def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE) as f:
            return json.load(f)
    return []


def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f, indent=2)


def search_flights_amadeus(origin, destination, dep_date, adults=1):
    """Search flights via Amadeus API (requires AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET env vars)."""
    try:
        from amadeus import Client  # type: ignore

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
            dep_time = first_seg["departure"]["at"]
            arr_time = last_seg["arrival"]["at"]
            carrier = first_seg["carrierCode"]
            stops = len(segments) - 1
            duration = itinerary["duration"].replace("PT", "").lower()
            results.append(
                {
                    "Airline": carrier,
                    "Departure": dep_time,
                    "Arrival": arr_time,
                    "Duration": duration,
                    "Stops": stops,
                    "Price (USD)": price,
                }
            )
        return sorted(results, key=lambda x: x["Price (USD)"])
    except ImportError:
        return None
    except KeyError:
        return None


def search_flights_demo(origin, destination, dep_date):
    """Return deterministic demo data when no API key is configured."""
    import hashlib
    import random

    seed = int(hashlib.md5(f"{origin}{destination}{dep_date}".encode()).hexdigest(), 16) % (2**31)
    rng = random.Random(seed)

    airlines = ["AA", "UA", "DL", "BA", "LH", "EK", "SQ", "QF", "AF", "KL"]
    results = []
    base_price = rng.randint(150, 900)
    for i in range(8):
        airline = rng.choice(airlines)
        price = round(base_price + rng.uniform(-50, 300) * (i * 0.3 + 1), 2)
        dep_hour = rng.randint(5, 22)
        dep_min = rng.choice([0, 15, 30, 45])
        duration_h = rng.randint(1, 14)
        duration_m = rng.choice([0, 15, 30, 45])
        arr_hour = (dep_hour + duration_h) % 24
        arr_min = (dep_min + duration_m) % 60
        stops = rng.choices([0, 1, 2], weights=[50, 35, 15])[0]
        results.append(
            {
                "Airline": airline,
                "Departure": f"{dep_date} {dep_hour:02d}:{dep_min:02d}",
                "Arrival": f"{dep_date} {arr_hour:02d}:{arr_min:02d}",
                "Duration": f"{duration_h}h {duration_m}m",
                "Stops": stops,
                "Price (USD)": price,
            }
        )
    return sorted(results, key=lambda x: x["Price (USD)"])


def search_flights(origin, destination, dep_date, adults=1):
    results = search_flights_amadeus(origin, destination, dep_date, adults)
    if results is None:
        results = search_flights_demo(origin, destination, dep_date)
    return results


# ── UI ───────────────────────────────────────────────────────────────────────

st.title("✈️ Flight Price Tracker")
st.caption("Search for the lowest fares and monitor prices automatically.")

using_demo = "AMADEUS_CLIENT_ID" not in os.environ
if using_demo:
    st.info(
        "Running in **demo mode** with simulated prices. "
        "Set `AMADEUS_CLIENT_ID` and `AMADEUS_CLIENT_SECRET` environment variables to use live data.",
        icon="ℹ️",
    )

# ── Search form ───────────────────────────────────────────────────────────────
with st.form("search_form"):
    col1, col2, col3, col4 = st.columns([2, 2, 1.5, 1])

    airport_names = list(AIRPORT_CODES.keys())

    with col1:
        from_name = st.selectbox("From", airport_names, index=0)
    with col2:
        to_name = st.selectbox("To", airport_names, index=2)
    with col3:
        dep_date = st.date_input("Departure date", value=date.today() + timedelta(days=30), min_value=date.today())
    with col4:
        adults = st.number_input("Passengers", min_value=1, max_value=9, value=1)

    search_clicked = st.form_submit_button("Search Flights", use_container_width=True, type="primary")

# ── Search results ────────────────────────────────────────────────────────────
if search_clicked:
    origin_code = AIRPORT_CODES[from_name]
    dest_code = AIRPORT_CODES[to_name]

    if origin_code == dest_code:
        st.error("Origin and destination must be different.")
    else:
        with st.spinner("Searching for flights..."):
            time.sleep(0.5)  # brief pause for UX
            flights = search_flights(origin_code, dest_code, str(dep_date), adults)

        st.session_state["last_results"] = flights
        st.session_state["last_search"] = {
            "from_name": from_name,
            "to_name": to_name,
            "origin": origin_code,
            "destination": dest_code,
            "date": str(dep_date),
            "adults": adults,
        }

if "last_results" in st.session_state and st.session_state["last_results"]:
    flights = st.session_state["last_results"]
    search = st.session_state["last_search"]

    st.subheader(
        f"{search['from_name']} → {search['to_name']}  |  {search['date']}  |  {search['adults']} passenger(s)"
    )

    df = pd.DataFrame(flights)
    lowest = df["Price (USD)"].min()

    # highlight cheapest
    def highlight_cheapest(row):
        if row["Price (USD)"] == lowest:
            return ["background-color: #d4edda"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df.style.apply(highlight_cheapest, axis=1).format({"Price (USD)": "${:.2f}"}),
        use_container_width=True,
        hide_index=True,
    )

    st.success(f"Lowest price found: **${lowest:.2f} USD** (highlighted in green)")

    # ── Add to watchlist ──────────────────────────────────────────────────────
    st.divider()
    st.subheader("Monitor this route")
    with st.expander("Set a price alert for this route", expanded=True):
        with st.form("alert_form"):
            c1, c2 = st.columns(2)
            with c1:
                alert_email = st.text_input("Your email address", placeholder="you@example.com")
            with c2:
                price_threshold = st.number_input(
                    "Alert me when price drops below (USD)",
                    min_value=1,
                    max_value=10000,
                    value=int(lowest * 0.9),
                )
            monitor_interval = st.selectbox(
                "Check prices every",
                ["15 minutes", "30 minutes", "1 hour", "3 hours", "6 hours", "12 hours", "24 hours"],
                index=2,
            )
            add_alert = st.form_submit_button("Add Price Alert", type="primary")

        if add_alert:
            if not alert_email or "@" not in alert_email:
                st.error("Please enter a valid email address.")
            else:
                watchlist = load_watchlist()
                entry = {
                    "id": f"{search['origin']}-{search['destination']}-{search['date']}-{int(time.time())}",
                    "origin": search["origin"],
                    "destination": search["destination"],
                    "origin_name": search["from_name"],
                    "destination_name": search["to_name"],
                    "date": search["date"],
                    "adults": search["adults"],
                    "email": alert_email,
                    "threshold": price_threshold,
                    "interval": monitor_interval,
                    "last_checked": None,
                    "lowest_seen": lowest,
                    "created_at": datetime.now().isoformat(),
                }
                watchlist.append(entry)
                save_watchlist(watchlist)
                st.success(
                    f"Alert added! You'll be notified at **{alert_email}** when the price drops below **${price_threshold}**."
                )

# ── Watchlist ─────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Active Price Alerts")

watchlist = load_watchlist()
if not watchlist:
    st.caption("No active alerts. Search for a flight above and add an alert.")
else:
    for i, entry in enumerate(watchlist):
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
            with c1:
                st.write(f"**{entry['origin_name']} → {entry['destination_name']}**")
                st.caption(f"Date: {entry['date']}  |  Passengers: {entry['adults']}")
            with c2:
                st.metric("Alert threshold", f"${entry['threshold']}")
            with c3:
                st.metric("Lowest seen", f"${entry['lowest_seen']:.2f}")
                checked = entry.get("last_checked") or "never"
                st.caption(f"Last checked: {checked}")
            with c4:
                if st.button("Remove", key=f"del_{entry['id']}"):
                    watchlist.pop(i)
                    save_watchlist(watchlist)
                    st.rerun()
            st.caption(f"Notifications → {entry['email']}  |  Interval: {entry['interval']}")
