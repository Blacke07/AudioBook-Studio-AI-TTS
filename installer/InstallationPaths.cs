using System;
using System.IO;

static class InstallationPaths {
    internal const string Program="Data/Program";
    internal const string User="Data/User";
    internal const string State="Data/State";
    internal const string Manifest="Data/State/installation-manifest.json";
    internal const string Marker="Data/State/.studio-install-incomplete";
    internal static string At(string root,string relative) { return Path.Combine(root,relative.Replace('/',Path.DirectorySeparatorChar)); }
    internal static string Log(string root,string name) { return At(root,State+"/logs/"+name); }
    internal static void CheckLength(string path) {
        if(Path.GetFullPath(path).Length>=240) throw new InvalidOperationException(
            "This path is too long for the Windows application tools. Choose a shorter installation folder: "+path);
    }
}
