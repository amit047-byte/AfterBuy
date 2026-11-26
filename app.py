import os
import json
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import google.generativeai as genai
import PIL.Image

load_dotenv()

app = Flask(__name__)
CORS(app)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

RECEIPTS = []

PROMPT = """You are a receipt parser. Extract the following fields from this receipt image and return ONLY valid JSON (no markdown, no explanation):
{
  "product": "product name",
  "seller": "store or seller name",
  "purchase_date": "YYYY-MM-DD",
  "invoice_number": "invoice or order number or null",
  "amount": "total amount as string or null",
  "return_days": null or number of days for return window,
  "warranty_months": null or number of months of warranty
}
If a field is not found, use null. Do not include any text outside the JSON."""


@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "AfterBuy backend running", "endpoints": [
        "POST /parse-receipt  — upload receipt image, get parsed JSON",
        "GET  /receipts       — list all saved receipts",
        "POST /receipts       — save a confirmed receipt",
        "DELETE /receipts/<id> — delete a receipt"
    ]})


@app.route("/parse-receipt", methods=["POST"])
def parse_receipt():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded. Send a file field named 'file'."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename."}), 400

    try:
        image = PIL.Image.open(file.stream)
        response = model.generate_content([image, PROMPT])
        raw = response.text.strip()

        # Strip markdown code fences if Gemini wraps in ```json ... ```
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        data = json.loads(raw)
        return jsonify({"success": True, "data": data})

    except json.JSONDecodeError:
        return jsonify({"error": "Could not parse Gemini response as JSON.", "raw": raw}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
