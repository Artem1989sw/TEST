"""
Локальний сервер для тесту на рівень англійської мови.

Роздає english-test.html і приймає результати проходження тесту на
POST /save-result, зберігаючи їх у папку log/:
  - окремий JSON-файл на кожну спробу (log/result_ДАТА_ЧАС.json)
  - зведений results.csv (легко відкрити в Excel)

Запуск: подвійний клік на start-test.bat (він сам відкриє браузер),
або вручну:  python server.py
"""

import csv
import http.server
import json
import os
import socket
import socketserver
import sys
from datetime import datetime

# Force UTF-8 console output so Ukrainian text prints correctly regardless
# of the Windows console's default codepage (paired with `chcp 65001` in
# start-test.bat).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

PORT = 8000
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(DIRECTORY, "log")


def get_lan_ip():
    """Best-effort local network IP (the address other devices on the
    same Wi-Fi/router should use), without actually sending anything."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        if self.path in ("", "/"):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if self.path != "/save-result":
            self.send_response(404)
            self.end_headers()
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body.decode("utf-8"))
        except Exception:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"ok": false}')
            return

        os.makedirs(LOG_DIR, exist_ok=True)

        now = datetime.now()
        data.setdefault("timestamp", now.isoformat(timespec="seconds"))

        # 1) окремий JSON-файл на кожну спробу
        file_ts = now.strftime("%Y-%m-%d_%H-%M-%S")
        json_path = os.path.join(LOG_DIR, f"result_{file_ts}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 2) зведений CSV (додаємо рядок; заголовок пишемо один раз)
        csv_path = os.path.join(LOG_DIR, "results.csv")
        is_new = not os.path.exists(csv_path)
        by_level = data.get("byLevel", {})
        raw = data.get("raw", {})

        def raw_str(lvl):
            r = raw.get(lvl) or {}
            return f'{r.get("correct", "")}/{r.get("total", "")}'

        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            if is_new:
                writer.writerow([
                    "Дата і час", "Рівень", "Правильних", "Всього", "Загальний %",
                    "A1 %", "A2 %", "B1 %", "B2 %",
                    "A1 (прав/всього)", "A2 (прав/всього)", "B1 (прав/всього)", "B2 (прав/всього)",
                ])
            writer.writerow([
                data.get("timestamp", ""),
                data.get("level", ""),
                data.get("totalCorrect", ""),
                data.get("total", ""),
                data.get("overallPct", ""),
                by_level.get("A1", ""),
                by_level.get("A2", ""),
                by_level.get("B1", ""),
                by_level.get("B2", ""),
                raw_str("A1"),
                raw_str("A2"),
                raw_str("B1"),
                raw_str("B2"),
            ])

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, fmt, *args):
        pass  # тихий консольний вивід


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    os.makedirs(LOG_DIR, exist_ok=True)
    lan_ip = get_lan_ip()
    # Bind to 0.0.0.0 so other devices on the same Wi-Fi/network can open
    # the test too — not just this computer.
    with ReusableTCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print("=" * 60, flush=True)
        print("Тест запущено!", flush=True)
        print(f"  На цьому комп'ютері:   http://localhost:{PORT}/", flush=True)
        print(f"  Для інших у цій мережі: http://{lan_ip}:{PORT}/", flush=True)
        print(flush=True)
        print("Надішліть друге посилання тим, хто проходитиме тест", flush=True)
        print("(вони мають бути підключені до цього самого Wi-Fi/мережі).", flush=True)
        print(f"Результати зберігаються тут: {LOG_DIR}", flush=True)
        print("Щоб зупинити сервер, закрийте це вікно.", flush=True)
        print("=" * 60, flush=True)
        httpd.serve_forever()
