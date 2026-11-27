import json
import os
import smtplib
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def _send(self, code, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(200, {"ok": True})

    def do_POST(self):
        sender = (os.environ.get("GMAIL_SENDER") or "amit.productivity047@gmail.com").strip()
        app_pw = (os.environ.get("GMAIL_APP_PASSWORD") or "").strip().replace(" ", "")
        if not app_pw:
            return self._send(500, {"error": "GMAIL_APP_PASSWORD is not configured on Vercel."})

        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._send(400, {"error": "Invalid JSON body."})

        to_addr = (data.get("to") or "").strip()
        alerts = data.get("items") or []
        if not to_addr or not alerts:
            return self._send(400, {"error": "Recipient email and items are required."})

        lines = ["Hi,", "", "Here are your upcoming AfterBuy return and warranty deadlines:", ""]
        for it in alerts:
            prod = it.get("product") or "Product"
            seller = it.get("seller") or "Seller"
            ret = it.get("return_days_left")
            war = it.get("warranty_days_left")
            parts = []
            if ret is not None and 0 <= ret <= 5:
                parts.append("Return closes today" if ret == 0 else f"Return closes in {ret} day(s)")
            if war is not None and 0 <= war <= 30:
                parts.append("Warranty ends today" if war == 0 else f"Warranty ends in {war} day(s)")
            if parts:
                lines.append(f"- {prod} ({seller}): " + " | ".join(parts))

        if len(lines) <= 4:
            return self._send(200, {"skipped": True})

        lines.extend(["", "Open AfterBuy to review your receipts or claim warranty.", "", "— AfterBuy"])
        msg = EmailMessage()
        msg["From"] = f"AfterBuy <{sender}>"
        msg["To"] = to_addr
        msg["Subject"] = "AfterBuy Alert: Return or Warranty Deadline Approaching"
        msg.set_content("\n".join(lines))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
                smtp.login(sender, app_pw)
                smtp.send_message(msg)
            return self._send(200, {"success": True, "sent_to": to_addr})
        except Exception as e:
            return self._send(500, {"error": str(e)})
