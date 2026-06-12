"""Standalone capital-flow dashboard app."""

from __future__ import annotations

from flask import Flask

from src.capital_flow.routes import register_capital_flow_routes
from src.static_assets import static_url


app = Flask(__name__, template_folder="templates", static_folder="static")


@app.context_processor
def inject_static_helpers():
    return {"static_url": static_url}


def initialize_app() -> None:
    # Kept for parity with the portfolio app start script. This service is read-only.
    return None


register_capital_flow_routes(app)


if __name__ == "__main__":
    initialize_app()
    app.run(debug=False, port=5083, host="0.0.0.0")
