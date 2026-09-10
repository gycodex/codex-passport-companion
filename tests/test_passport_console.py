import asyncio
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from passport_console import Controller, Server


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.controller = Controller(Path(self.temp.name))
        self.server = Server(0, self.controller)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.controller.close()
        self.temp.cleanup()

    def request(self, path, data=None, **headers):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        client.request("GET" if data is None else "POST", path,
                       body=None if data is None else json.dumps(data), headers=headers)
        response = client.getresponse()
        status, body = response.status, response.read()
        client.close()
        return status, body

    def test_api_rejects_missing_token_foreign_origin_and_host(self):
        for headers in ({}, {"X-Passport-Token": self.server.token, "Origin": "https://evil.example"},
                        {"X-Passport-Token": self.server.token, "Host": "evil.example"}):
            self.assertEqual(self.request("/api/save", {}, **headers)[0], 403)
        self.assertEqual(self.request("/api/status")[0], 403)
        self.assertEqual(self.request("/", Host="evil.example")[0], 403)
        self.assertEqual(self.request("/../passport_console.py")[0], 404)

    def test_pairing_persists_but_never_appears_in_status(self):
        key = "ab" * 32
        status, _ = self.request("/api/save", {"host": "192.168.1.10", "pairing": {"key": key}}, **{"X-Passport-Token": self.server.token})
        self.assertEqual(status, 200)
        snapshot = self.controller.snapshot()
        self.assertTrue(snapshot["key_present"])
        self.assertNotIn(key, json.dumps(snapshot))
        self.assertEqual(json.loads((Path(self.temp.name) / "pairing.json").read_text())["key"], key)

    def test_invalid_inputs_do_not_save(self):
        for value in ({"port": 0}, {"pairing": {"key": "bad"}}, {"host": "8.8.8.8"}, {"autoconnect": "yes"}):
            with self.assertRaises(ValueError):
                self.controller.submit("save", value)
        self.assertFalse((Path(self.temp.name) / "settings.json").exists())

    def test_single_bridge_lifecycle_and_test_queue(self):
        starts, stops = [], []
        async def fake_bridge(args, control):
            starts.append(args)
            control.report("connected")
            try:
                await asyncio.Event().wait()
            finally:
                stops.append(True)
        with patch("passport_console.bridge_loop", fake_bridge):
            self.controller.submit("save", {"mode": "ble"})
            self.controller.submit("connect", {})
            self.controller.submit("connect", {})
            self.controller.submit("test", {})
            self.assertTrue(self.controller.take_test())
            self.assertFalse(self.controller.take_test())
            with self.assertRaises(ValueError):
                self.controller.submit("save", {"device": "other"})
            self.controller.submit("disconnect", {})
            self.assertEqual(len(starts), 1)
            self.assertEqual(len(stops), 1)
            self.assertEqual(self.controller.snapshot()["status"], "disconnected")
            with self.assertRaises(ValueError):
                self.controller.submit("test", {})


if __name__ == "__main__":
    unittest.main()
