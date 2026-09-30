#!/usr/bin/env python3
"""Sustain checkout traffic until Ctrl-C. Uses stdlib only."""

import argparse
import concurrent.futures
import json
import subprocess
import time
import urllib.error
import urllib.request


def request(url, token=""):
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                url + "/checkout",
                data=b"{}",
                headers={
                    "Content-Type": "application/json",
                    **({"Authorization": "Bearer " + token} if token else {}),
                },
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
    parser.add_argument(
        "--authenticated",
        action="store_true",
        help="Use the active gcloud operator identity for a private demo shop",
    )
    parser.add_argument(
        "--seconds", type=int, default=0, help="Stop after this duration; 0 runs until Ctrl-C"
    )
    args = parser.parse_args()
    if not 1 <= args.rps <= 20:
        parser.error("rps must be between 1 and 20")
    if args.seconds < 0:
        parser.error("seconds must not be negative")
    token, refreshed = "", 0
    deadline = time.monotonic() + args.seconds if args.seconds else float("inf")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.rps) as pool:
        try:
            while time.monotonic() < deadline:
                if args.authenticated and (not token or time.monotonic() - refreshed > 2400):
                    token = subprocess.check_output(
                        ["gcloud", "auth", "print-identity-token"], text=True
                    ).strip()
                    refreshed = time.monotonic()
                started = time.monotonic()
                statuses = list(
                    pool.map(lambda url: request(url, token), [args.url.rstrip("/")] * args.rps)
                )
                print(json.dumps({"time": time.time(), "statuses": statuses}), flush=True)
                time.sleep(max(0, 1 - (time.monotonic() - started)))
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
