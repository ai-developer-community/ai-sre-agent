"""Tiny shop with a repeatable deployment regression for the on-call demo."""

import json
import os
import random
import time
import uuid

from flask import Flask, g, jsonify, request


class PaymentConfigError(Exception):
    """Payment configuration introduced by a broken deployment."""


def create_app():
    app = Flask(__name__)
    fail_rate = float(os.getenv("FAIL_RATE", "0"))
    latency_ms = int(os.getenv("LATENCY_MS", "0"))
    version = os.getenv("APP_VERSION", "v1")
    if not 0 <= fail_rate <= 1 or not 0 <= latency_ms <= 10000:
        raise ValueError("FAIL_RATE must be 0..1; LATENCY_MS must be 0..10000")

    @app.before_request
    def begin_request():
        g.started = time.monotonic()
        g.request_id = str(uuid.uuid4())

    @app.after_request
    def log_request(response):
        print(
            json.dumps(
                {
                    "severity": "ERROR" if response.status_code >= 500 else "INFO",
                    "message": "PaymentConfigError: payment provider configuration is invalid"
                    if response.status_code >= 500
                    else "request completed",
                    "error_type": "PaymentConfigError" if response.status_code >= 500 else None,
                    "path": request.path,
                    "method": request.method,
                    "status": response.status_code,
                    "latency_ms": round((time.monotonic() - g.started) * 1000, 2),
                    "app_version": version,
                    "revision": os.getenv("K_REVISION", "local"),
                    "request_id": g.request_id,
                }
            ),
            flush=True,
        )
        return response

    @app.get("/health")
    def health():
        # Process liveness, deliberately not a claim that checkout works.
        return jsonify(status="ok", version=version)

    @app.get("/products")
    def products():
        return jsonify(products=[{"id": "coffee", "name": "On-call coffee", "price": 12}])

    @app.post("/checkout")
    def checkout():
        time.sleep(latency_ms / 1000)
        if random.random() < fail_rate:
            raise PaymentConfigError()
        return jsonify(status="paid", order_id=str(uuid.uuid4()), version=version)

    @app.errorhandler(PaymentConfigError)
    def payment_error(_error):
        return jsonify(
            error="PaymentConfigError",
            message="Payment provider configuration is invalid",
            version=version,
        ), 500

    return app


app = create_app()
