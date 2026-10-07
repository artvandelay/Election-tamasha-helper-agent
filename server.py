#!/usr/bin/env python3
"""Election Tamasha rules helper.

Serves the rulebook and a small English chat. The OpenRouter key is read
from the environment or from .env in this directory. It is never written
into the page.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
ENV_PATH = ROOT / ".env"
DEFAULT_MODEL = "~deepseek/deepseek-flash-latest"
MAX_HISTORY = 8
MAX_MESSAGE = 2000
MAX_POSITION = 80

def load_prompts() -> tuple[str, str]:
    path = (ROOT / "prompt.txt") if (ROOT / "prompt.txt").is_file() else (STATIC / "prompt.txt")
    if not path.is_file():
        raise RuntimeError("prompt.txt not found.")
    raw = path.read_text(encoding="utf-8")
    parts = raw.split("=== CLOSING RULES ===")
    system = parts[0].replace("=== SYSTEM RULES ===", "").strip()
    closing = parts[1].strip() if len(parts) > 1 else ""
    return system, closing


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._capture = False
        self._depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        attr = dict(attrs)
        if tag == "main" and attr.get("id") == "rulebook":
            self._capture = True
            self._depth = 1
            return
        if not self._capture:
            return
        self._depth += 1
        if tag in {"h1", "h2", "h3"}:
            self.parts.append("\n\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in {"p", "tr"}:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if not self._capture:
            return
        self._depth -= 1
        if self._depth <= 0:
            self._capture = False

    def handle_data(self, data: str) -> None:
        if self._capture:
            self.parts.append(data)


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def rulebook_text() -> str:
    path = (STATIC / "rules.html") if (STATIC / "rules.html").is_file() else (ROOT / "rules.html")
    html = path.read_text(encoding="utf-8")
    parser = TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


RULEBOOK = ""


# Blank or these words mean the player did not say. They are not a default.
_UNSET = {
    "",
    "unspecified",
    "not specified",
    "none",
    "n/a",
    "na",
    "—",
    "-",
    "–",
}


def position_block(position: dict) -> str:
    """Version, phase, and side only. notes are ignored if the client still sends them."""
    if not isinstance(position, dict):
        position = {}
    labels = {
        "version": "Version",
        "phase": "Phase",
        "side": "Who is asking",
    }
    lines = []
    for key, label in labels.items():
        value = str(position.get(key) or "").strip()
        if value.lower() in _UNSET:
            continue
        lines.append(f"{label}: {value[:MAX_POSITION]}")
    if not lines:
        return (
            "Game position: the player did not say a version, phase, or side. "
            "That is not a default. Do not assume Basic, Purple, Prachar, or anything else. "
            "If the question is general, answer it and do not ask for the board. "
            "If they ask about playing an Attack, Victim, or Faction card, ask which version "
            "in one short question. Do not say yes or no."
        )
    return (
        "Game position the player set. Use these facts and do not ask again for them. "
        "Any of version, phase, or side missing below was not said. Do not assume it. "
        "If version is missing and they ask about an Attack, Victim, or Faction card, "
        "ask which version. Do not say yes or no.\n"
        + "\n".join(lines)
    )


def chat(message: str, position: dict, history: list) -> tuple[str, str]:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is missing. Put it in .env beside server.py.")
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    # Every request gets the full rulebook string. No summary, no passage pick, no retrieval.
    if len(RULEBOOK) < 1000:
        raise RuntimeError("The full rulebook is not loaded.")
    system_rules, closing_rules = load_prompts()
    system = system_rules + "\n\nRULEBOOK:\n" + RULEBOOK + "\n\n" + closing_rules
    if RULEBOOK not in system or len(system) <= len(RULEBOOK):
        raise RuntimeError("Chat must send the whole rulebook.")
    messages = [
        {"role": "system", "content": system},
    ]
    for turn in (history[-MAX_HISTORY:] if isinstance(history, list) else []):
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:MAX_MESSAGE]})
    messages.append(
        {
            "role": "user",
            "content": position_block(position) + "\n\nQuestion:\n" + message[:MAX_MESSAGE],
        }
    )
    payload = json.dumps(
        {
            "model": model,
            "temperature": 0.2,
            "max_tokens": 700,
            "messages": messages,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://127.0.0.1:8787",
            "X-Title": "Election Tamasha Rules Helper",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"OpenRouter returned {exc.code}. {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach OpenRouter. {exc.reason}") from exc
    try:
        answer = body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise RuntimeError("OpenRouter sent a response without an answer.") from exc
    return answer, model


class Handler(BaseHTTPRequestHandler):
    server_version = "ElectionTamashaRules/0.1"

    def log_message(self, fmt: str, *args) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        secret = os.environ.get("CHAT_SECRET", "").strip()
        if not secret:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {secret}"

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self._json(200, {"ok": True, "model": os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)})
            return
        routes = {
            "/": "index.html",
            "/index.html": "index.html",
            "/rules": "rules.html",
            "/rules.html": "rules.html",
            "/logo.svg": "logo.svg",
            "/home-box.webp": "home-box.webp",
            "/prompt.txt": "prompt.txt",
        }
        rel = routes.get(path)
        if rel is None:
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        file_path = (STATIC / rel) if (STATIC / rel).is_file() else (ROOT / rel)
        if not file_path.is_file():
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        kind = {
            ".html": "text/html; charset=utf-8",
            ".svg": "image/svg+xml",
            ".webp": "image/webp",
            ".txt": "text/plain; charset=utf-8",
        }.get(file_path.suffix, "application/octet-stream")
        self._send(200, file_path.read_bytes(), kind)

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/chat":
            self._json(404, {"error": "Not found"})
            return
        if not self._authorized():
            self._json(401, {"error": "Unauthorized"})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 100_000:
            self._json(413, {"error": "Message is too large"})
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"error": "Send JSON"})
            return
        message = str(data.get("message") or "").strip()
        if not message:
            self._json(400, {"error": "Ask a question"})
            return
        history = data.get("history") if isinstance(data.get("history"), list) else []
        position = data.get("position") if isinstance(data.get("position"), dict) else {}
        try:
            answer, model = chat(message, position, history)
        except RuntimeError as exc:
            self._json(502, {"error": str(exc)})
            return
        self._json(200, {"answer": answer, "model": model})


def main() -> None:
    global RULEBOOK
    load_env(ENV_PATH)
    RULEBOOK = rulebook_text()
    if len(RULEBOOK) < 1000:
        raise SystemExit("Rulebook text did not extract. Refusing to start.")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8787"))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Rules helper on http://{host}:{port}  model={os.environ.get('OPENROUTER_MODEL', DEFAULT_MODEL)}")
    print(f"Rulebook characters: {len(RULEBOOK)}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
