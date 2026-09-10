import asyncio
import importlib.util
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "tools" / "codex_bridge.py"
SPEC = importlib.util.spec_from_file_location("codex_bridge", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
codex_bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(codex_bridge)


class CodexBridgeTests(unittest.TestCase):
    def test_app_server_reads_large_jsonl_response(self) -> None:
        script = (
            "import json, sys\n"
            "for line in sys.stdin:\n"
            "    request = json.loads(line)\n"
            "    if 'id' in request:\n"
            "        print(json.dumps({'id': request['id'], "
            "'result': {'metadata': 'x' * 100000}}), flush=True)\n"
        )
        create_process = asyncio.create_subprocess_exec

        async def fake_server(*args, **kwargs):
            return await create_process(sys.executable, "-u", "-c", script, **kwargs)

        async def check():
            server = codex_bridge.CodexAppServer()
            try:
                await server.start()
                result = await server.request("thread/list")
                self.assertEqual(len(result["metadata"]), 100000)
            finally:
                await server.close()

        with patch.object(codex_bridge.asyncio, "create_subprocess_exec", fake_server):
            asyncio.run(check())

    def test_lan_adapter_removes_only_the_ble_line_terminator(self) -> None:
        received = []
        class Client:
            async def send_payload(self, payload):
                received.append(payload)
        for payload in (b'{"time":[1,0]}\n', b'{"time":[1,0]}\r\n', b'{"time":[1,0]}'):
            asyncio.run(codex_bridge.send_payload(Client(), payload))
        self.assertEqual(received, [b'{"time":[1,0]}'] * 3)

    def test_weekly_only_window_is_not_relabelled_as_five_hours(self) -> None:
        result = codex_bridge.normalize_rate_limits({"rateLimits": {
            "primary": {"usedPercent": 36, "windowDurationMins": 10080,
                        "resetsAt": 1234}, "secondary": None}})
        self.assertTrue(result["available"])
        self.assertEqual(result["primary"],
                         {"used": 36, "duration": 10080, "reset": 1234})
        self.assertEqual(result["secondary"]["duration"], 0)

    def test_normalizes_codex_bucket(self) -> None:
        result = codex_bridge.normalize_rate_limits(
            {
                "rateLimitsByLimitId": {
                    "codex": {
                        "planType": "plus",
                        "primary": {
                            "usedPercent": 12,
                            "windowDurationMins": 300,
                            "resetsAt": 123,
                        },
                        "secondary": {
                            "usedPercent": 62,
                            "windowDurationMins": 10080,
                            "resetsAt": 456,
                        },
                    }
                }
            }
        )
        self.assertEqual(result["plan"], "plus")
        self.assertEqual(result["primary"]["used"], 12)
        self.assertEqual(result["secondary"]["duration"], 10080)
        self.assertTrue(result["available"])

    def test_session_watcher_uses_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            session = home / "sessions" / "2026" / "01" / "01" / "run.jsonl"
            session.parent.mkdir(parents=True)
            session.write_text("", encoding="utf-8")
            watcher = codex_bridge.SessionWatcher(home)
            with session.open("a", encoding="utf-8") as stream:
                stream.write(
                    '{"type":"response_item","payload":{"type":"message",'
                    '"role":"user","content":[{"private":"ignored"}]}}\n'
                )
            self.assertTrue(watcher.poll())
            self.assertTrue(watcher.running)
            with session.open("a", encoding="utf-8") as stream:
                stream.write(
                    '{"type":"response_item","payload":{"type":"message",'
                    '"role":"assistant","phase":"final_answer",'
                    '"content":[{"private":"ignored"}]}}\n'
                )
            self.assertTrue(watcher.poll())
            self.assertFalse(watcher.running)
            self.assertEqual(watcher.completion_sequence, 1)

    def test_usage_cache_keeps_last_valid_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.json"
            usage = {
                "plan": "plus",
                "primary": {"used": 30, "duration": 300, "reset": 123},
                "secondary": {"used": 6, "duration": 10080, "reset": 456},
                "available": True,
            }
            codex_bridge.save_cached_usage(path, usage)
            self.assertEqual(codex_bridge.load_cached_usage(path), usage)

            codex_bridge.save_cached_usage(path, codex_bridge.normalize_rate_limits({}))
            self.assertEqual(codex_bridge.load_cached_usage(path), usage)

    def test_expired_usage_window_rolls_into_next_period(self) -> None:
        usage = {
            "plan": "plus",
            "primary": {"used": 87, "duration": 300, "reset": 1_000},
            "secondary": {"used": 14, "duration": 10080, "reset": 900_000},
            "available": True,
        }
        self.assertTrue(codex_bridge.roll_expired_usage_windows(usage, now=1_060))
        self.assertEqual(usage["primary"]["used"], 0)
        self.assertEqual(usage["primary"]["reset"], 19_000)
        self.assertEqual(usage["secondary"]["used"], 14)
        self.assertEqual(usage["secondary"]["reset"], 900_000)

    def test_usage_window_catches_up_after_multiple_periods(self) -> None:
        usage = {
            "primary": {"used": 50, "duration": 5, "reset": 1_000},
            "secondary": {"used": 0, "duration": 0, "reset": 0},
        }
        self.assertTrue(codex_bridge.roll_expired_usage_windows(usage, now=1_601))
        self.assertEqual(usage["primary"], {"used": 0, "duration": 5, "reset": 1_900})

    def test_counts_parallel_task_lifecycle_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            first = home / "sessions" / "first.jsonl"
            second = home / "sessions" / "second.jsonl"
            first.parent.mkdir(parents=True)
            first.write_text("", encoding="utf-8")
            second.write_text("", encoding="utf-8")
            watcher = codex_bridge.SessionWatcher(home)
            with first.open("a", encoding="utf-8") as stream:
                stream.write(
                    '{"type":"event_msg","payload":{"type":"task_started",'
                    '"turn_id":"turn-1"}}\n'
                )
            with second.open("a", encoding="utf-8") as stream:
                stream.write(
                    '{"type":"event_msg","payload":{"type":"task_started",'
                    '"turn_id":"turn-2"}}\n'
                )
            self.assertTrue(watcher.poll())
            self.assertEqual(watcher.running_count, 2)

            with first.open("a", encoding="utf-8") as stream:
                stream.write(
                    '{"type":"event_msg","payload":{"type":"task_complete",'
                    '"turn_id":"turn-1"}}\n'
                )
            self.assertTrue(watcher.poll())
            self.assertEqual(watcher.running_count, 1)

    def test_counts_only_active_app_server_threads(self) -> None:
        server = codex_bridge.CodexAppServer()
        responses = [
            {
                "data": [
                    {"status": {"type": "active", "activeFlags": []}},
                    {"status": {"type": "idle"}},
                    {"status": {"type": "notLoaded"}},
                ],
                "nextCursor": "page-2",
            },
            {
                "data": [
                    {"status": {"type": "active", "activeFlags": ["waiting"]}},
                    {"status": {"type": "systemError"}},
                ],
                "nextCursor": None,
            },
        ]

        async def fake_request(method: str, params: object = None) -> dict:
            self.assertEqual(method, "thread/list")
            return responses.pop(0)

        server.request = fake_request
        self.assertEqual(asyncio.run(server.running_task_count()), 2)


if __name__ == "__main__":
    unittest.main()
