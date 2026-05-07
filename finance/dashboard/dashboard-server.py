"""Dashboard HTTP server.

Serves static files from the vault root (same as `python -m http.server`) and
adds a `POST /api/refresh-prices` endpoint that runs the investment
calculate.py script and returns the result as JSON.

Usage:
    python 3-resources/tools/sb-os/finance/dashboard/dashboard-server.py [PORT]

Default port: 8080. Must be launched with the vault root as CWD.
"""

import json
import os
import subprocess
import sys
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


VAULT_ROOT = _find_vault_root()
CALCULATE_SCRIPT = VAULT_ROOT / "3-resources" / "tools" / "sb-os" / "finance" / "scripts" / "investimentos" / "calculate.py"


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path.rstrip("/") == "/api/refresh-prices":
            self._handle_refresh_prices()
            return
        self.send_error(404, "Not found")

    def _handle_refresh_prices(self):
        try:
            env = os.environ.copy()
            env["BOOKKEEPER_ACTOR"] = "dashboard_trigger"
            env["BOOKKEEPER_RUN_ID"] = str(uuid.uuid4())
            proc = subprocess.run(
                [sys.executable, str(CALCULATE_SCRIPT)],
                cwd=str(VAULT_ROOT),
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
            body = {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:],
            }
            status = 200 if proc.returncode == 0 else 500
        except subprocess.TimeoutExpired:
            body = {"ok": False, "error": "calculate.py timed out after 180s"}
            status = 504
        except Exception as e:
            body = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            status = 500

        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[dashboard-server] {self.address_string()} - {fmt % args}\n")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"Dashboard server listening on http://localhost:{port}")
    print(f"Vault root: {VAULT_ROOT}")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server.")
        server.server_close()


if __name__ == "__main__":
    main()
