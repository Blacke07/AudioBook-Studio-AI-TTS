using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

class AppLauncher : Form {
    static readonly string Root=Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
    const string Url="http://127.0.0.1:7863/";
    Process child;
    WindowsJob job;
    StreamWriter output;
    readonly object logLock=new object();
    Label status=new Label();
    Button open=new Button();
    System.Windows.Forms.Timer poll=new System.Windows.Forms.Timer();
    DateTime deadline;
    bool ready,closing,childStarted;

    [STAThread] static int Main(string[] args) {
        if(args.Length>0 && args[0]=="--check-resources") {
            using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("app.ico"))
            using(var icon=new Icon(stream)) return icon.Width>0 ? 0:1;
        }
        if(args.Length>0 && args[0]=="--check-installation") {
            try { CheckFiles(); return 0; } catch(Exception error) { Console.Error.WriteLine(error.Message); return 1; }
        }
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        string name;
        using(var sha=SHA256.Create()) name=BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(Root.ToUpperInvariant()))).Replace("-","");
        bool first;
        using(var mutex=new Mutex(true,"Local\\AudioBookStudio-"+name,out first)) {
            if(!first) { MessageBox.Show("AudioBook Studio is already running. Use its existing control window.","AudioBook Studio"); return 0; }
            try { CheckFiles(); Application.Run(new AppLauncher()); }
            catch(Exception error) { MessageBox.Show(error.Message,"AudioBook Studio",MessageBoxButtons.OK,MessageBoxIcon.Error); return 1; }
        }
        return 0;
    }

    static void CheckFiles() {
        foreach(string name in new string[]{".venv/Scripts/python.exe","launcher.py","app.py","installation-manifest.json"})
            if(!File.Exists(Path.Combine(Root,name))) throw new FileNotFoundException("Incomplete installation: missing "+name+". Run the installer in a dedicated application folder.");
    }

    public AppLauncher() {
        Text="AudioBook Studio"; ClientSize=new Size(580,200); FormBorderStyle=FormBorderStyle.FixedDialog;
        MaximizeBox=false; StartPosition=FormStartPosition.CenterScreen; Font=new Font("Segoe UI",10);
        using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("app.ico"))
        using(var icon=new Icon(stream)) Icon=(Icon)icon.Clone();
        Controls.Add(new PictureBox { Image=Icon.ToBitmap(), SizeMode=PictureBoxSizeMode.Zoom, Bounds=new Rectangle(24,25,50,50) });
        Controls.Add(new Label { Text="AudioBook Studio",Font=new Font("Segoe UI",18,FontStyle.Bold),AutoSize=true,Location=new Point(90,23) });
        status.Text="Starting the local application…"; status.SetBounds(90,65,460,25); Controls.Add(status);
        Controls.Add(new Label { Text="Closing this window stops the application and its own child processes.",
            AutoSize=false,Bounds=new Rectangle(24,106,530,34) });
        open.Text="Open application"; open.Enabled=false; open.SetBounds(24,151,170,32);
        open.Click+=delegate { OpenApp(); }; Controls.Add(open);
        var journal=new Button { Text="View log",Bounds=new Rectangle(208,151,130,32) };
        journal.Click+=delegate { if(File.Exists(Path.Combine(Root,"startup.log"))) Process.Start("notepad.exe",Quote(Path.Combine(Root,"startup.log"))); };
        Controls.Add(journal);
        var stop=new Button { Text="Stop",Bounds=new Rectangle(424,151,130,32) };
        stop.Click+=delegate { Close(); }; Controls.Add(stop);
        poll.Interval=500; poll.Tick+=Tick;
        Shown+=delegate { StartApp(); };
        FormClosed+=delegate { StopApp(); };
    }
    static string Quote(string value) { return "\""+value.Replace("\"","")+"\""; }
    void WriteLog(string line) { if(line!=null) lock(logLock) { if(output!=null) output.WriteLine(line); } }
    void StartApp() {
        try {
            using(var socket=new TcpClient()) {
                var pending=socket.BeginConnect("127.0.0.1",7863,null,null);
                if(pending.AsyncWaitHandle.WaitOne(250)) {
                    try { socket.EndConnect(pending); throw new InvalidOperationException("Port 7863 is already in use. Close the other application before starting this installation."); }
                    catch(SocketException) { }
                }
            }
            output=new StreamWriter(Path.Combine(Root,"startup.log"),false,new UTF8Encoding(false));output.AutoFlush=true;
            job=new WindowsJob();
            var info=new ProcessStartInfo(Path.Combine(Root,".venv/Scripts/python.exe"),"-u "+Quote(Path.Combine(Root,"launcher.py"))+" --no-browser") {
                WorkingDirectory=Root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,
                StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8
            };
            info.EnvironmentVariables["PYTHONUTF8"]="1";info.EnvironmentVariables["PYTHONIOENCODING"]="utf-8";
            child=new Process { StartInfo=info };
            child.OutputDataReceived+=delegate(object sender,DataReceivedEventArgs e) { WriteLog(e.Data); };
            child.ErrorDataReceived+=delegate(object sender,DataReceivedEventArgs e) { WriteLog(e.Data); };
            child.Start();childStarted=true;job.Attach(child);child.BeginOutputReadLine();child.BeginErrorReadLine();
            deadline=DateTime.UtcNow.AddSeconds(65);poll.Start();
        } catch(Exception error) { MessageBox.Show(error.Message,"AudioBook Studio",MessageBoxButtons.OK,MessageBoxIcon.Error);Close(); }
    }
    void Tick(object sender,EventArgs e) {
        if(closing) return;
        if(child.HasExited) {
            poll.Stop();child.WaitForExit();
            if(child.ExitCode!=0) MessageBox.Show("The application stopped with an error. Details from startup.log:\n\n"+Tail(),"AudioBook Studio",MessageBoxButtons.OK,MessageBoxIcon.Error);
            Close();return;
        }
        if(ready) return;
        try {
            var request=(HttpWebRequest)WebRequest.Create(Url+"api/status");request.Proxy=null;request.Timeout=350;
            using(var response=(HttpWebResponse)request.GetResponse()) {
                if(response.StatusCode==HttpStatusCode.OK) {
                    ready=true;status.Text="The application is running locally.";open.Enabled=true;OpenApp();
                }
            }
        } catch(WebException) { } // Wait for the owned server to finish startup, up to the explicit deadline.
        if(!ready && DateTime.UtcNow>deadline) {
            poll.Stop();MessageBox.Show("The application did not start in time. See startup.log.\n\n"+Tail(),"AudioBook Studio",MessageBoxButtons.OK,MessageBoxIcon.Error);Close();
        }
    }
    string Tail() {
        string[] lines=File.Exists(Path.Combine(Root,"startup.log"))?File.ReadAllLines(Path.Combine(Root,"startup.log")):new string[0];
        return string.Join(Environment.NewLine,lines,Math.Max(0,lines.Length-10),Math.Min(10,lines.Length));
    }
    void OpenApp() {
        try { Process.Start(Url); }
        catch(System.ComponentModel.Win32Exception error) {
            MessageBox.Show("Could not open your browser: "+error.Message+"\nOpen this address manually: "+Url,"AudioBook Studio",MessageBoxButtons.OK,MessageBoxIcon.Error);
        }
    }
    void StopApp() {
        if(closing) return;closing=true;poll.Stop();
        if(job!=null) job.Dispose(); // Closing the job stops only our child process tree, even after a crash.
        if(child!=null) {
            if(childStarted) {
                if(!child.HasExited) {
                    try { child.Kill(); } catch(InvalidOperationException) { if(!child.HasExited) throw; }
                }
                child.WaitForExit();
            }
            child.Dispose();
        }
        lock(logLock) { if(output!=null) { output.Dispose();output=null; } }
    }
}
