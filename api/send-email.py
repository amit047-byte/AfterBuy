import json
import os
import urllib.request
import urllib.error
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
        api_key = (os.environ.get("RESEND_API_KEY") or "").strip()
        if not api_key:
            return self._send(500, {"error": "RESEND_API_KEY is not configured on Vercel."})

        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._send(400, {"error": "Invalid JSON body."})

        to_addr = (data.get("to") or "").strip()
        subject = (data.get("subject") or "").strip()
        body = (data.get("body") or "").strip()
        reply_to = (data.get("reply_to") or "").strip()
        if not to_addr or not subject or not body:
            return self._send(400, {"error": "Recipient email, subject, and body are required."})

        payload = {
            "from": (os.environ.get("RESEND_FROM") or "AfterBuy <onboarding@resend.dev>").strip(),
            "to": [to_addr],
            "subject": subject,
            "text": body,
        }
        if reply_to:
            payload["reply_to"] = reply_to

        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                res_json = json.loads(resp.read().decode("utf-8") or "{}")
                return self._send(200, {"success": True, "id": res_json.get("id")})
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            try:
                msg = json.loads(err_body).get("message") or f"Resend error {e.code}"
            except Exception:
                msg = f"Resend error {e.code}"
            return self._send(e.code, {"error": msg})
        except Exception as e:
            return self._send(500, {"error": str(e)})
