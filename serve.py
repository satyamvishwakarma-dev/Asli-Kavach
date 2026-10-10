"""Tiny local web server for the Asli Kavach page (serves this folder on http://127.0.0.1:8000).
Plain 'python -m http.server' can send .js files with the wrong type on some Windows PCs,
which stops the page from loading its local Gradio client. This one always sends the right type."""
import http.server
import os
import socketserver

os.chdir(os.path.dirname(os.path.abspath(__file__)))


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".js": "text/javascript", ".mjs": "text/javascript", ".html": "text/html"}

    def log_message(self, *args):          # keep the window quiet
        pass


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", 8000), Handler) as server:
    print("Page server running: http://127.0.0.1:8000/asli_kavach.html   (Ctrl+C to stop)")
    server.serve_forever()
