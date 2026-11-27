import io
import os
import re
import html
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import PIL.Image
from pypdf import PdfReader

load_dotenv()

app = Flask(__name__)
CORS(app)

KAGGLE_API_URL = (os.getenv("KAGGLE_API_URL") or "").rstrip("/")
GOOGLE_CLIENT_ID = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
NGROK_HEADERS = {"ngrok-skip-browser-warning": "true"}

RECEIPTS = []


@app.route("/config", methods=["GET"])
def get_config():
    return jsonify({"google_client_id": GOOGLE_CLIENT_ID or None})


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


def _extract_pdf_text(raw_bytes):
    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception:
        return ""


def _extract_contacts(text):
    if not text:
        return None, None
    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    email = next((e for e in emails if not e.lower().endswith(("example.com", "example.org", "duckduckgo.com"))), None)
    phones = re.findall(r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3,5}\)?[\s.-]?)?\d{3,5}[\s.-]?\d{4}", text)
    phone = None
    for p in phones:
        digits = re.sub(r"\D", "", p)
        if 8 <= len(digits) <= 15:
            phone = re.sub(r"\s+", " ", p).strip()
            break
    return phone, email


def _web_lookup_support(seller, product):
    q = f"{seller or ''} {product or ''} customer care phone number support email".strip()
    if not q:
        return None, None
    try:
        r = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": q},
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            timeout=8,
        )
        if r.status_code == 200:
            clean = html.unescape(re.sub(r"<[^>]+>", " ", r.text))
            return _extract_contacts(clean)
    except Exception:
        pass
    return None, None


@app.route("/parse-receipt", methods=["POST"])
def parse_receipt():
    if not KAGGLE_API_URL:
        return jsonify({"error": "KAGGLE_API_URL is not configured in .env"}), 500

    try:
        pdf_phone, pdf_email = None, None
        if "file" in request.files:
            file = request.files["file"]
            if file.filename == "":
                return jsonify({"error": "Empty filename."}), 400
            raw_bytes = file.read()
            send_name = file.filename
            send_mime = file.mimetype or "application/octet-stream"
            if send_mime == "application/pdf" or send_name.lower().endswith(".pdf"):
                pdf_text = _extract_pdf_text(raw_bytes)
                pdf_phone, pdf_email = _extract_contacts(pdf_text)
                if not pdf_text:
                    return jsonify({"error": "Could not extract text from PDF."}), 400
                resp = requests.post(
                    f"{KAGGLE_API_URL}/parse-receipt",
                    json={"text": pdf_text[:6000]},
                    headers=NGROK_HEADERS,
                    timeout=90,
                )
            else:
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
            body = request.get_json(silent=True) or {}
            pdf_phone, pdf_email = _extract_contacts(body.get("text", ""))
            resp = requests.post(
                f"{KAGGLE_API_URL}/parse-receipt",
                json=body,
                headers=NGROK_HEADERS,
                timeout=90,
            )

        if resp.status_code >= 400:
            return jsonify({"error": f"Kaggle API returned {resp.status_code}", "detail": resp.text[:300]}), resp.status_code

        payload = resp.json()
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            if pdf_phone and not payload["data"].get("support_phone"):
                payload["data"]["support_phone"] = pdf_phone
            if pdf_email and not payload["data"].get("support_email"):
                payload["data"]["support_email"] = pdf_email
        return jsonify(payload)
    except requests.exceptions.Timeout:
        return jsonify({"error": "Kaggle Gemma 3 request timed out."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/warranty-assist", methods=["POST"])
def warranty_assist():
    body = request.get_json(silent=True) or {}
    product = (body.get("product") or "your product").strip()
    seller = (body.get("seller") or "the brand").strip()
    issue = (body.get("issue") or "hardware/functional defect").strip()
    phone = body.get("support_phone")
    email = body.get("support_email")
    source = "pdf" if (phone or email) else "fallback"

    if not phone or not email:
        w_phone, w_email = _web_lookup_support(seller, product)
        if w_phone and not phone:
            phone = w_phone
            source = "web"
        if w_email and not email:
            email = w_email
            source = "web"

    steps = [
        f"Keep your {product} invoice/receipt and product serial number ready.",
        f"Visit {seller}'s official warranty/support portal and register your {product} using the purchase date.",
        f"Select 'Warranty Claim / Service Request' and describe the issue: \"{issue}\".",
        "Attach your proof of purchase and submit to get a claim/ticket ID, then track pickup or service center visit.",
    ]

    if KAGGLE_API_URL:
        try:
            prompt = (
                f"Give 4 concise numbered steps to register and claim warranty for {product} bought from {seller} "
                f"for the issue: {issue}. Keep each step under 18 words."
            )
            r = requests.post(
                f"{KAGGLE_API_URL}/chat",
                json={"message": prompt, "receipts": []},
                headers=NGROK_HEADERS,
                timeout=15,
            )
            if r.status_code == 200 and r.json().get("reply"):
                lines = [re.sub(r"^\d+[\).\s-]+", "", ln).strip() for ln in r.json()["reply"].splitlines() if ln.strip()]
                if len(lines) >= 2:
                    steps = lines[:5]
        except Exception:
            pass

    return jsonify({
        "success": True,
        "steps": steps,
        "support_phone": phone,
        "support_email": email,
        "source": source,
    })


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
        "drive_file_id": body.get("drive_file_id"),
        "drive_file_name": body.get("drive_file_name"),
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
