"""Servidor falso con la API de `llama-server`: /health y /v1/chat/completions.

Se usa en proceso (hilo) para probar el cliente y como ejecutable para probar el arranque:
`python falso_llama.py --port N ...`. Responde "Traducción de: <último párrafo del prompt>".
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class Manejador(BaseHTTPRequestHandler):
    respuesta_forzada: tuple[int, bytes] | None = None
    peticiones: list[dict[str, Any]] = []  # noqa: RUF012 - compartida a propósito
    salida: str | None = None
    """Texto fijo que devolver en lugar de «Traducción de: …»."""

    def do_GET(self) -> None:
        if self.path == "/health":
            self._responder(200, json.dumps({"status": "ok"}).encode())
        else:
            self._responder(404, b"{}")

    def do_POST(self) -> None:
        cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).peticiones.append(cuerpo)
        if self.respuesta_forzada is not None:
            self._responder(*self.respuesta_forzada)
            return
        prompt = cuerpo["messages"][0]["content"]
        texto = type(self).salida or f"Traducción de: {prompt.rsplit(chr(10), 1)[-1]}"
        if cuerpo.get("stream"):
            self._en_streaming(texto)
            return
        self._responder(200, json.dumps({"choices": [{"message": {"content": texto}}]}).encode())

    def _en_streaming(self, texto: str) -> None:
        """Eventos SSE como los de llama-server, una palabra por evento."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        palabras = texto.split(" ")
        eventos = [{"choices": [{"delta": {"role": "assistant"}}]}]
        trozos = [palabras[0], *(f" {p}" for p in palabras[1:])]
        eventos += [{"choices": [{"delta": {"content": trozo}}]} for trozo in trozos]
        try:
            for evento in eventos:
                self.wfile.write(f"data: {json.dumps(evento)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            pass  # el cliente ha cortado la conexión

    def _responder(self, codigo: int, cuerpo: bytes) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *_: object) -> None:
        pass


def en_hilo() -> tuple[ThreadingHTTPServer, str]:
    """Arranca el servidor falso en un hilo y devuelve el servidor y su URL."""
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor, f"http://127.0.0.1:{servidor.server_address[1]}"


if __name__ == "__main__":
    puerto = int(sys.argv[sys.argv.index("--port") + 1])
    ThreadingHTTPServer(("127.0.0.1", puerto), Manejador).serve_forever()
