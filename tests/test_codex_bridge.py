import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
import sys
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


MODULE_PATH = Path(__file__).parents[1] / "tools" / "codex_bridge.py"
SPEC = importlib.util.spec_from_file_location("codex_bridge", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
codex_bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(codex_bridge)


class CodexBridgeTests(unittest.TestCase):
    def test_stops_after_three_failed_reconnects(self) -> None:
        attempts = []
        reports = []

        @asynccontextmanager
        async def unavailable(_args):
            attempts.append(1)
            raise ConnectionError("offline")
            yield

        async def exercise(directory):
            server = SimpleNamespace(start=AsyncMock(), close=AsyncMock(),
                                     rate_limits=AsyncMock(return_value={}),
                                     running_task_count=AsyncMock(return_value=0))
            control = SimpleNamespace(stop_requested=False,
                                      report=lambda kind, **data: reports.append((kind, data)))
            with patch.dict(codex_bridge.os.environ, {"CODEX_HOME": directory}), \
                 patch.object(codex_bridge, "CodexAppServer", return_value=server), \
                 patch.object(codex_bridge, "open_transport", unavailable), \
                 patch.object(codex_bridge.asyncio, "sleep", new_callable=AsyncMock):
                await codex_bridge.bridge_loop(SimpleNamespace(codex="unused", dry_run=False), control)
            server.close.assert_awaited_once()

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(directory))
        self.assertEqual(len(attempts), 4)  # Initial connection, then three retries.
        self.assertEqual([data["reconnect_attempt"] for kind, data in reports if kind == "retrying"], [1, 2, 3])
        self.assertEqual([data for kind, data in reports if kind == "error"], [{"reconnect_exhausted": True}])

    def test_immediate_disconnects_consume_reconnect_budget(self) -> None:
        attempts = []
        reports = []

        @asynccontextmanager
        async def unstable(_args):
            attempts.append(1)
            yield SimpleNamespace(is_connected=False, send_payload=AsyncMock())

        @asynccontextmanager
        async def no_voice(_client, _control):
            yield

        async def exercise(directory):
            server = SimpleNamespace(start=AsyncMock(), close=AsyncMock(),
                                     rate_limits=AsyncMock(return_value={}),
                                     running_task_count=AsyncMock(return_value=0))
            control = SimpleNamespace(stop_requested=False,
                                      report=lambda kind, **data: reports.append(kind))
            with patch.dict(codex_bridge.os.environ, {"CODEX_HOME": directory}), \
                 patch.dict(sys.modules, {"voice_bridge": SimpleNamespace(voice_session=no_voice)}), \
                 patch.object(codex_bridge, "CodexAppServer", return_value=server), \
                 patch.object(codex_bridge, "open_transport", unstable), \
                 patch.object(codex_bridge.asyncio, "sleep", new_callable=AsyncMock):
                await codex_bridge.bridge_loop(SimpleNamespace(codex="unused", dry_run=False), control)

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(directory))
        self.assertEqual(len(attempts), 4)
        self.assertEqual(reports.count("retrying"), 3)
        self.assertEqual(reports.count("error"), 1)

    def test_live_interruption_updates_count_even_when_server_refresh_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            session = home / "sessions" / "run.jsonl"
            session.parent.mkdir()
            session.write_text("", encoding="utf-8")
            watcher = codex_bridge.SessionWatcher(home)
            sent = []

            def append(kind):
                with session.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"type": "event_msg", "payload": {
                        "type": kind, "turn_id": "live"}}) + "\n")

            async def send(payload):
                sent.append(json.loads(payload))

            @asynccontextmanager
            async def transport(args):
                append("task_started")
                yield SimpleNamespace(is_connected=True, send_payload=send)

            @asynccontextmanager
            async def voice(client, control):
                append("turn_aborted")
                yield

            sleeps = 0
            async def sleep(seconds):
                nonlocal sleeps
                sleeps += 1
                watcher.interrupted_until = 0
                if sleeps >= 2:
                    control.stop_requested = True

            control = SimpleNamespace(stop_requested=False, take_test=lambda: False,
                                      report=lambda *args, **kwargs: None)

            async def rate_limits():
                if watcher.interrupted:
                    # Model an account refresh taking longer than the notice duration.
                    watcher.interrupted_until = codex_bridge.time.monotonic() - 1
                return {}

            server = SimpleNamespace(start=AsyncMock(), close=AsyncMock(),
                                     rate_limits=rate_limits,
                                     running_task_count=AsyncMock(side_effect=[0, RuntimeError("offline")]))
            with patch.dict(codex_bridge.os.environ, {"CODEX_HOME": directory}), \
                 patch.dict(sys.modules, {"voice_bridge": SimpleNamespace(voice_session=voice)}), \
                 patch.object(codex_bridge, "SessionWatcher", return_value=watcher), \
                 patch.object(codex_bridge, "CodexAppServer", return_value=server), \
                 patch.object(codex_bridge, "open_transport", transport), \
                 patch.object(codex_bridge.asyncio, "sleep", sleep):
                asyncio.run(codex_bridge.bridge_loop(SimpleNamespace(codex="unused", dry_run=False), control))
            heartbeats = [payload for payload in sent if "running" in payload]
            self.assertEqual([payload["running"] for payload in heartbeats], [1, 0, 0])
            self.assertEqual([payload["msg"] for payload in heartbeats],
                             ["助手正在工作", "Task interrupted", "助手已就绪"])
            self.assertTrue(all(payload["codex"]["completion_seq"] == 0 for payload in heartbeats))
            server.close.assert_awaited_once()

    def test_interruption_is_scoped_deduplicated_and_never_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            watcher = codex_bridge.SessionWatcher(Path(directory))
            first, mirror, second = (Path(name) for name in ("first", "mirror", "second"))
            watcher.thread_ids.update({first: "a", mirror: "a", second: "b"})

            def event(path, kind, turn):
                return watcher._consume(path, json.dumps({"type": "event_msg", "payload": {
                    "type": kind, "turn_id": turn}}))

            event(first, "task_started", "old")
            event(mirror, "task_started", "old")
            event(first, "task_started", "new")
            event(second, "task_started", "other")
            with patch.object(codex_bridge.time, "monotonic", return_value=100):
                self.assertTrue(event(first, "turn_aborted", "old"))
                self.assertEqual(watcher.running_count, 2)
                self.assertEqual(watcher.active_turns, {(first, "new"), (second, "other")})
                self.assertFalse(event(mirror, "turn_aborted", "old"))
                self.assertFalse(event(first, "task_complete", "old"))
                self.assertEqual(watcher.completion_sequence, 0)
                payload = json.loads(codex_bridge.heartbeat_payload({}, watcher))
                self.assertEqual(payload["msg"], "Task interrupted; 2 running")
                self.assertEqual(payload["running"], 2)
                self.assertEqual(payload["waiting"], 0)
                self.assertEqual(payload["codex"]["completion_seq"], 0)
                # Another task's successful completion retains its normal alert.
                event(second, "task_complete", "other")
                self.assertEqual(watcher.completion_sequence, 1)
                self.assertEqual(json.loads(codex_bridge.heartbeat_payload(
                    {}, watcher, completed=True))["msg"], "任务已完成")
            with patch.object(codex_bridge.time, "monotonic", return_value=106):
                self.assertFalse(watcher.interrupted)
                self.assertEqual(json.loads(codex_bridge.heartbeat_payload({}, watcher))["msg"],
                                 "助手正在工作")

    def test_interruption_recovery_and_live_poll(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            session = home / "sessions" / "run.jsonl"
            session.parent.mkdir()

            def append(kind, turn):
                with session.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"type": "event_msg", "payload": {
                        "type": kind, "turn_id": turn}}) + "\n")

            append("task_started", "old")
            append("turn_aborted", "old")
            watcher = codex_bridge.SessionWatcher(home)
            self.assertFalse(watcher.running)
            self.assertFalse(watcher.interrupted)
            self.assertEqual(watcher.completion_sequence, 0)
            for turn in (None, "", 42, "unknown"):
                append("turn_aborted", turn)
            self.assertFalse(watcher.poll())
            self.assertFalse(watcher.interrupted)
            append("task_started", "live")
            self.assertTrue(watcher.poll())
            append("turn_aborted", "live")
            self.assertTrue(watcher.poll())
            self.assertFalse(watcher.running)
            self.assertTrue(watcher.interrupted)
            self.assertEqual(json.loads(codex_bridge.heartbeat_payload({}, watcher))["msg"],
                             "Task interrupted")
            self.assertFalse(watcher.state_path.exists())
            restarted = codex_bridge.SessionWatcher(home)
            self.assertFalse(restarted.running)
            self.assertFalse(restarted.interrupted)

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

