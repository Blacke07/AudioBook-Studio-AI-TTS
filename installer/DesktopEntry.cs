using System;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;

// Resolve the embedded browser SDK before the CLR loads AppLauncher and its WebView fields.
static class DesktopEntry {
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern bool SetDllDirectory(string path);
    [STAThread] static int Main(string[] args) {
        string root=Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string program=InstallationPaths.At(root,InstallationPaths.Program);
        // Build/resource checks run next to the cached SDK; installations always use Data/Program.
        if(!Directory.Exists(program)) program=root;
        AppDomain.CurrentDomain.AssemblyResolve+=delegate(object sender,ResolveEventArgs e) {
            string name=new AssemblyName(e.Name).Name;
            if(name!="Microsoft.Web.WebView2.Core" && name!="Microsoft.Web.WebView2.WinForms") return null;
            return Assembly.LoadFrom(Path.Combine(program,name+".dll"));
        };
        SetDllDirectory(program);
        return Run(args);
    }
    [MethodImpl(MethodImplOptions.NoInlining)] static int Run(string[] args) { return AppLauncher.Run(args); }
}
