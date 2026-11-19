"""Fetch LNER departures in both directions between London King's Cross and
Leeds, and save them to trains.json. Run by GitHub Actions every 10 minutes.

The API key is read from the RDM_CONSUMER_KEY environment variable, which comes
from a GitHub secret. It is sent in a request header. It is never printed and
never written to trains.json.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

# If requests fail, check the base address and header against the Live
# Departure Board 1.1 specification page on the Rail Data Marketplace.
BASE_URL = os.environ.get(
    "RDM_BASE_URL",
    "https://api1.raildata.org.uk/1010-live-departure-board-dep1_2/LDBWS/api/20220120",
)
KEY = os.environ.get("RDM_CONSUMER_KEY", "").strip()

# Route name used on the page -> (from station, to station)
ROUTES = {"KGX-LDS": ("KGX", "LDS"), "LDS-KGX": ("LDS", "KGX")}
LNER_CODE = "GR"          # LNER's operator code
ROWS = 10                 # how many departures to ask for per station
OUT_FILE = "trains.json"
LONDON = ZoneInfo("Europe/London")


def fetch_board(frm, to):
    """Ask for the next departures from `frm` that are going to `to`."""
    url = (f"{BASE_URL}/GetDepBoardWithDetails/{frm}"
           f"?numRows={ROWS}&filterCrs={to}&filterType=to")
    req = urllib.request.Request(
        url, headers={"x-apikey": KEY, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def empty_to_none(value):
    return value if value not in (None, "") else None


def arrival_at(service, dest):
    """Find the scheduled and estimated arrival at `dest` from the calling points."""
    for group in service.get("subsequentCallingPoints") or []:
        for point in group.get("callingPoint") or []:
            if point.get("crs") == dest:
                return point.get("st"), point.get("et")
    return None, None


def parse_services(board, to):
    """Keep only LNER services and pull out the fields the page needs."""
    trains = []
    for s in board.get("trainServices") or []:
        operator = s.get("operator") or ""
        if s.get("operatorCode") != LNER_CODE and "North Eastern" not in operator:
            continue
        arr_st, arr_et = arrival_at(s, to)
        trains.append({
            "std": empty_to_none(s.get("std")),
            "etd": empty_to_none(s.get("etd")),
            "platform": empty_to_none(s.get("platform")),
            "cancelled": bool(s.get("isCancelled")),
            "cancelReason": empty_to_none(s.get("cancelReason")),
            "delayReason": empty_to_none(s.get("delayReason")),
            "arrivalSt": empty_to_none(arr_st),
            "arrivalEt": empty_to_none(arr_et),
        })
    return trains


def main():
    result = {
        "updated": datetime.now(LONDON).strftime("%Y-%m-%d %H:%M"),
        "routes": {},
        "error": None,
    }
    try:
        if not KEY:
            raise RuntimeError("missing key")
        for name, (frm, to) in ROUTES.items():
            result["routes"][name] = parse_services(fetch_board(frm, to), to)
    except urllib.error.HTTPError as err:
        # Only the status code is shown, so nothing sensitive is logged.
        result["error"] = f"The train service returned an error ({err.code}). It will try again soon."
        result["routes"] = {}
    except RuntimeError:
        result["error"] = "Train times aren't set up yet."
        result["routes"] = {}
    except (urllib.error.URLError, ValueError) as err:
        result["error"] = f"Couldn't load train times ({type(err).__name__})."
        result["routes"] = {}

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    counts = {name: len(trains) for name, trains in result["routes"].items()}
    print("Updated", result["updated"], "| trains per route:", counts, "| error:", result["error"])


if __name__ == "__main__":
    main()