class SessionFreshnessTests(unittest.TestCase):
    def test_recent_records_override_stale_windows_mtime(self):
        import os
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory); path=home/'sessions'/'live.jsonl';path.parent.mkdir()
            path.write_text(json.dumps({'timestamp':datetime.now(timezone.utc).isoformat(),
                'type':'event_msg','payload':{'type':'task_started','turn_id':'live'}})+'\n',encoding='utf-8')
            os.utime(path,(1,1))
            watcher=codex_bridge.SessionWatcher(home)
            self.assertEqual(watcher.running_count,1)
            self.assertEqual(watcher.completion_sequence,0)

    def test_old_abandoned_session_stays_inactive(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);path=home/'sessions'/'old.jsonl';path.parent.mkdir()
            path.write_text(json.dumps({'timestamp':'2000-01-01T00:00:00Z',
                'type':'event_msg','payload':{'type':'task_started','turn_id':'old'}})+'\n',encoding='utf-8')
            os.utime(path,(1,1))
            self.assertEqual(codex_bridge.SessionWatcher(home).running_count,0)

    def test_recent_completion_is_not_replayed_on_restart(self):
        import os
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);path=home/'sessions'/'done.jsonl';path.parent.mkdir()
            stamp=datetime.now(timezone.utc).isoformat()
            path.write_text(''.join(json.dumps({'timestamp':stamp,'type':'event_msg',
                'payload':{'type':kind,'turn_id':'done'}})+'\n' for kind in ['task_started','task_complete']),encoding='utf-8')
            os.utime(path,(1,1))
            watcher=codex_bridge.SessionWatcher(home)
            self.assertEqual(watcher.running_count,0)
            self.assertEqual(watcher.completion_sequence,0)
