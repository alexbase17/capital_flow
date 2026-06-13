"""Capital-flow dashboard page and API routes."""

from __future__ import annotations

from flask import Flask, jsonify, render_template, request

from src.capital_flow.ai_summary import capital_flow_ai_summary
from src.capital_flow.service import capital_flow_payload


def register_capital_flow_routes(app: Flask) -> None:
    @app.route("/")
    def capital_flow_page():
        return render_template("capital_flow.html", title="资金流向")

    @app.route("/api/capital-flow")
    def api_capital_flow():
        try:
            payload = capital_flow_payload(
                force_refresh=request.args.get("refresh") == "1",
                window_key=request.args.get("window"),
            )
            return jsonify(payload)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/capital-flow/ai-summary")
    def api_capital_flow_ai_summary():
        try:
            force_refresh = request.args.get("refresh") == "1"
            payload = capital_flow_payload(
                force_refresh=force_refresh,
                window_key=request.args.get("window"),
            )
            return jsonify(
                {
                    "ai_summary": capital_flow_ai_summary(
                        payload,
                        use_deepseek=True,
                        use_cache=not force_refresh,
                    )
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502
