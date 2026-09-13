import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import console_setup
import desktop_runtime
from passport_desktop import startup_command


class RuntimeTests(unittest.TestCase):
    def test_frozen_roles_do_not_launch_python_scripts(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', 'C:/Passport Test/Passport.exe'):
            self.assertEqual(desktop_runtime.command('backend', '--port', 18766),
                             ['C:/Passport Test/Passport.exe', '--passport-role', 'backend', '--port', '18766'])
            self.assertEqual(startup_command(), '"C:/Passport Test/Passport.exe"')
            self.assertEqual(desktop_runtime.child_environment()['PYINSTALLER_RESET_ENVIRONMENT'], '1')

    def test_source_roles_and_config_directory(self):
        with patch.object(sys, 'frozen', False, create=True):
            args = desktop_runtime.command('setup', 'value with spaces')
            self.assertEqual(Path(args[1]).name, 'console_setup.py')
            self.assertEqual(args[2], 'value with spaces')
        self.assertEqual(desktop_runtime.config_directory(['--config-dir=build-test']), Path('build-test').resolve())
        with self.assertRaises(ValueError):
            desktop_runtime.command('unknown')

    def test_frozen_setup_missing_dependency_never_runs_pip_or_stops_service(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sys, 'frozen', True, create=True), \
                 patch.object(sys, 'argv', ['setup', '18766', directory, 'test-token', 'same-user']), \
                 patch('console_setup.getpass.getuser', return_value='same-user'), \
                 patch('console_setup.importlib.metadata.version', return_value='old'), \
                 patch('console_setup.subprocess.run') as pip, \
                 patch('console_setup.urllib.request.urlopen') as http, \
                 patch('console_setup.subprocess.Popen') as launch:
                console_setup.main()
                pip.assert_not_called()
                http.assert_not_called()
                launch.assert_not_called()
                self.assertIn('失败', json.loads((Path(directory) / 'setup-result.json').read_text(encoding='utf-8'))['message'])

    def test_frozen_elevation_launch_uses_exe_and_restores_environment(self):
        calls = []
        def shell(*args):
            calls.append((args, os.environ.get('PYINSTALLER_RESET_ENVIRONMENT')))
            return 33
        windll = Mock()
        windll.shell32.ShellExecuteW.side_effect = shell
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sys, 'frozen', True, create=True), \
                 patch.object(sys, 'executable', 'C:/Passport Test/Passport.exe'), \
                 patch('console_setup.sys.platform', 'win32'), \
                 patch('console_setup.ctypes.windll', windll, create=True), \
                 patch('console_setup.getpass.getuser', return_value='same-user'), \
                 patch.dict(os.environ, {'PYINSTALLER_RESET_ENVIRONMENT': 'original'}):
                console_setup.launch(18766, Path(directory), 'test-token')
                self.assertEqual(os.environ['PYINSTALLER_RESET_ENVIRONMENT'], 'original')
        args, environment = calls[0]
        self.assertEqual(environment, '1')
        self.assertEqual(args[1:3], ('runas', 'C:/Passport Test/Passport.exe'))
        self.assertEqual(args[3], subprocess.list2cmdline([
            '--passport-role', 'setup', '18766', str(Path(directory).resolve()), 'test-token', 'same-user']))


if __name__ == '__main__':
    unittest.main()
