"""
Локальний сервер для тесту на рівень англійської мови.

Роздає ТІЛЬКИ index.html і приймає результати проходження тесту на
POST /save-result, зберігаючи їх у папку log/:
  - окремий JSON-файл на кожну спробу (log/result_ДАТА_ЧАС_xxxxxx.json)
  - зведений results.csv (легко відкрити в Excel)

Якщо поруч лежить cloudflared.exe (або він є в PATH), сервер сам піднімає
публічний тунель і показує посилання https://....trycloudflare.com, за яким
тест можна проходити з будь-якої мережі. Результати все одно падають у log/
на цьому комп'ютері.

Запуск: подвійний клік на start-test.bat (він сам відкриє браузер),
або вручну:  python server.py
"""

import atexit
import csv
import http.server
import json
import os
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import uuid
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
PUBLIC_URL_FILE = os.path.join(DIRECTORY, "public-url.txt")

LEVELS = ("A1", "A2", "B1", "B2")
MAX_BODY_BYTES = 4096
PAGES = {"/", "/index.html"}

write_lock = threading.Lock()


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


def _int_in(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError("bad number")
    return value


def clean_payload(data):
    """Return a sanitized copy of the client's result or raise ValueError.
    The endpoint is reachable from the internet, so nothing from the
    request is written to disk unless it has the exact expected shape."""
    if not isinstance(data, dict):
        raise ValueError("not an object")
    level = data.get("level")
    if level not in LEVELS:
        raise ValueError("bad level")
    by_level = data.get("byLevel")
    raw = data.get("raw")
    if not isinstance(by_level, dict) or not isinstance(raw, dict):
        raise ValueError("bad breakdown")
    return {
        "level": level,
        "totalCorrect": _int_in(data.get("totalCorrect"), 0, 1000),
        "total": _int_in(data.get("total"), 1, 1000),
        "overallPct": _int_in(data.get("overallPct"), 0, 100),
        "byLevel": {l: _int_in(by_level.get(l), 0, 100) for l in LEVELS},
        "raw": {
            l: {
                "correct": _int_in((raw.get(l) or {}).get("correct"), 0, 1000),
                "total": _int_in((raw.get(l) or {}).get("total"), 0, 1000),
            }
            for l in LEVELS
        },
    }


class Handler(http.server.SimpleHTTPRequestHandler):
    timeout = 15

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def send_head(self):
        # Serves GET and HEAD. Only the test page is public; log/, .git,
        # server.py etc. must never be reachable through the tunnel.
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path not in PAGES:
            self.send_error(404)
            return None
        self.path = "/index.html"
        return super().send_head()

    def _reply(self, code, body=b""):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/save-result":
            self._reply(404)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= MAX_BODY_BYTES:
                raise ValueError("bad length")
            data = clean_payload(json.loads(self.rfile.read(length).decode("utf-8")))
        except Exception:
            self._reply(400, b'{"ok": false}')
            return

        now = datetime.now()
        data["timestamp"] = now.isoformat(timespec="seconds")

        with write_lock:
            os.makedirs(LOG_DIR, exist_ok=True)

            # 1) окремий JSON-файл на кожну спробу
            file_ts = now.strftime("%Y-%m-%d_%H-%M-%S")
            json_path = os.path.join(LOG_DIR, f"result_{file_ts}_{uuid.uuid4().hex[:6]}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # 2) зведений CSV (додаємо рядок; заголовок пишемо один раз)
            csv_path = os.path.join(LOG_DIR, "results.csv")
            is_new = not os.path.exists(csv_path)
            by_level = data["byLevel"]
            raw = data["raw"]

            def raw_str(lvl):
                return f'{raw[lvl]["correct"]}/{raw[lvl]["total"]}'

            with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                if is_new:
                    writer.writerow([
                        "Дата і час", "Рівень", "Правильних", "Всього", "Загальний %",
                        "A1 %", "A2 %", "B1 %", "B2 %",
                        "A1 (прав/всього)", "A2 (прав/всього)", "B1 (прав/всього)", "B2 (прав/всього)",
                    ])
                writer.writerow([
                    data["timestamp"],
                    data["level"],
                    data["totalCorrect"],
                    data["total"],
                    data["overallPct"],
                    by_level["A1"], by_level["A2"], by_level["B1"], by_level["B2"],
                    raw_str("A1"), raw_str("A2"), raw_str("B1"), raw_str("B2"),
                ])

        self._reply(200, b'{"ok": true}')

    def log_message(self, fmt, *args):
        pass  # тихий консольний вивід


class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def find_cloudflared():
    local = os.path.join(DIRECTORY, "cloudflared.exe")
    return local if os.path.exists(local) else shutil.which("cloudflared")


def start_tunnel():
    """Start a Cloudflare quick tunnel to the local server, if cloudflared is
    available. Returns the subprocess or None."""
    exe = find_cloudflared()
    if not exe:
        return None
    try:
        if os.path.exists(PUBLIC_URL_FILE):
            os.remove(PUBLIC_URL_FILE)
    except OSError:
        pass

    proc = subprocess.Popen(
        [exe, "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    atexit.register(proc.terminate)

    def watch_output():
        announced = False
        for line in proc.stderr:
            m = re.search(r"https://([a-z0-9-]+)\.trycloudflare\.com", line)
            if announced or not m or m.group(1) == "api":
                continue
            announced = True
            url = m.group(0)
            with open(PUBLIC_URL_FILE, "w", encoding="utf-8") as f:
                f.write(url + "\n")
            print(flush=True)
            print("  >>> ПУБЛІЧНЕ ПОСИЛАННЯ (з будь-якої мережі):", flush=True)
            print(f"  >>> {url}", flush=True)
            print("  (також збережено у public-url.txt; воно змінюється при кожному запуску)", flush=True)
        if not announced:
            print(flush=True)
            print("  !!! Тунель не піднявся (cloudflared завершився без посилання).", flush=True)
            print("  !!! Імовірно, ваша мережа блокує api.trycloudflare.com.", flush=True)
            print("  !!! Тест і далі працює локально та в межах цієї Wi-Fi мережі.", flush=True)

    threading.Thread(target=watch_output, daemon=True).start()
    return proc


if __name__ == "__main__":
    os.makedirs(LOG_DIR, exist_ok=True)
    lan_ip = get_lan_ip()
    # Bind to 0.0.0.0 so other devices on the same Wi-Fi/network can open
    # the test too — not just this computer.
    with ThreadedServer(("0.0.0.0", PORT), Handler) as httpd:
        print("=" * 60, flush=True)
        print("Тест запущено!", flush=True)
        print(f"  На цьому комп'ютері:   http://localhost:{PORT}/", flush=True)
        print(f"  Для інших у цій мережі: http://{lan_ip}:{PORT}/", flush=True)
        print(f"Результати зберігаються тут: {LOG_DIR}", flush=True)
        if find_cloudflared():
            print("Піднімаю публічний тунель, зачекайте кілька секунд...", flush=True)
        else:
            print("cloudflared.exe не знайдено: тест доступний лише в локальній мережі.", flush=True)
        print("Щоб зупинити сервер, закрийте це вікно.", flush=True)
        print("=" * 60, flush=True)
        start_tunnel()
        httpd.serve_forever()
