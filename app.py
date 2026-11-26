import io
import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import PIL.Image

load_dotenv()

app = Flask(__name__)
CORS(app)

KAGGLE_API_URL = (os.getenv("KAGGLE_API_URL") or "").rstrip("/")
NGROK_HEADERS = {"ngrok-skip-browser-warning": "true"}

RECEIPTS = []


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "AfterBuy backend running",
        "kaggle_url": KAGGLE_API_URL or None,
        "endpoints": [
            "POST /parse-receipt  — forward receipt image/text to Kaggle Gemma 3",
            "POST /draft-email    — draft support email via Kaggle Gemma 3",
            "POST /chat           — chat with saved receipts via Kaggle Gemma 3",
            "GET  /receipts       — list all saved receipts",
            "POST /receipts       — save a confirmed receipt",
            "DELETE /receipts/<id> — delete a receipt",
        ],
    })


@app.route("/parse-receipt", methods=["POST"])
def parse_receipt():
    if not KAGGLE_API_URL:
        return jsonify({"error": "KAGGLE_API_URL is not configured in .env"}), 500

    try:
        if "file" in request.files:
            file = request.files["file"]
            if file.filename == "":
                return jsonify({"error": "Empty filename."}), 400
            raw_bytes = file.read()
            send_name = file.filename
            send_mime = file.mimetype or "application/octet-stream"
            if send_mime.startswith("image/"):
                img = PIL.Image.open(io.BytesIO(raw_bytes)).convert("RGB")
                img.thumbnail((1024, 1024))
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=90)
                raw_bytes = buf.getvalue()
                send_name = "receipt.jpg"
                send_mime = "image/jpeg"
            resp = requests.post(
                f"{KAGGLE_API_URL}/parse-receipt",
                files={"file": (send_name, io.BytesIO(raw_bytes), send_mime)},
                headers=NGROK_HEADERS,
                timeout=90,
            )
        else:
            resp = requests.post(
                f"{KAGGLE_API_URL}/parse-receipt",
                json=request.get_json(silent=True) or {},
                headers=NGROK_HEADERS,
                timeout=90,
            )

        if resp.status_code >= 400:
            return jsonify({"error": f"Kaggle API returned {resp.status_code}", "detail": resp.text[:300]}), resp.status_code

        return jsonify(resp.json())
    except requests.exceptions.Timeout:
        return jsonify({"error": "Kaggle Gemma 3 request timed out."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/draft-email", methods=["POST"])
def draft_email():
    if not KAGGLE_API_URL:
        return jsonify({"error": "KAGGLE_API_URL is not configured in .env"}), 500
    try:
        resp = requests.post(
            f"{KAGGLE_API_URL}/draft-email",
            json=request.get_json(silent=True) or {},
            headers=NGROK_HEADERS,
            timeout=90,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chat", methods=["POST"])
def chat():
    if not KAGGLE_API_URL:
        return jsonify({"error": "KAGGLE_API_URL is not configured in .env"}), 500
    try:
        resp = requests.post(
            f"{KAGGLE_API_URL}/chat",
            json=request.get_json(silent=True) or {},
            headers=NGROK_HEADERS,
            timeout=90,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/receipts", methods=["GET"])
def get_receipts():
    return jsonify({"receipts": RECEIPTS, "count": len(RECEIPTS)})


@app.route("/receipts", methods=["POST"])
def save_receipt():
    body = request.get_json(silent=True)
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
