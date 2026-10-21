"""The server answers only its own local page: no DNS rebinding, no requests sent by other web pages."""
import asyncio
import unittest
from unittest.mock import patch

import app as studio


def status(headers, method="GET", path="/missing-file"):
    """HTTP status for a request sent straight to the ASGI app: no network, no server, nothing written."""
    sent = []
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", studio.PORT),
             "headers": [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in headers.items()]}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(studio.app(scope, receive, send))
    return next(message["status"] for message in sent if message["type"] == "http.response.start")


class LocalAccessTests(unittest.TestCase):
    def test_own_local_page_is_served(self):
        for host in ("127.0.0.1:7863", "localhost:7863", "LOCALHOST:7863", "[::1]:7863", "127.0.0.1:18763"):
            self.assertEqual(status({"host": host}), 404, host)  # reaches the app: the file does not exist
        for origin in ("http://127.0.0.1:7863", "http://localhost:7863"):
            self.assertNotEqual(status({"host": "127.0.0.1:7863", "origin": origin}, "POST"), 403, origin)

    def test_foreign_host_names_are_refused(self):
        for host in ("attacker.example:7863", "127.0.0.1.attacker.example:7863", "localhost.attacker.example",
                     "evil@127.0.0.1:7863", "127.0.0.2:7863", ""):
            self.assertEqual(status({"host": host}), 403, host)
        self.assertEqual(status({}), 403)

    def test_other_web_pages_are_refused(self):
        for origin in ("https://attacker.example", "http://attacker.example:7863", "null",
                       "http://localhost.attacker.example:7863", "https://127.0.0.1:7863"):
            self.assertEqual(status({"host": "127.0.0.1:7863", "origin": origin}, "POST"), 403, origin)

    def test_refused_request_never_reaches_an_action(self):
        with patch.object(studio.worker, "stop") as stop:
            self.assertEqual(status({"host": "127.0.0.1:7863", "origin": "https://attacker.example"}, "POST",
                                    "/api/stop"), 403)
            self.assertEqual(status({"host": "attacker.example:7863"}, "POST", "/api/stop"), 403)
        stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
