"""Run the real WebView2 host against invented HTML and a fake backend; never launch an AI engine."""
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build import build_launcher
from webview2 import restore

CSC = Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
SERVER = '''import json,subprocess,sys,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
root=Path.cwd()
settings=json.loads((root/'server.json').read_text())
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'])
(root/'child.pid').write_text(str(child.pid))
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path=='/api/status':
   self.send_response(503 if (root/'unavailable').exists() else 200);self.end_headers()
   self.wfile.write(json.dumps({'running':settings['busy'],'queued':settings['queued']}).encode())
  else:
   self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers()
   self.wfile.write(b'<!doctype html><title>Synthetic desktop test</title><h1>The Lantern House</h1><p>Invented test material.</p>')
 def log_message(self,*args): pass
ThreadingHTTPServer(('127.0.0.1',settings['port']),Handler).serve_forever()
'''


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory(prefix='AudioBook desktop ! café ')
        cls.folder = Path(cls.temp.name)
        _, icon = build_launcher(CSC, cls.folder)
        sdk = restore(ROOT)
        cls.probe = cls.folder / 'DesktopProbe.exe'
        args = [str(CSC), '/nologo', '/target:exe', '/platform:x64', '/codepage:65001',
                '/win32manifest:' + str(ROOT / 'installer/windows.manifest'),
                '/main:DesktopProbe', '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                '/reference:System.Web.Extensions.dll',
                '/reference:' + str(sdk / 'Microsoft.Web.WebView2.Core.dll'),
                '/reference:' + str(sdk / 'Microsoft.Web.WebView2.WinForms.dll'),
                '/resource:' + str(icon) + ',app.ico', '/out:' + str(cls.probe),
                str(ROOT / 'tests/DesktopProbe.cs')]
        args += [str(ROOT / 'installer' / name) for name in
                 ('AppLauncher.cs', 'WindowsJob.cs', 'DesktopPolicy.cs', 'DesktopRuntime.cs', 'StudioWebView.cs')]
        result = subprocess.run(args, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stdout.decode('utf-8', errors='replace'))
        cls.runtime = subprocess.run([str(cls.probe), 'runtime'], timeout=10).returncode == 0

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_origin_boundaries_profile_identity_busy_queue_and_offscreen_placement(self):
        result = subprocess.run([str(self.probe), 'policy'], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertIn(b'POLICY_OK', result.stdout)

    def test_vendor_signature_is_checked_without_executing_the_candidate(self):
        valid = self.folder / 'WebView2Loader.dll'
        result = subprocess.run([str(self.probe), 'signature', str(valid)], timeout=30, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        invalid = self.folder / 'unsigned-bootstrap.exe'
        invalid.write_bytes(b'This is deliberately not executable software.')
        self.assertEqual(subprocess.run([str(self.probe), 'signature', str(invalid)], timeout=30, capture_output=True).returncode, 3)

    def test_changed_sdk_cache_is_refused_before_extraction(self):
        with TemporaryDirectory(prefix='AudioBook SDK ') as directory:
            root = Path(directory)
            (root / 'installer').mkdir()
            (root / 'downloads').mkdir()
            (root / 'licenses').mkdir()
            shutil.copyfile(ROOT / 'licenses/WebView2.txt', root / 'licenses/WebView2.txt')
            spec = json.loads((ROOT / 'installer/webview2.json').read_text())
            (root / 'installer/webview2.json').write_text(json.dumps(spec))
            cached = root / 'downloads' / spec['name']
            cached.write_bytes(b'changed package')
            with self.assertRaisesRegex(RuntimeError, 'pinned SHA-256'):
                restore(root)
            self.assertFalse((root / 'build').exists())

    def exercise(self, mode, decisions):
        if not self.runtime:
            self.skipTest('Microsoft WebView2 Runtime is not installed; native host smoke requires it.')
        with TemporaryDirectory(prefix='AudioBook desktop session ! café ') as directory:
            root = Path(directory)
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            (root / 'server.json').write_text(json.dumps({'port': port, 'busy': mode in ('busy', 'browser-busy'),
                                                         'queued': int(mode in ('queued', 'browser-queued'))}))
            (root / 'fake_server.py').write_text(SERVER, encoding='utf-8')
            if mode == 'restore':
                (root / '.desktop').mkdir()
                (root / '.desktop/window.json').write_text('[20,30,900,650,0]')
            process = subprocess.Popen([str(self.probe), mode, str(root), sys.executable, f'http://127.0.0.1:{port}/'],
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            owned = []
            try:
                if mode in ('crash', 'instance'):
                    deadline = time.monotonic() + 35
                    while not (root / 'ready.txt').exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(.1)
                    self.assertTrue((root / 'ready.txt').exists(), 'Host did not become ready')
                    if mode == 'crash':
                        owned = psutil.Process(process.pid).children(recursive=True)
                        process.kill()
                    else:
                        second = subprocess.run([str(self.probe), 'activate', str(root)], timeout=10)
                        self.assertEqual(second.returncode, 0)
                process.wait(45)
                if mode != 'crash':
                    self.assertEqual(process.returncode, 0, (root / 'failure.txt').read_text() if (root / 'failure.txt').exists() else '')
                    self.assertEqual((root / 'result.txt').read_text(), str(decisions))
                    self.assertTrue((root / '.desktop/window.json').exists())
                    self.assertNotIn('did not exit after disposal', (root / 'startup.log').read_text(encoding='utf-8'))
                    if mode in ('busy', 'queued'):
                        self.assertTrue((root / 'cancel-preserved.txt').exists())
                    if mode == 'unknown':
                        self.assertIn('Could not check', (root / 'decisions.txt').read_text())
                    if mode == 'instance':
                        self.assertTrue((root / 'activation-restored.txt').exists())
                    if mode.startswith('browser-'):
                        self.assertTrue((root / 'recovery-preserved.txt').exists())
                        log = (root / 'startup.log').read_text(encoding='utf-8')
                        self.assertIn('backend has been kept running', log)
                child = int((root / 'child.pid').read_text())
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    browser = [p for p in psutil.process_iter(['pid', 'name', 'cmdline'])
                               if 'msedgewebview2' in (p.info['name'] or '').lower()
                               and str(root / '.desktop/WebView2').lower() in ' '.join(p.info['cmdline'] or []).lower()]
                    living = [p for p in owned if p.is_running()]
                    if not browser and not psutil.pid_exists(child) and not living:
                        break
                    time.sleep(.2)
                self.assertFalse(browser, 'Dedicated WebView2 processes remained')
                self.assertFalse(psutil.pid_exists(child), 'Owned backend child remained')
                self.assertFalse(living, 'Owned descendants remained after host crash')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(5)
                # Runtime descendants can release profile handles shortly after an abrupt test-host exit.
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    remaining = [p for p in psutil.process_iter(['pid', 'name', 'cmdline'])
                                 if 'msedgewebview2' in (p.info['name'] or '').lower()
                                 and str(root / '.desktop/WebView2').lower() in ' '.join(p.info['cmdline'] or []).lower()]
                    if not remaining:
                        break
                    time.sleep(.1)

    def test_idle_close_stops_backend_and_dedicated_browser(self):
        self.exercise('idle', 0)

    def test_busy_close_cancel_preserves_job_then_confirm_stops_it(self):
        self.exercise('busy', 2)

    def test_queued_work_also_requires_confirmation(self):
        self.exercise('queued', 2)

    def test_unavailable_status_requires_confirmation(self):
        self.exercise('unknown', 1)

    def test_host_crash_stops_owned_backend_and_browser(self):
        self.exercise('crash', 0)

    def test_browser_crash_busy_cancel_and_recovery_keep_backend(self):
        self.exercise('browser-busy', 2)

    def test_browser_crash_queued_cancel_and_recovery_keep_backend(self):
        self.exercise('browser-queued', 2)

    def test_browser_crash_unknown_status_requires_confirmation_and_can_reopen(self):
        self.exercise('browser-unknown', 2)

    def test_second_instance_restores_existing_window_without_starting_another_server(self):
        self.exercise('instance', 0)

    def test_saved_window_position_and_size_are_restored(self):
        self.exercise('restore', 0)


if __name__ == '__main__':
    unittest.main()
