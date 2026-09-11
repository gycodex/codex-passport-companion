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
from passport_console import Controller, Server, find_codex, running_codex_paths


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

    def test_authorization_requires_token_and_deduplicates_launch(self):
        with patch('console_setup.needs_setup', return_value=True), patch('console_setup.launch') as launch:
            self.assertEqual(self.request('/api/authorize', {})[0], 403)
            launch.assert_not_called()
            headers = {'X-Passport-Token': self.server.token}
            for _ in range(2):
                code, body = self.request('/api/authorize', {}, **headers)
                self.assertEqual(code, 200)
                self.assertTrue(json.loads(body)['restarting'])
            launch.assert_called_once()

    def test_exit_disconnects_before_acknowledging(self):
        with patch.object(self.controller, 'submit', wraps=self.controller.submit) as submit:
            code, _ = self.request('/api/exit', {}, **{'X-Passport-Token': self.server.token})
            self.assertEqual(code, 200)
            submit.assert_called_once_with('disconnect', {})
            self.assertEqual(self.controller.snapshot()['status'], 'disconnected')

    def test_windows_npm_launcher_resolves_to_native_executable(self):
        root = Path(self.temp.name)
        native = root / "npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/codex/codex.exe"
        native.parent.mkdir(parents=True)
        native.touch()
        native.chmod(0o700)
        with patch("passport_console.running_codex_paths", return_value=[]), patch("passport_console.sys.platform", "win32"), patch("passport_console.shutil.which", return_value=str(root / "npm/codex.cmd")), patch.dict("os.environ", {"APPDATA": str(root)}):
            self.assertEqual(find_codex(), str(native))

    def test_running_codex_takes_priority_over_path(self):
        native = Path(self.temp.name) / "codex.exe"
        native.touch()
        native.chmod(0o700)
        with patch("passport_console.running_codex_paths", return_value=[str(native)]), patch("passport_console.shutil.which") as lookup:
            self.assertEqual(find_codex(), str(native))
            lookup.assert_not_called()

    def test_process_detection_ignores_gui_other_users_and_exited_processes(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        import psutil
        def process(path, arguments, owner="me"):
            p = Mock()
            p.info = {"name": "codex.exe"}
            p.username.return_value = owner
            p.exe.return_value = path
            p.cmdline.return_value = arguments
            return p
        gui = process("C:/Apps/Codex.exe", ["Codex.exe"])
        other = process("C:/other/codex.exe", ["codex.exe", "app-server"], "other")
        cli = process("C:/my/codex.exe", ["codex.exe", "app-server"])
        exited = process("", [])
        exited.exe.side_effect = psutil.NoSuchProcess(123)
        with patch("psutil.Process") as current, patch("psutil.process_iter", return_value=[gui, other, exited, cli]):
            current.return_value.username.return_value = "me"
            self.assertEqual(running_codex_paths(), ["C:/my/codex.exe"])

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
