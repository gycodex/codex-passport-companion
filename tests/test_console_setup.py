import importlib.metadata
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import console_setup


class SetupTests(unittest.TestCase):
    def test_only_enabled_windows_doubao_requests_permission(self):
        cfg = dict(voice_enabled=True, voice_hotkeys=True, voice_ime='doubao',
                   voice_doubao_compat=True, voice_output='cable')
        with patch('console_setup.sys.platform', 'linux'):
            self.assertFalse(console_setup.needs_setup(cfg))
        windll = Mock()
        windll.shell32.IsUserAnAdmin.return_value = 0
        with patch('console_setup.sys.platform', 'win32'), patch('console_setup.ctypes.windll', windll, create=True):
            self.assertTrue(console_setup.needs_setup(cfg))
            for key, value in [('voice_enabled',False), ('voice_hotkeys',False),
                               ('voice_doubao_compat',False), ('voice_output','meter'), ('voice_ime','xunfei')]:
                self.assertFalse(console_setup.needs_setup(dict(cfg, **{key:value})))
            windll.shell32.IsUserAnAdmin.return_value = 1
            with patch('console_setup.importlib.metadata.version', return_value='17.18.0'):
                self.assertFalse(console_setup.needs_setup(cfg))
            with patch('console_setup.importlib.metadata.version', side_effect=importlib.metadata.PackageNotFoundError):
                self.assertTrue(console_setup.needs_setup(cfg))

    def test_install_failure_does_not_stop_existing_service(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sys, 'argv', ['setup','8766',folder,'test-token','same-user']), \
                 patch('console_setup.getpass.getuser', return_value='same-user'), \
                 patch('console_setup.importlib.metadata.version', return_value='old'), \
                 patch('console_setup.subprocess.CREATE_NO_WINDOW', 0, create=True), \
                 patch('console_setup.subprocess.run', side_effect=RuntimeError('install failed')), \
                 patch('console_setup.urllib.request.urlopen') as request, \
                 patch('console_setup.subprocess.Popen') as start:
                console_setup.main()
                request.assert_not_called()
                start.assert_not_called()
                self.assertIn('失败', (Path(folder)/'setup-result.json').read_text(encoding='utf-8'))

    def test_other_admin_account_does_not_start_or_stop_services(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sys, 'argv', ['setup','8766',folder,'test-token','original-user']), \
                 patch('console_setup.getpass.getuser', return_value='other-user'), \
                 patch('console_setup.urllib.request.urlopen') as request, \
                 patch('console_setup.subprocess.Popen') as start:
                console_setup.main()
                request.assert_not_called()
                start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
