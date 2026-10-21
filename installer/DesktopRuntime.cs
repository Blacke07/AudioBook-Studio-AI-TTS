// The shared Evergreen runtime is a prerequisite, never owned or removed by this application.
using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

static class DesktopRuntime {
    public const string DownloadPage="https://developer.microsoft.com/microsoft-edge/webview2/";
    public const string BootstrapUrl="https://go.microsoft.com/fwlink/p/?LinkId=2124703";
    const string Client=@"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";
    internal static bool ValidVersion(string text) { Version version; return Version.TryParse(text,out version) && version.Major>0; }
    public static bool Available() {
        foreach(var hive in new[]{RegistryHive.LocalMachine,RegistryHive.CurrentUser})
            foreach(var view in new[]{RegistryView.Registry32,RegistryView.Registry64})
                using(var root=RegistryKey.OpenBaseKey(hive,view))
                using(var key=root.OpenSubKey(Client)) {
                    if(key!=null && ValidVersion(key.GetValue("pv","").ToString())) return true;
                }
        return false;
    }
    public static async Task<bool> EnsureForSetup(IWin32Window owner) {
        if(Available()) return true;
        if(MessageBox.Show(owner,"AudioBook Studio needs Microsoft Edge WebView2 Runtime for its own window.\n\n"+
            "Download and install the shared Microsoft runtime now? This needs internet access and accepts Microsoft's runtime license terms.\n\n"+
            "The runtime receives Microsoft's updates and is kept when AudioBook Studio is uninstalled.\n"+DownloadPage,
            "Microsoft WebView2 Runtime",MessageBoxButtons.YesNo,MessageBoxIcon.Question,MessageBoxDefaultButton.Button2)!=DialogResult.Yes) return false;
        string folder=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"AudioBookStudio-Installer","WebView2");
        Directory.CreateDirectory(folder);
        string file=Path.Combine(folder,"MicrosoftEdgeWebview2Setup-"+Guid.NewGuid().ToString("N")+".exe");
        try {
            ServicePointManager.SecurityProtocol|=SecurityProtocolType.Tls12;
            using(var client=new WebClient()) await client.DownloadFileTaskAsync(new Uri(BootstrapUrl),file);
            // Evergreen is mutable: require Windows' Authenticode chain validation and Microsoft's exact signer.
            await Task.Run(delegate {
                using(var verified=OpenVerifiedBootstrapper(file))
                using(var setup=Process.Start(new ProcessStartInfo(file,"/silent /install") { UseShellExecute=false,CreateNoWindow=true })) {
                    setup.WaitForExit();
                    if(setup.ExitCode!=0 && setup.ExitCode!=3010) throw new IOException("Microsoft WebView2 setup returned code "+setup.ExitCode+".");
                }
            });
            if(!Available()) throw new IOException("WebView2 Runtime is not available yet. Finish Microsoft's installation or restart Windows, then run AudioBook Studio setup again.");
            return true;
        } finally { if(File.Exists(file)) File.Delete(file); }
    }
    internal static FileStream OpenVerifiedBootstrapper(string file) {
        var stream=new FileStream(file,FileMode.Open,FileAccess.Read,FileShare.Read);
        try { VerifyBootstrapper(file); return stream; }
        catch { stream.Dispose(); throw; }
    }
    internal static void VerifyBootstrapper(string file) {
        string script="$ProgressPreference='SilentlyContinue'; $ErrorActionPreference='Stop'; "+
            "Import-Module (Join-Path $PSHOME 'Modules\\Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1'); "+
            "$s=Get-AuthenticodeSignature -LiteralPath '"+file.Replace("'","''")+"'; "+
            "if($s.Status -ne 'Valid' -or $s.SignerCertificate.GetNameInfo('SimpleName',$false) -ne 'Microsoft Corporation'){Write-Output $s.Status; exit 1}";
        var check=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell/v1.0/powershell.exe"),
            "-NoProfile -NonInteractive -EncodedCommand "+Convert.ToBase64String(Encoding.Unicode.GetBytes(script))) {
                UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true };
        using(var signature=Process.Start(check)) {
            string detail=signature.StandardOutput.ReadToEnd().Trim();
            signature.WaitForExit();
            if(signature.ExitCode!=0) throw new IOException("The WebView2 bootstrapper did not have a valid Microsoft signature ("+detail+"). It was not run.");
        }
    }
}
