// Web content stays local. No host-object bridge, remote debugging or browser-profile reuse.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

sealed class StudioWebView : WebView2 {
    readonly Uri origin;
    public StudioWebView(Uri origin) { this.origin=origin; Dock=DockStyle.Fill; DefaultBackgroundColor=Color.FromArgb(22,19,17); }
    public async Task Start(CoreWebView2Environment environment,string address) {
        await EnsureCoreWebView2Async(environment);
        var core=CoreWebView2;
        core.Settings.AreHostObjectsAllowed=false;
        core.Settings.IsWebMessageEnabled=false;
        core.Settings.IsStatusBarEnabled=false;
        core.Settings.IsPasswordAutosaveEnabled=false;
        core.Settings.IsGeneralAutofillEnabled=false;
        core.PermissionRequested+=delegate(object sender,CoreWebView2PermissionRequestedEventArgs e) {
            e.State=CoreWebView2PermissionState.Deny; e.Handled=true;
        };
        core.NavigationStarting+=delegate(object sender,CoreWebView2NavigationStartingEventArgs e) {
            if(DesktopPolicy.Local(origin,e.Uri)) return;
            e.Cancel=true;
            if(e.IsUserInitiated && DesktopPolicy.External(e.Uri)) OpenExternal(e.Uri);
        };
        core.FrameNavigationStarting+=delegate(object sender,CoreWebView2NavigationStartingEventArgs e) {
            if(!DesktopPolicy.Local(origin,e.Uri)) e.Cancel=true;
        };
        core.AddWebResourceRequestedFilter("*",CoreWebView2WebResourceContext.All);
        core.WebResourceRequested+=delegate(object sender,CoreWebView2WebResourceRequestedEventArgs e) {
            string uri=e.Request.Uri;
            if(!DesktopPolicy.Local(origin,uri) && !uri.StartsWith("data:") && !uri.StartsWith("blob:"))
                e.Response=environment.CreateWebResourceResponse(new MemoryStream(),403,"Local content only","");
        };
        core.NewWindowRequested+=async delegate(object sender,CoreWebView2NewWindowRequestedEventArgs e) {
            e.Handled=true;
            if(!DesktopPolicy.Local(origin,e.Uri)) {
                if(e.IsUserInitiated && DesktopPolicy.External(e.Uri)) OpenExternal(e.Uri);
                return;
            }
            using(var deferral=e.GetDeferral()) {
                var owner=FindForm();
                var popup=new Form { Text="AudioBook Studio — Preview",Icon=owner.Icon,Size=new Size(1100,760),
                    StartPosition=FormStartPosition.CenterParent,BackColor=DefaultBackgroundColor };
                var view=new StudioWebView(origin); popup.Controls.Add(view);
                try {
                    popup.Show(owner); await view.Start(environment,null); e.NewWindow=view.CoreWebView2;
                    view.CoreWebView2.WindowCloseRequested+=delegate { popup.Close(); };
                } catch(Exception error) {
                    popup.Dispose(); MessageBox.Show(owner,"Could not open the preview: "+error.Message,"AudioBook Studio");
                }
            }
        };
        core.DownloadStarting+=async delegate(object sender,CoreWebView2DownloadStartingEventArgs e) {
            e.Handled=true;
            if(!DesktopPolicy.Local(origin,e.DownloadOperation.Uri)) { e.Cancel=true; return; }
            using(var deferral=e.GetDeferral()) {
                await Task.Yield(); // Native modal UI must run after the WebView2 callback has returned.
                if(IsDisposed) { e.Cancel=true; return; }
                using(var dialog=new SaveFileDialog { Title="Save AudioBook Studio download",FileName=Path.GetFileName(e.ResultFilePath),
                    DefaultExt=Path.GetExtension(e.ResultFilePath).TrimStart('.'),Filter="All files (*.*)|*.*",
                    OverwritePrompt=true,RestoreDirectory=true }) {
                    if(dialog.ShowDialog(FindForm())!=DialogResult.OK) { e.Cancel=true; return; }
                    e.ResultFilePath=dialog.FileName;
                }
            }
        };
        if(address!=null) core.Navigate(address);
    }
    static void OpenExternal(string uri) {
        try { Process.Start(new ProcessStartInfo(uri) { UseShellExecute=true }); }
        catch(System.ComponentModel.Win32Exception error) { MessageBox.Show("Could not open the link: "+error.Message,"AudioBook Studio"); }
    }
}
