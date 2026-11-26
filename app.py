import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

RECEIPTS = []


def get_kaggle_url():
    return (os.getenv("KAGGLE_API_URL") or "").strip().rstrip("/")


@app.route("/", methods=["GET"])
def home():
    kaggle_url = get_kaggle_url()
    return jsonify({
        "status": "AfterBuy backend running",
        "kaggle_connected": bool(kaggle_url),
        "kaggle_url": kaggle_url or None,
        "endpoints": [
            "POST /parse-receipt  — forward receipt image/text to Kaggle Gemma 3",
            "GET  /receipts       — list all saved receipts",
            "POST /receipts       — save a confirmed receipt",
            "DELETE /receipts/<id> — delete a receipt",
        ],
    })


@app.route("/parse-receipt", methods=["POST"])
def parse_receipt():
    kaggle_url = get_kaggle_url()
    if not kaggle_url:
        return jsonify({"error": "KAGGLE_API_URL is not set in .env"}), 503

    headers = {"ngrok-skip-browser-warning": "true"}
    target = f"{kaggle_url}/parse-receipt"

    try:
        if "file" in request.files:
            f = request.files["file"]
            if not f.filename:
                return jsonify({"error": "Empty filename."}), 400
            resp = requests.post(
                target,
                files={"file": (f.filename, f.stream, f.mimetype or "application/octet-stream")},
                headers=headers,
                timeout=90,
            )
        else:
            resp = requests.post(
                target,
                json=request.get_json(silent=True) or {},
                headers=headers,
                timeout=90,
            )

        data = resp.json()
        return jsonify(data), resp.status_code
    except requests.RequestException as e:
        return jsonify({"error": f"Failed to reach Kaggle API: {e}"}), 502
    except ValueError:
        return jsonify({"error": "Invalid JSON returned from Kaggle API."}), 502


@app.route("/receipts", methods=["GET"])
def get_receipts():
    return jsonify({"receipts": RECEIPTS, "count": len(RECEIPTS)})


@app.route("/receipts", methods=["POST"])
def save_receipt():
    body = request.get_json()
    if not body:
        return jsonify({"error": "Send JSON body with receipt fields."}), 400

    receipt = {
        "id": len(RECEIPTS) + 1,
        "product": body.get("product"),
        "seller": body.get("seller"),
        "purchase_date": body.get("purchase_date"),
        "invoice_number": body.get("invoice_number"),
        "amount": body.get("amount"),
        "return_days": body.get("return_days"),
        "warranty_months": body.get("warranty_months"),
    }
    RECEIPTS.append(receipt)
    return jsonify({"success": True, "receipt": receipt}), 201


@app.route("/receipts/<int:receipt_id>", methods=["DELETE"])
def delete_receipt(receipt_id):
    global RECEIPTS
    before = len(RECEIPTS)
    RECEIPTS = [r for r in RECEIPTS if r["id"] != receipt_id]
    if len(RECEIPTS) == before:
        return jsonify({"error": "Receipt not found."}), 404
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
