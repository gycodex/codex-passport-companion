import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from doubao_compat import BUILD_HASH, DoubaoCompatibility


class CompatibilityTests(unittest.TestCase):
    def test_adapter_requires_opt_in(self):
        from voice_bridge import Shortcuts
        cfg = dict(voice_hotkeys=True, voice_output='test', voice_ime='doubao',
                   voice_start_key='alt+v', voice_stop_key='alt+v')
        with patch.dict(sys.modules, {'pynput.keyboard': MagicMock()}), patch('voice_bridge.sys.platform', 'win32'), patch('doubao_compat.DoubaoCompatibility') as adapter:
            shortcuts = Shortcuts(cfg)
            self.assertIsNone(shortcuts.compat)
            adapter.assert_not_called()
            enabled = Shortcuts(dict(cfg, voice_doubao_compat=True))
            adapter.return_value.start.assert_called_once()
            enabled.close()
            adapter.return_value.close.assert_called_once()

    def runtime(self):
        runtime = MagicMock()
        runtime.get_local_device.return_value.enumerate_processes.return_value = [
            type('Process', (), {'name': 'ImeService.exe', 'pid': 42})()]
        session = runtime.attach.return_value
        session.is_detached = False
        probe, hook = MagicMock(), MagicMock()
        probe.exports_sync.path.return_value = 'D:/Apps/DoubaoIME/ImeService.exe'
        probe.exports_sync.arch.return_value = 'x64'
        hook.exports_sync.ready.return_value = True
        session.create_script.side_effect = [probe, hook]
        return runtime, session, probe, hook

    def test_unknown_build_only_probes_and_detaches(self):
        runtime, session, probe, hook = self.runtime()
        with patch.dict(sys.modules, {'frida': runtime}), patch('doubao_compat.sys.platform', 'win32'), patch('doubao_compat.Path.read_bytes', return_value=b'unknown'):
            with self.assertRaisesRegex(ValueError, '版本未验证'):
                DoubaoCompatibility().start()
        self.assertEqual(session.create_script.call_count, 1)
        probe.unload.assert_called_once()
        session.detach.assert_called_once()
        hook.load.assert_not_called()

    def test_verified_alternate_install_and_disconnect(self):
        runtime, session, probe, hook = self.runtime()
        with patch.dict(sys.modules, {'frida': runtime}), patch('doubao_compat.sys.platform', 'win32'), patch('doubao_compat.Path.read_bytes', return_value=b'verified'), patch('doubao_compat.hashlib.sha256') as digest:
            digest.return_value.hexdigest.return_value = BUILD_HASH
            adapter = DoubaoCompatibility()
            adapter.start()
            adapter.check()
            session.is_detached = True
            with self.assertRaises(ValueError):
                adapter.check()
            adapter.close()
            adapter.close()
        hook.unload.assert_called_once()
        session.detach.assert_called_once()

    def test_hook_install_failure_detaches(self):
        runtime, session, probe, hook = self.runtime()
        hook.exports_sync.ready.side_effect = RuntimeError('hook failed')
        with patch.dict(sys.modules, {'frida': runtime}), patch('doubao_compat.sys.platform', 'win32'), patch('doubao_compat.Path.read_bytes', return_value=b'verified'), patch('doubao_compat.hashlib.sha256') as digest:
            digest.return_value.hexdigest.return_value = BUILD_HASH
            with self.assertRaises(ValueError):
                DoubaoCompatibility().start()
        hook.unload.assert_called_once()
        session.detach.assert_called_once()
