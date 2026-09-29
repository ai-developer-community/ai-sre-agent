#!/usr/bin/env python3
"""Sustain checkout traffic until Ctrl-C. Uses stdlib only."""

import argparse
import concurrent.futures
import json
import time
import urllib.error
import urllib.request


def request(url):
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                url + "/checkout", data=b"{}", headers={"Content-Type": "application/json"}
            ),
            timeout=10,
        ) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError):
        return "network_error"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--rps", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.rps <= 20:
        parser.error("rps must be between 1 and 20")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.rps) as pool:
        try:
            while True:
                started = time.monotonic()
                statuses = list(pool.map(request, [args.url.rstrip("/")] * args.rps))
                print(json.dumps({"time": time.time(), "statuses": statuses}), flush=True)
                time.sleep(max(0, 1 - (time.monotonic() - started)))
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
