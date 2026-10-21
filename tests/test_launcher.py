"""Exercise native resources and owned-process cleanup without launching the user's application."""
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT=Path(__file__).resolve().parents[1]
CSC=Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
sys.path.insert(0,str(ROOT/'tools'))
from build import build_launcher


class LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=TemporaryDirectory(prefix='AudioBook icons ')
        cls.folder=Path(cls.temp.name)
        generator=cls.folder/'IconBuilder.exe'
        subprocess.run([str(CSC),'/nologo','/target:exe','/reference:System.Drawing.dll',
                        '/out:'+str(generator),str(ROOT/'tools/IconBuilder.cs')],check=True,capture_output=True)
        subprocess.run([str(generator),str(cls.folder/'assets')],check=True)
        cls.icon=cls.folder/'assets/audiobook.ico'
        cls.launcher=cls.folder/'AudioBook Studio.exe'
        build_launcher(CSC,cls.folder)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_icon_has_seven_valid_sizes_with_transparency(self):
        data=self.icon.read_bytes()
        self.assertEqual(struct.unpack_from('<HHH',data),(0,1,7))
        for index,expected in enumerate((16,24,32,48,64,128,256)):
            width,height,_,_,planes,depth,size,offset=struct.unpack_from('<BBBBHHII',data,6+index*16)
            self.assertEqual((width or 256,height or 256,planes,depth),(expected,expected,1,32))
            png=data[offset:offset+size]
            self.assertEqual(png[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack_from('>II',png,16),(expected,expected))
            self.assertEqual(png[25],6)  # PNG RGBA, preserving transparent corners.

    def test_launcher_resource_and_installation_checks_are_read_only(self):
        subprocess.run([str(self.launcher),'--check-resources'],check=True)
        before={file.relative_to(self.folder) for file in self.folder.rglob('*')}
        result=subprocess.run([str(self.launcher),'--check-installation'],capture_output=True,timeout=5)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(before,{file.relative_to(self.folder) for file in self.folder.rglob('*')})
        self.assertFalse((self.folder/'startup.log').exists())

    def test_job_closes_owned_process_tree_without_stopping_an_unrelated_process(self):
        with TemporaryDirectory(prefix='AudioBook job ') as folder:
            folder=Path(folder)
            script=folder/'child.py'
            script.write_text("import subprocess,sys,time\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\nprint(p.pid,flush=True)\ntime.sleep(60)\n")
            probe=folder/'JobProbe.cs'
            probe.write_text('''using System;
using System.Diagnostics;
using System.Threading;
class JobProbe {
 static int Main(string[] args) {
  using(var job=new WindowsJob()) {
   var info=new ProcessStartInfo(args[0],"\\\""+args[1]+"\\\"") { UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true };
   using(var child=Process.Start(info)) {
    try { job.Attach(child); } catch { child.Kill();throw; }
    int descendant=int.Parse(child.StandardOutput.ReadLine());
    job.Dispose();
    if(!child.WaitForExit(5000)) return 1;
    for(int attempt=0;attempt<50;attempt++) {
     try { using(var item=Process.GetProcessById(descendant)) { if(item.HasExited) return 0; } }
     catch(ArgumentException) { return 0; }
     Thread.Sleep(100);
    }
    return 2;
   }
  }
 }
}''',encoding='utf-8')
            output=folder/'JobProbe.exe'
            subprocess.run([str(CSC),'/nologo','/out:'+str(output),str(probe),
                            str(ROOT/'installer/WindowsJob.cs')],check=True,capture_output=True)
            unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                result=subprocess.run([str(output),sys.executable,str(script)],capture_output=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr.decode('utf-8','replace'))
                self.assertIsNone(unrelated.poll())
            finally:
                unrelated.terminate();unrelated.wait(5)


if __name__=='__main__': unittest.main()
