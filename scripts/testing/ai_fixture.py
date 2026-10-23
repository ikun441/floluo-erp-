"""Loopback-only protocol fixture; never imported by the ERP application or its Docker image."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def start():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            intent = {
                "operation": "query",
                "resource": "inventory",
                "arguments": {"query": "AI验证商品"},
                "references": {},
                "confidence": 0.95,
                "parser_source": "ai",
            }
            if "采购参数联调" in payload["messages"][1]["content"]:
                intent.update(
                    operation="create",
                    resource="purchase_orders",
                    arguments={"quantity": "3", "unit_price": "10.00"},
                )
            assert payload["response_format"] == {"type": "json_object"}
            response = json.dumps(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": json.dumps(intent, ensure_ascii=False)},
                        }
                    ]
                },
                ensure_ascii=False,
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
