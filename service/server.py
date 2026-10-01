"""brief-engine: HTTP wrapper around renderer/build_brief.py for n8n.
POST /render  {"as_of": "YYYY-MM-DD", "pulls": {"<name>": {...}}}  ->
  {"ok": true, "as_of", "pages", "divisions", "flags": [...], "warnings": [...], "pdf_base64", "markdown", "payload"}
GET  /health  -> {"ok": true}
Stdlib only besides reportlab + pypdf. No storage, no credentials, no network calls of its own."""
import base64, json, os, subprocess, sys, tempfile, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
RENDERER = os.environ.get("RENDERER_DIR", os.path.join(os.path.dirname(HERE), "renderer"))
sys.path.insert(0, HERE)
from to_markdown import render as to_md

def page_count(pdf_path):
    try:
        from pypdf import PdfReader
        return len(PdfReader(pdf_path).pages)
    except Exception:
        data = open(pdf_path, "rb").read()
        return data.count(b"/Type /Page") - data.count(b"/Type /Pages")

def do_render(req):
    as_of = req["as_of"]
    pulls = req.get("pulls") or {}
    if not pulls:
        raise ValueError("no pulls in request")
    with tempfile.TemporaryDirectory(prefix="brief-") as tmp:
        pdir = os.path.join(tmp, "pulls"); os.makedirs(pdir)
        for name, obj in pulls.items():
            with open(os.path.join(pdir, f"{name}.json"), "w") as f:
                json.dump(obj, f)
        out_pdf = os.path.join(tmp, f"Wyatt Portfolio Brief {as_of}.pdf")
        cmd = [sys.executable, os.path.join(RENDERER, "build_brief.py"), pdir, as_of, out_pdf]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=RENDERER)
        warnings = [ln for ln in (proc.stderr or "").splitlines() if "WARN" in ln]
        if proc.returncode != 0 or not os.path.exists(out_pdf):
            return {"ok": False, "as_of": as_of, "error": f"engine exit {proc.returncode}",
                    "stderr": (proc.stderr or "")[-4000:], "stdout": (proc.stdout or "")[-2000:]}
        payload = json.load(open(os.path.splitext(out_pdf)[0] + ".payload.json"))
        flags = []
        for div in payload.get("divisions", []):
            for b in div.get("blocks", []):
                if b.get("kind") == "flags":
                    for it in b.get("items", []):
                        flags.append({"division": div.get("title"), "flag": (list(it) + [""])[0], "detail": (list(it) + ["", ""])[1]})
        pdf_b64 = base64.b64encode(open(out_pdf, "rb").read()).decode("ascii")
        return {"ok": True, "as_of": as_of, "pages": page_count(out_pdf), "divisions": len(payload.get("divisions", [])),
                "flags": flags, "warnings": warnings, "pdf_base64": pdf_b64, "markdown": to_md(payload), "payload": payload,
                "engine_stdout": (proc.stdout or "")[-2000:]}

class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        self._send(200 if self.path == "/health" else 404, {"ok": self.path == "/health", "service": "brief-engine"})
    def do_POST(self):
        if self.path != "/render":
            return self._send(404, {"ok": False, "error": "unknown path"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n).decode())
            res = do_render(req)
            self._send(200 if res.get("ok") else 422, res)
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e), "trace": traceback.format_exc()[-3000:]})
    def log_message(self, fmt, *args):
        sys.stderr.write("brief-engine " + (fmt % args) + "\n")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"brief-engine listening on :{port}, renderer={RENDERER}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
