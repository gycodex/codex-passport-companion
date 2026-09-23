"""Desktop lifecycle tests; no UI, hardware, account or startup registry changes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from passport_console import Controller, Server
from passport_desktop import Backend, Desktop


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.controller = Controller(Path(self.temp.name))
        self.server = Server(0, self.controller)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = Backend(self.server.server_port, Path(self.temp.name))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.controller.close()
        self.temp.cleanup()

    def test_attach_reuses_existing_backend_without_spawning(self):
        with patch("passport_desktop.subprocess.Popen") as spawn:
            self.client.start()
            spawn.assert_not_called()
        state, changed = self.client.status()
        self.assertEqual(state["status"], "disconnected")
        self.assertFalse(changed)

    def test_authorized_backend_token_rotation_recovers(self):
        self.client.start()
        self.server.token = "new-generation-token"
        state, changed = self.client.status()
        self.assertTrue(changed)
        self.assertEqual(state["status"], "disconnected")
        self.assertEqual(self.client.token, self.server.token)
        self.assertFalse(self.client.status()[1])

    def test_exit_disconnects_service(self):
        self.client.start()
        with patch.object(self.controller, "submit", wraps=self.controller.submit) as submit:
            self.client.stop()
            submit.assert_called_once_with("disconnect", {}, timeout=5)
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())

    def test_foreign_service_is_not_started_over_or_stopped(self):
        with patch.object(self.client, "request", return_value={"app": "other"}), \
             patch("passport_desktop.subprocess.Popen") as spawn:
            with self.assertRaises(ValueError):
                self.client.start()
            spawn.assert_not_called()
            with self.assertRaises(ValueError):
                self.client.stop()

    def test_old_backend_requires_upgrade_without_stopping_it(self):
        with patch.object(self.client, "request", return_value={"app": "passport-companion-console"}) as request, \
             patch("passport_desktop.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "旧版"):
                self.client.start()
            request.assert_called_once_with("health")
            spawn.assert_not_called()

    def test_unresponsive_owned_backend_is_terminated(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("backend", 2), 0]
        self.client.process = process
        with patch.object(self.client, "attach", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                self.client.stop()
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    def test_owned_backend_is_killed_if_terminate_stalls(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("backend", 2),
                                    subprocess.TimeoutExpired("backend", 2), 0]
        self.client.process = process
        with patch.object(self.client, "attach", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                self.client.stop()
        process.terminate.assert_called_once()
        process.kill.assert_called_once()


class DesktopLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.desktop = Desktop(Mock(), Mock())
        self.desktop.window = Mock()

    def test_close_hides_only_when_tray_is_available(self):
        self.desktop.tray_ready = True
        self.assertFalse(self.desktop.closing())
        self.desktop.window.hide.assert_called_once()
        self.desktop.backend.stop.assert_not_called()

    def test_exit_waits_for_disconnect_before_destroying_window(self):
        calls = []
        self.desktop.backend.stop.side_effect = lambda: calls.append("disconnect")
        self.desktop.window.destroy.side_effect = lambda: calls.append("destroy")
        self.desktop.quit()
        self.assertEqual(calls, ["disconnect", "destroy"])
        self.assertTrue(self.desktop.finished.is_set())
        self.assertIsNone(self.desktop.closing())

    def test_failed_backend_stop_still_closes_window(self):
        self.desktop.backend.stop.side_effect = OSError("busy")
        with patch("traceback.print_exc"):
            self.desktop.quit()
        self.assertTrue(self.desktop.finished.is_set())
        self.desktop.window.destroy.assert_called_once()


class SetupPersistenceTests(unittest.TestCase):
    def test_setup_requires_live_sync_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(Path(directory))
            try:
                self.assertEqual(controller.config["mode"], "lan")
                self.assertFalse(controller.config["setup_complete"])
                controller.submit("save", {"setup_complete": True})
                self.assertFalse(controller.config["setup_complete"])
                with self.assertRaises(ValueError):
                    controller.submit("finish_setup", {})
                controller.report("connected")
                with self.assertRaises(ValueError):
                    controller.submit("finish_setup", {})
                controller.report("connected", synced_at=123)
                controller.submit("finish_setup", {})
            finally:
                controller.close()
            restored = Controller(Path(directory))
            try:
                self.assertTrue(restored.config["setup_complete"])
            finally:
                restored.close()

    def test_existing_user_keeps_transport_and_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "settings.json").write_text(json.dumps({
                "mode": "lan", "host": "192.168.1.50", "autoconnect": False}), encoding="utf-8")
            controller = Controller(Path(directory))
            try:
                self.assertTrue(controller.config["setup_complete"])
                self.assertEqual(controller.config["mode"], "lan")
                self.assertEqual(controller.config["host"], "192.168.1.50")
                self.assertFalse(controller.config["autoconnect"])
            finally:
                controller.close()


if __name__ == "__main__":
    unittest.main()
