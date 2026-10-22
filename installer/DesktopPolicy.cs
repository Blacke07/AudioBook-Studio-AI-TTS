// Pure decisions shared by the desktop host and its process tests.
using System;
using System.Drawing;
using System.IO;
using System.Security.Cryptography;
using System.Text;

static class DesktopPolicy {
    public const string Address="http://127.0.0.1:7863/";
    public static string Identity(string root) {
        using(var sha=SHA256.Create())
            return "AudioBookStudio."+BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(
                Path.GetFullPath(root).TrimEnd('\\').ToUpperInvariant()))).Replace("-","");
    }
    public static string StateFolder(string root) { return InstallationPaths.At(root,"Data/State/desktop"); }
    public static bool Local(Uri origin,string address) {
        Uri target;
        return Uri.TryCreate(address,UriKind.Absolute,out target) && target.Scheme==origin.Scheme &&
            target.Host==origin.Host && target.Port==origin.Port && string.IsNullOrEmpty(target.UserInfo);
    }
    public static bool External(string address) {
        Uri target;
        return Uri.TryCreate(address,UriKind.Absolute,out target) &&
            (target.Scheme=="https" || target.Scheme=="http") && string.IsNullOrEmpty(target.UserInfo);
    }
    public static bool Busy(bool running,int queued) { return running || queued>0; }
    public static Rectangle Fit(Rectangle saved,Rectangle area) {
        int width=Math.Min(Math.Max(saved.Width,800),area.Width), height=Math.Min(Math.Max(saved.Height,600),area.Height);
        return new Rectangle(Math.Max(area.Left,Math.Min(saved.Left,area.Right-width)),
            Math.Max(area.Top,Math.Min(saved.Top,area.Bottom-height)),width,height);
    }
}
