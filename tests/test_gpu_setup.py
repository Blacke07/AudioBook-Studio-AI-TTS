"""Check the actual setup eligibility code against the installer's manifest-driven rules."""
import importlib.util
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')


class GpuSetupTests(unittest.TestCase):
    def test_setup_and_installer_agree_on_gpu_driver_and_memory_boundaries(self):
        spec = importlib.util.spec_from_file_location('gpu_install_core', ROOT / 'installer/install.py')
        core = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(core)
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        cases = [('7.5', '8192', '570.65'), ('8.0', '40960', '617.42'),
                 ('8.6', '12288', '617.42'), ('8.9', '8188', '617.42'),
                 ('12.0', '32768', '617.42'), ('6.1', '8192', '617.42'), ('12.1', '32768', '617.42'),
                 ('7.5', '6144', '617.42'), ('8.9', '12288', '570.64')]
        with TemporaryDirectory(prefix='AudioBook GPU checks ') as folder:
            folder = Path(folder)
            probe = folder / 'GpuProbe.cs'
            probe.write_text('''using System;
using System.Globalization;
class GpuProbe {
 static void Main(string[] args) {
  Console.WriteLine(Setup.SupportsGpu(double.Parse(args[0],CultureInfo.InvariantCulture),
                   double.Parse(args[1],CultureInfo.InvariantCulture),args[2]));
 }
}''', encoding='utf-8')
            output = folder / 'GpuProbe.exe'
            subprocess.run([str(CSC), '/nologo', '/target:exe', '/platform:x64', '/codepage:65001',
                            '/main:GpuProbe', '/reference:System.Windows.Forms.dll',
                            '/reference:System.Drawing.dll', '/reference:System.Web.Extensions.dll',
                            '/resource:' + str(ROOT / 'manifest.json') + ',manifest.json',
                            '/out:' + str(output), str(probe), str(ROOT / 'installer/Setup.cs'),
                            str(ROOT / 'installer/DesktopRuntime.cs')],
                           check=True, capture_output=True)
            for capability, memory, driver in cases:
                with self.subTest(capability=capability, memory=memory, driver=driver):
                    expected = True
                    try:
                        core.check_hardware(manifest['profiles']['compact'], 'GPU', capability,
                                            memory, driver, manifest['hardware'])
                    except RuntimeError:
                        expected = False
                    actual = subprocess.check_output([str(output), capability, memory, driver], text=True).strip()
                    self.assertEqual(actual, str(expected))
