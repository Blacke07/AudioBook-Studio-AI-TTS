// An executable test harness, never shipped in the installed application.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Windows.Forms;

class DesktopProbe {
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window,uint message,IntPtr wparam,IntPtr lparam);
    static void Check(bool value,string message) { if(!value) throw new Exception(message); }
    [STAThread] static int Main(string[] args) {
        if(args[0]=="policy") {
            var origin=new Uri(DesktopPolicy.Address);
            foreach(string uri in new[]{"http://127.0.0.1:7863/","http://127.0.0.1:7863/api/audio?path=a.mp4","http://127.0.0.1:7863/#/settings"})
                Check(DesktopPolicy.Local(origin,uri),"Local URL refused: "+uri);
            foreach(string uri in new[]{"https://127.0.0.1:7863/","http://127.0.0.1:7864/","http://localhost:7863/","http://127.0.0.1:7863.evil.test/",
                "file:///C:/private.txt","javascript:alert(1)","http://name@127.0.0.1:7863/","https://example.test/"})
                Check(!DesktopPolicy.Local(origin,uri),"Foreign URL allowed: "+uri);
            Check(!DesktopPolicy.External("file:///C:/private.txt") && !DesktopPolicy.External("javascript:alert(1)"),"External protocol allowed");
            Check(DesktopPolicy.External("https://example.test/"),"External HTTPS refused");
            Check(!DesktopPolicy.Busy(false,0) && DesktopPolicy.Busy(false,1) && DesktopPolicy.Busy(true,0),"Busy decision");
            Check(DesktopPolicy.Identity(@"C:\Books !\café")==DesktopPolicy.Identity(@"c:\books !\CAFÉ\"),"Install identity");
            Check(DesktopPolicy.Identity(@"C:\Books")!=DesktopPolicy.Identity(@"D:\Books"),"Different installs share identity");
            Check(DesktopPolicy.StateFolder(@"C:\Books !\café")==@"C:\Books !\café\Data\State\desktop","Profile path");
            Check(DesktopPolicy.Fit(new Rectangle(-5000,-4000,1400,900),new Rectangle(0,0,1280,720))==new Rectangle(0,0,1280,720),"Offscreen placement");
            Check(!DesktopRuntime.ValidVersion(null) && !DesktopRuntime.ValidVersion("0.0.0.0") && !DesktopRuntime.ValidVersion("broken") && DesktopRuntime.ValidVersion("155.0.1.2"),"Runtime version detection");
            Console.WriteLine("POLICY_OK"); return 0;
        }
        if(args[0]=="runtime") return DesktopRuntime.Available()?0:2;
        if(args[0]=="signature") {
            try {
                using(var verified=DesktopRuntime.OpenVerifiedBootstrapper(args[1])) {
                    bool writeBlocked=false,deleteBlocked=false;
                    try { using(var writer=new FileStream(args[1],FileMode.Open,FileAccess.Write,FileShare.ReadWrite)) { } }
                    catch(IOException) { writeBlocked=true; }
                    try { File.Delete(args[1]); } catch(IOException) { deleteBlocked=true; }
                    Check(writeBlocked && deleteBlocked,"Verified bootstrapper was not locked against modification/replacement");
                }
                return 0;
            }
            catch(IOException error) { Console.Error.WriteLine(error.Message); return 3; }
        }
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        if(args[0]=="activate") return AppLauncher.RunInstance(args[1],delegate { throw new Exception("Second instance tried to create another server."); });
        string root=args[1], mode=args[0]; int decisions=0,stage=0,ticks=0; uint failedBrowser=0;
        var info=new ProcessStartInfo(args[2],"-u "+AppLauncher.Quote(Path.Combine(root,mode=="manual"?"serve.py":"fake_server.py"))) {
            WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true };
        Func<string,bool> confirmation=message => {
            decisions++; File.AppendAllText(Path.Combine(root,"decisions.txt"),message+"\n");
            return mode!="busy" && mode!="queued" && !mode.StartsWith("browser-") || decisions>1;
        };
        var app=new AppLauncher(root,new Uri(args[3]),info,mode=="manual"?null:confirmation);
        app.Text=mode=="manual"?"AudioBook Studio — Preview (test copy)":"AudioBook Studio — Automated test";
        if(mode=="manual") return AppLauncher.RunInstance(root,delegate { return app; });
        var timer=new Timer { Interval=350 };
        timer.Tick+=async delegate {
            if(app.IsDisposed || app.Disposing) return;
            if(++ticks>110) { File.WriteAllText(Path.Combine(root,"failure.txt"),"Desktop test timed out"); Environment.Exit(1); }
            if(!app.Ready) return;
            try {
                var view=app.Controls.OfType<StudioWebView>().SingleOrDefault();
                if(stage==10) {
                    if(!app.Controls.OfType<Button>().Single(button => button.Text=="Reopen window").Visible) return;
                    stage=11; await app.ReadStatus();
                    if(mode=="browser-unknown") File.WriteAllText(Path.Combine(root,"unavailable"),"");
                    app.Close(); return;
                }
                if(stage==11 && decisions==1) {
                    stage=12;
                    Check(!app.IsDisposed,"Browser crash or Cancel closed the application");
                    await app.ReopenWindow(); return;
                }
                if(stage==12) {
                    if(view==null || view.CoreWebView2==null || await view.CoreWebView2.ExecuteScriptAsync("document.readyState")!="\"complete\"") return;
                    stage=13;
                    Check(view.CoreWebView2.BrowserProcessId!=failedBrowser,"Browser was not recreated");
                    Check(await view.CoreWebView2.ExecuteScriptAsync("document.title")=="\"Synthetic desktop test\"","Recovered page did not load");
                    File.WriteAllText(Path.Combine(root,"recovery-preserved.txt"),"true"); app.Close(); return;
                }
                if(stage==0) {
                    if(await view.CoreWebView2.ExecuteScriptAsync("document.readyState")!="\"complete\"") return;
                    stage=1;
                    Check(await view.CoreWebView2.ExecuteScriptAsync("document.title")=="\"Synthetic desktop test\"","Page did not load");
                    if(mode.StartsWith("browser-")) {
                        failedBrowser=view.CoreWebView2.BrowserProcessId;
                        stage=10;
                        using(var browser=Process.GetProcessById((int)failedBrowser)) browser.Kill();
                        return;
                    }
                    if(mode=="restore") {
                        Check(app.Bounds==new Rectangle(20,30,900,650),"Saved window placement was not restored"); app.Close(); return;
                    }
                    if(mode=="crash") { File.WriteAllText(Path.Combine(root,"ready.txt"),"ready"); timer.Stop(); return; }
                    if(mode=="instance") {
                        app.WindowState=FormWindowState.Minimized;
                        File.WriteAllText(Path.Combine(root,"ready.txt"),"ready"); return;
                    }
                    app.Bounds=new Rectangle(70,80,1050,730);
                    if(mode=="unknown") File.WriteAllText(Path.Combine(root,"unavailable"),"");
                    app.Close(); return;
                }
                if(stage==1 && mode=="instance" && app.WindowState!=FormWindowState.Minimized) {
                    File.WriteAllText(Path.Combine(root,"activation-restored.txt"),"true"); stage=3; app.Close();
                }
                if(stage==1 && (mode=="busy" || mode=="queued") && decisions==1) {
                    stage=2;
                    Check(!app.IsDisposed,"Cancel closed the application");
                    Check(view.Enabled,"Cancel did not restore browser input");
                    await app.ReadStatus(); // The same server and work survive Cancel.
                    File.WriteAllText(Path.Combine(root,"cancel-preserved.txt"),"true");
                    app.WindowState=FormWindowState.Minimized;
                    PostMessage(app.Handle,app.ActivationMessage,IntPtr.Zero,IntPtr.Zero); return;
                }
                if(stage==2) {
                    Check(app.WindowState!=FormWindowState.Minimized,"Activation did not restore the window");
                    stage=3; app.Close();
                }
            } catch(Exception error) { File.WriteAllText(Path.Combine(root,"failure.txt"),error.ToString()); Environment.Exit(1); }
        };
        app.Shown+=delegate { timer.Start(); };
        AppLauncher.RunInstance(root,delegate { return app; }); timer.Dispose();
        File.WriteAllText(Path.Combine(root,"result.txt"),decisions.ToString()); return 0;
    }
}
