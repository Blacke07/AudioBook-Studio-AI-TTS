using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;

class AppLauncher : Form {
    static readonly string Root=Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
    readonly string root;
    readonly Uri address;
    readonly ProcessStartInfo command;
    readonly Func<string,bool> confirm;
    Process child;
    Process browserProcess;
    WindowsJob job;
    StreamWriter output;
    StudioWebView view;
    readonly object logLock=new object();
    readonly Label status=new Label();
    readonly Button reopen=new Button { Text="Reopen window",Bounds=new Rectangle(230,144,180,34),Visible=false };
    readonly Button stop=new Button { Text="Cancel",Bounds=new Rectangle(424,144,130,34) };
    readonly System.Windows.Forms.Timer poll=new System.Windows.Forms.Timer { Interval=500 };
    NotifyIcon tray;
    DateTime deadline;
    bool ready,closing,childStarted,polling,checkingClose,openingView;
    FormWindowState visibleState=FormWindowState.Normal;
    internal bool Ready { get { return ready; } }
    internal uint ActivationMessage { get; private set; }

    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern uint RegisterWindowMessage(string message);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window,uint message,IntPtr wparam,IntPtr lparam);
    [DllImport("user32.dll")] static extern bool AllowSetForegroundWindow(int pid);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr window,int attribute,ref int value,int size);

    internal static int Run(string[] args) {
        try {
            if(args.Length>0 && args[0]=="--check-resources") {
                using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("app.ico"))
                using(var icon=new Icon(stream)) return icon.Width>0 ? 0:1;
            }
            if(args.Length>0 && args[0]=="--check-installation") { CheckFiles(true); return 0; }
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            return RunInstance(Root,delegate {
                CheckFiles();
                if(!DesktopRuntime.Available()) throw new InvalidOperationException(
                    "Microsoft Edge WebView2 Runtime is required. Run setup to install it, or get it from:\n"+DesktopRuntime.DownloadPage);
                return new AppLauncher(Root,new Uri(DesktopPolicy.Address),ServerCommand(Root),null);
            });
        } catch(Exception error) {
            if(args.Length>0) Console.Error.WriteLine(error.Message);
            else MessageBox.Show(error.Message,"AudioBook Studio",MessageBoxButtons.OK,MessageBoxIcon.Error);
            return 1;
        }
    }
    internal static int RunInstance(string folder,Func<AppLauncher> create) {
        string id=DesktopPolicy.Identity(folder);
        using(var mutex=new Mutex(false,"Local\\"+id)) {
            bool owned;
            try { owned=mutex.WaitOne(0); } catch(AbandonedMutexException) { owned=true; }
            if(!owned) { ActivateExisting(id); return 0; }
            // Let Windows infer taskbar identity from the same EXE targeted by setup's shortcuts.
            try { Application.Run(create()); }
            finally { mutex.ReleaseMutex(); }
        }
        return 0;
    }
    static void CheckFiles(bool verifying=false) {
        foreach(string name in new[]{".venv/Scripts/python.exe","launcher.py","app.py",
            "Microsoft.Web.WebView2.Core.dll","Microsoft.Web.WebView2.WinForms.dll","WebView2Loader.dll"})
            if(!File.Exists(InstallationPaths.At(Root,InstallationPaths.Program+"/"+name))) throw new FileNotFoundException("Incomplete installation: missing "+name+". Run setup to repair the program; your data is kept.");
        if(!File.Exists(InstallationPaths.At(Root,InstallationPaths.Manifest)) || (!verifying && File.Exists(InstallationPaths.At(Root,InstallationPaths.Marker))))
            throw new InvalidOperationException("Installation or migration is incomplete. Run setup again; your data is kept.");
    }
    internal static ProcessStartInfo ServerCommand(string folder) {
        string program=InstallationPaths.At(folder,InstallationPaths.Program);
        var info=new ProcessStartInfo(Path.Combine(program,".venv/Scripts/python.exe"),"-B -u "+Quote(Path.Combine(program,"launcher.py"))+" --no-browser") {
            WorkingDirectory=program,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,
            StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8
        };
        info.EnvironmentVariables["PYTHONUTF8"]="1"; info.EnvironmentVariables["PYTHONIOENCODING"]="utf-8";
        return info;
    }
    static void ActivateExisting(string id) {
        uint message=RegisterWindowMessage(id+".Show"); string self=Assembly.GetExecutingAssembly().Location;
        for(int attempt=0;attempt<40;attempt++) {
            foreach(var process in Process.GetProcessesByName(Path.GetFileNameWithoutExtension(self))) {
                using(process) {
                    if(process.Id==Process.GetCurrentProcess().Id) continue;
                    try {
                        if(!string.Equals(process.MainModule.FileName,self,StringComparison.OrdinalIgnoreCase) || process.MainWindowHandle==IntPtr.Zero) continue;
                        AllowSetForegroundWindow(process.Id); PostMessage(process.MainWindowHandle,message,IntPtr.Zero,IntPtr.Zero); return;
                    } catch(System.ComponentModel.Win32Exception) { } // Another user's process cannot be ours.
                    catch(InvalidOperationException) { } // The first process exited while enumerating.
                }
            }
            Thread.Sleep(50); // Wait only for the first instance to create its startup window.
        }
        MessageBox.Show("AudioBook Studio is already starting. Use its taskbar or notification-area icon.","AudioBook Studio");
    }
    // The internal constructor allows an isolated fake server in tests. Production always uses the fixed URL above.
    internal AppLauncher(string folder,Uri address,ProcessStartInfo server,Func<string,bool> confirmation) {
        root=folder; this.address=address; command=server; confirm=confirmation;
        ActivationMessage=RegisterWindowMessage(DesktopPolicy.Identity(root)+".Show");
        Text="AudioBook Studio"; ClientSize=new Size(580,200); FormBorderStyle=FormBorderStyle.FixedDialog;
        MaximizeBox=false; StartPosition=FormStartPosition.CenterScreen; Font=new Font("Segoe UI",10);
        BackColor=Color.FromArgb(22,19,17); ForeColor=Color.FromArgb(241,232,221);
        using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("app.ico"))
        using(var icon=new Icon(stream)) Icon=(Icon)icon.Clone();
        Controls.Add(new PictureBox { Image=Icon.ToBitmap(),SizeMode=PictureBoxSizeMode.Zoom,Bounds=new Rectangle(24,25,50,50) });
        Controls.Add(new Label { Text="AudioBook Studio",Font=new Font("Segoe UI",18,FontStyle.Bold),AutoSize=true,Location=new Point(90,23) });
        status.Text="Starting the local application…"; status.SetBounds(90,65,460,65); Controls.Add(status);
        var journal=new Button { Text="Open startup log",Bounds=new Rectangle(24,144,180,34) };
        journal.Click+=delegate { OpenLog(); }; Controls.Add(journal);
        stop.Click+=delegate { Close(); }; Controls.Add(stop);
        reopen.Click+=async delegate { await ReopenWindow(); }; Controls.Add(reopen);
        var menu=new ContextMenuStrip();
        menu.Items.Add("Show window",null,delegate { ShowWindow(); });
        menu.Items.Add("Open startup log",null,delegate { OpenLog(); });
        menu.Items.Add("Stop and exit",null,delegate { Close(); });
        tray=new NotifyIcon { Icon=Icon,Text="AudioBook Studio",ContextMenuStrip=menu,Visible=true };
        tray.DoubleClick+=delegate { ShowWindow(); };
        poll.Tick+=Tick; Shown+=delegate { StartApp(); }; FormClosing+=CheckClosing; FormClosed+=delegate { StopApp(); };
    }
    protected override void WndProc(ref Message message) {
        if((uint)message.Msg==ActivationMessage) ShowWindow(); base.WndProc(ref message);
    }
    protected override void OnHandleCreated(EventArgs e) {
        base.OnHandleCreated(e); int dark=1;
        DwmSetWindowAttribute(Handle,20,ref dark,sizeof(int)); // Optional dark caption; older Windows may ignore it.
    }
    protected override void OnResize(EventArgs e) {
        base.OnResize(e); if(WindowState!=FormWindowState.Minimized) visibleState=WindowState;
    }
    void ShowWindow() { Show(); if(WindowState==FormWindowState.Minimized) WindowState=visibleState; Activate(); SetForegroundWindow(Handle); }
    internal static string Quote(string value) { return "\""+value.Replace("\"","")+"\""; }
    void OpenLog() { if(File.Exists(InstallationPaths.Log(root,"startup.log"))) Process.Start("notepad.exe",Quote(InstallationPaths.Log(root,"startup.log"))); }
    void WriteLog(string line) { if(line!=null) lock(logLock) { if(output!=null) output.WriteLine(line); } }
    void StartApp() {
        try {
            using(var socket=new TcpClient()) {
                var pending=socket.BeginConnect(address.Host,address.Port,null,null);
                if(pending.AsyncWaitHandle.WaitOne(250)) {
                    try { socket.EndConnect(pending); throw new InvalidOperationException("Port "+address.Port+" is already in use. Close the other application before starting this installation."); }
                    catch(SocketException) { }
                }
            }
            string state=DesktopPolicy.StateFolder(root); Directory.CreateDirectory(state);
            if((File.GetAttributes(state)&FileAttributes.ReparsePoint)!=0) throw new IOException("The .desktop folder must not be a link.");
            Directory.CreateDirectory(Path.GetDirectoryName(InstallationPaths.Log(root,"startup.log")));
            output=new StreamWriter(InstallationPaths.Log(root,"startup.log"),false,new UTF8Encoding(false)) { AutoFlush=true };
            job=new WindowsJob(); child=new Process { StartInfo=command };
            child.OutputDataReceived+=delegate(object sender,DataReceivedEventArgs e) { WriteLog(e.Data); };
            child.ErrorDataReceived+=delegate(object sender,DataReceivedEventArgs e) { WriteLog(e.Data); };
            child.Start(); childStarted=true; job.Attach(child); child.BeginOutputReadLine(); child.BeginErrorReadLine();
            deadline=DateTime.UtcNow.AddSeconds(65); poll.Start();
        } catch(Exception error) { Fail(error.Message); }
    }
    internal async Task<Dictionary<string,object>> ReadStatus() {
        var request=(HttpWebRequest)WebRequest.Create(new Uri(address,"api/status"));
        request.Proxy=null; request.Timeout=2000; request.ReadWriteTimeout=2000;
        return await Task.Run(delegate {
            using(var response=request.GetResponse())
            using(var reader=new StreamReader(response.GetResponseStream()))
                return new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(reader.ReadToEnd());
        });
    }
    async void Tick(object sender,EventArgs e) {
        if(closing || polling) return;
        if(child.HasExited) { Fail(child.ExitCode==0?null:"The application stopped with an error. See startup.log.\n\n"+Tail()); return; }
        if(ready) return; polling=true;
        try {
            await ReadStatus(); if(closing || IsDisposed) return;
            poll.Stop(); status.Text="Opening your application window…";
            await OpenView(); if(closing || IsDisposed) return;
            FormBorderStyle=FormBorderStyle.Sizable; MaximizeBox=true; MinimumSize=new Size(800,600);
            RestorePlacement(); ready=true; poll.Start();
        } catch(WebException) {
            if(DateTime.UtcNow>deadline) Fail("The application did not start in time. See startup.log.\n\n"+Tail());
        } catch(Exception error) { Fail("Could not open the application window: "+error.Message); }
        finally { polling=false; }
    }
    async Task OpenView() {
        string profile=Path.Combine(DesktopPolicy.StateFolder(root),"WebView2");
        if(Directory.Exists(profile) && (File.GetAttributes(profile)&FileAttributes.ReparsePoint)!=0) throw new IOException("The WebView2 profile must not be a link.");
        var environment=await CoreWebView2Environment.CreateAsync(null,profile);
        if(closing || IsDisposed) return;
        var current=new StudioWebView(address); view=current; Controls.Add(current); current.BringToFront();
        await current.Start(environment,address.AbsoluteUri);
        if(closing || IsDisposed) return;
        browserProcess=Process.GetProcessById((int)current.CoreWebView2.BrowserProcessId);
        var browserHandle=browserProcess.Handle; // Retain this process identity even if Windows later reuses its PID.
        current.CoreWebView2.ProcessFailed+=delegate(object s,CoreWebView2ProcessFailedEventArgs failure) {
            if(failure.ProcessFailedKind==CoreWebView2ProcessFailedKind.BrowserProcessExited && !closing && !IsDisposed)
                BeginInvoke((MethodInvoker)delegate { if(view==current && !closing) BrowserFailed(); });
        };
        foreach(Control control in Controls) if(control!=current) control.Visible=false;
    }
    void BrowserFailed() {
        WriteLog("The embedded browser stopped unexpectedly; the backend has been kept running.");
        if(view!=null) view.Visible=false;
        foreach(var popup in OwnedForms) popup.Close();
        foreach(Control control in Controls) if(control!=view) control.Visible=true;
        stop.Text="Stop and exit";
        status.Text="The window stopped unexpectedly. Local jobs continue.\nReopen the window, or stop and exit.";
    }
    internal async Task ReopenWindow() {
        if(closing || checkingClose || openingView) return;
        openingView=true; reopen.Enabled=false;
        try {
            DisposeBrowser(); await OpenView();
        } catch(Exception error) {
            if(!closing && !IsDisposed) {
                BrowserFailed(); WriteLog("Could not reopen the window: "+error.Message);
                status.Text="Could not reopen the window. Local jobs continue.\nSee startup.log; retry or stop and exit.";
            }
        } finally { openingView=false; if(!IsDisposed) reopen.Enabled=true; }
    }
    async void CheckClosing(object sender,FormClosingEventArgs e) {
        if(closing) return;
        if(e.CloseReason==CloseReason.WindowsShutDown) { closing=true; return; }
        e.Cancel=true; if(checkingClose) return; checkingClose=true; bool exit=false;
        if(view!=null) view.Enabled=false;
        try {
            if(ready) {
                string question=null;
                try {
                    var state=await ReadStatus();
                    if(DesktopPolicy.Busy((bool)state["running"],Convert.ToInt32(state["queued"]))) question="A job is running or queued. Stop it and exit?";
                } catch(Exception error) {
                    WriteLog("Could not check job status: "+error.Message);
                    question="Could not check whether a job is running. Stop the application and exit?";
                }
                if(question!=null && !(confirm!=null?confirm(question):ConfirmExit(question))) return;
            }
            exit=true;
        } finally { checkingClose=false; if(!exit && view!=null && !view.IsDisposed) view.Enabled=true; }
        if(exit && !IsDisposed) { closing=true; BeginInvoke((MethodInvoker)Close); }
    }
    bool ConfirmExit(string message) {
        using(var dialog=new Form { Text="AudioBook Studio",ClientSize=new Size(450,148),FormBorderStyle=FormBorderStyle.FixedDialog,
            MaximizeBox=false,MinimizeBox=false,StartPosition=FormStartPosition.CenterParent,Font=Font,Icon=Icon }) {
            dialog.Controls.Add(new Label { Text=message,Bounds=new Rectangle(20,20,410,55) });
            var cancel=new Button { Text="Cancel",Bounds=new Rectangle(170,92,110,34),DialogResult=DialogResult.Cancel };
            var stop=new Button { Text="Stop and exit",Bounds=new Rectangle(294,92,136,34),DialogResult=DialogResult.OK };
            dialog.Controls.Add(cancel); dialog.Controls.Add(stop); dialog.CancelButton=cancel; dialog.AcceptButton=cancel;
            return dialog.ShowDialog(this)==DialogResult.OK;
        }
    }
    string Tail() {
        string file=InstallationPaths.Log(root,"startup.log"); string[] lines=File.Exists(file)?File.ReadAllLines(file):new string[0];
        return string.Join(Environment.NewLine,lines,Math.Max(0,lines.Length-10),Math.Min(10,lines.Length));
    }
    void Fail(string message) {
        if(closing) return; closing=true; poll.Stop();
        if(message!=null) { WriteLog(message); MessageBox.Show(this,message,"AudioBook Studio",MessageBoxButtons.OK,MessageBoxIcon.Error); } Close();
    }
    void RestorePlacement() {
        var size=new Rectangle(0,0,1400,900); Rectangle area=Screen.FromControl(this).WorkingArea;
        size.X=area.Left+(area.Width-size.Width)/2; size.Y=area.Top+(area.Height-size.Height)/2;
        string file=Path.Combine(DesktopPolicy.StateFolder(root),"window.json"); bool maximize=false;
        if(File.Exists(file)) {
            try {
                var data=new JavaScriptSerializer().Deserialize<int[]>(File.ReadAllText(file));
                if(data==null || data.Length!=5) throw new FormatException("Expected five window placement values.");
                size=new Rectangle(data[0],data[1],data[2],data[3]); maximize=data[4]==1; area=Screen.FromRectangle(size).WorkingArea;
            } catch(ArgumentException error) { WriteLog("Ignoring invalid window placement: "+error.Message); }
            catch(IOException error) { WriteLog("Ignoring unreadable window placement: "+error.Message); }
            catch(FormatException error) { WriteLog("Ignoring invalid window placement: "+error.Message); }
        }
        StartPosition=FormStartPosition.Manual; Bounds=DesktopPolicy.Fit(size,area); if(maximize) WindowState=FormWindowState.Maximized;
    }
    void StopApp() {
        closing=true; poll.Stop(); poll.Dispose();
        if(ready) {
            Rectangle b=WindowState==FormWindowState.Normal?Bounds:RestoreBounds;
            try { File.WriteAllText(Path.Combine(DesktopPolicy.StateFolder(root),"window.json"),
                new JavaScriptSerializer().Serialize(new[]{b.X,b.Y,b.Width,b.Height,visibleState==FormWindowState.Maximized?1:0})); }
            catch(IOException error) { WriteLog("Could not save window placement: "+error.Message); }
            catch(UnauthorizedAccessException error) { WriteLog("Could not save window placement: "+error.Message); }
        }
        DisposeBrowser();
        if(tray!=null) { tray.Visible=false; tray.ContextMenuStrip.Dispose(); tray.Dispose(); }
        if(job!=null) job.Dispose();
        if(child!=null) {
            if(childStarted) {
                if(!child.HasExited) { try { child.Kill(); } catch(InvalidOperationException) { if(!child.HasExited) throw; } }
                child.WaitForExit();
            }
            child.Dispose();
        }
        lock(logLock) { if(output!=null) { output.Dispose(); output=null; } }
    }
    void DisposeBrowser() {
        foreach(var popup in OwnedForms) popup.Close();
        if(view!=null) { Controls.Remove(view); view.Dispose(); view=null; }
        if(browserProcess!=null) {
            if(!browserProcess.WaitForExit(5000)) {
                WriteLog("The owned WebView2 browser did not exit after disposal; stopping that process.");
                try { browserProcess.Kill(); } catch(InvalidOperationException) { if(!browserProcess.HasExited) throw; }
                browserProcess.WaitForExit();
            }
            browserProcess.Dispose(); browserProcess=null;
        }
    }
}
