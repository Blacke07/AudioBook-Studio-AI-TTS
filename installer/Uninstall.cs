// Remove an AudioBook Studio installation: only what setup installed; the user's own data only on request.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

class Uninstaller {
    const string Title="Uninstall AudioBook Studio";
    const string ExeName="Uninstall AudioBook Studio.exe";
    const string Manifest="installation-manifest.json";
    const string Marker=".studio-install-incomplete";
    const string TempPrefix="AudioBookStudio-Uninstall-";
    const string Shortcuts="shortcuts.txt";  // shortcuts setup created, one path per line
    // Folders setup creates in full; nothing of the user's is stored in them.
    static readonly string[] OwnedTrees={"runtime",".venv",".install",".downloads","tools\\ffmpeg","tools\\ollama","licenses\\ffmpeg"};
    static readonly string[] OwnedFiles={"install.log","startup.log",Marker};
    // The user's own work. Kept unless the user explicitly asks to delete it.
    static readonly string[] DataFiles={"settings.json","characters.json","volumes.json"};
    static readonly string[] DataTrees={"voices","work","export"};

    readonly string root;
    readonly bool dryRun;
    bool deleteData;
    long freed;
    int removed;
    readonly List<string> failures=new List<string>(), planned=new List<string>();

    Uninstaller(string root,bool dryRun) { this.root=root; this.dryRun=dryRun; }

    [STAThread] static int Main(string[] args) {
        Application.EnableVisualStyles();
        var options=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
        for(int i=0;i<args.Length;i++)
            if(args[i].StartsWith("--")) options[args[i]]=i+1<args.Length && !args[i+1].StartsWith("--") ? args[++i] : "";
        string self=Assembly.GetExecutingAssembly().Location;
        if(options.ContainsKey("--check")) { new JavaScriptSerializer().DeserializeObject("{}"); return 0; }
        bool quiet=options.ContainsKey("--yes");
        string report=options.ContainsKey("--report") ? options["--report"] : null;
        Uninstaller job=null;
        try {
            string target=Path.GetFullPath(options.ContainsKey("--target") ? options["--target"] : Path.GetDirectoryName(self)).TrimEnd('\\');
            // A program cannot delete its own EXE: run from a temporary copy and let this one exit first.
            if(!options.ContainsKey("--dry-run") && IsInside(self,target)) return Relaunch(self,target,options);
            if(options.ContainsKey("--wait")) WaitFor(int.Parse(options["--wait"]));
            job=new Uninstaller(target,options.ContainsKey("--dry-run"));
            int code=job.Run(quiet,options.ContainsKey("--delete-data"));
            job.Report(report,code,null);
            return code;
        } catch(Exception error) {
            int code=error is RunningException ? 2 : 1;
            if(job!=null) job.Report(report,code,error.Message); else WriteReport(report,code,error.Message,null);
            if(!quiet) MessageBox.Show(error.Message+"\n\nNothing was removed.",Title,MessageBoxButtons.OK,MessageBoxIcon.Warning);
            return code;
        } finally { CleanTemporaryCopy(self); }
    }

    class RunningException : InvalidOperationException { public RunningException(string message):base(message) { } }

    int Run(bool quiet,bool deleteRequested) {
        var manifest=Inspect();
        var running=RunningFromHere();
        if(running.Count>0)
            throw new RunningException("Close AudioBook Studio and its control window before uninstalling.\n\nStill running from this folder: "+string.Join(", ",running));
        bool hasData=DataPaths(manifest).Any(path => File.Exists(path) || Directory.Exists(path));
        if(!quiet) {
            string question="Remove AudioBook Studio from this folder?\n\n"+root+"\n\n"+
                "This removes the application, its private Python, the TTS engine, FFmpeg, Ollama and the downloaded models "+
                "("+Size(AppPaths(manifest).Concat(OwnedTrees.Select(tree => Path.Combine(root,tree))))+").\n\n"+
                "Your manuscripts are not touched: they stay in the folders you chose. "+
                "Local Models, the setup EXE and other files you placed here are kept.\n\nContinue?";
            if(MessageBox.Show(question,Title,MessageBoxButtons.YesNo,MessageBoxIcon.Question,MessageBoxDefaultButton.Button2)!=DialogResult.Yes)
                return 5;
            if(hasData) {
                string data="Also delete your AudioBook Studio data in this folder ("+Size(DataPaths(manifest))+")?\n\n"+
                    "• settings, characters and the list of volumes\n• fixed voices (voices folder)\n"+
                    "• generated passages and chapter audio (work folder)\n• exported audiobooks (export folder)\n\n"+
                    "No keeps them in this folder. Yes deletes them permanently.";
                deleteRequested=MessageBox.Show(data,Title,MessageBoxButtons.YesNo,MessageBoxIcon.Warning,MessageBoxDefaultButton.Button2)==DialogResult.Yes;
            }
        }
        deleteData=deleteRequested;
        RemoveShortcuts();
        foreach(string tree in OwnedTrees) Delete(Path.Combine(root,tree));
        foreach(string file in OwnedFiles) Delete(Path.Combine(root,file));
        foreach(string path in AppPaths(manifest)) if(!IsSelf(path)) Delete(path);
        foreach(string cache in Caches(root)) Delete(cache);
        if(deleteData) foreach(string path in DataPaths(manifest)) Delete(path);
        RemoveEmptyFolders(manifest);
        // Keep the uninstaller and its manifest while something is left over, so it can run again.
        if(failures.Count==0) { Delete(Path.Combine(root,ExeName)); Delete(Path.Combine(root,Manifest)); Delete(Path.Combine(root,Shortcuts)); }
        bool rootRemoved=!dryRun && failures.Count==0 && Directory.Exists(root) && !Directory.EnumerateFileSystemEntries(root).Any() && TryRemove(root);
        if(!quiet) Summary(rootRemoved);
        return failures.Count>0 ? 3 : 0;
    }

    // -- what belongs to the installation -----------------------------------------------------------
    Dictionary<string,object> Inspect() {
        if(Path.GetPathRoot(root).TrimEnd('\\').Equals(root,StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("A drive root is never an AudioBook Studio installation.");
        if(!Directory.Exists(root)) throw new InvalidOperationException("Folder not found: "+root);
        if((File.GetAttributes(root)&FileAttributes.ReparsePoint)!=0)
            throw new InvalidOperationException("The installation folder is a link to another folder. Remove the link itself instead.");
        string manifestFile=Path.Combine(root,Manifest), marker=Path.Combine(root,Marker);
        Dictionary<string,object> manifest=null;
        if(File.Exists(manifestFile)) {
            try { manifest=new JavaScriptSerializer { MaxJsonLength=int.MaxValue }.DeserializeObject(File.ReadAllText(manifestFile,Encoding.UTF8)) as Dictionary<string,object>; }
            catch(ArgumentException) { manifest=null; }
            if(manifest==null || !manifest.ContainsKey("payload_files") || !manifest.ContainsKey("models") || !manifest.ContainsKey("gemma"))
                throw NotAnInstallation();
        } else if(!File.Exists(marker) || File.ReadAllText(marker).Trim()!="AudioBookStudio-Installer-1") throw NotAnInstallation();
        foreach(string relative in Relative(manifest,"payload_files").Concat(Relative(manifest,"initial_state_files")).Concat(ModelPaths(manifest)))
            Inside(relative);  // a damaged or foreign manifest must never point outside the installation
        return manifest;
    }

    InvalidOperationException NotAnInstallation() {
        return new InvalidOperationException("This folder is not an AudioBook Studio installation (installation-manifest.json is missing or invalid):\n"+root);
    }

    static IEnumerable<string> Relative(Dictionary<string,object> manifest,string key) {
        if(manifest==null || !manifest.ContainsKey(key)) yield break;
        foreach(object item in (object[])manifest[key]) yield return (string)((Dictionary<string,object>)item)["path"];
    }

    static IEnumerable<string> ModelPaths(Dictionary<string,object> manifest) {
        if(manifest==null) yield break;
        foreach(object item in (object[])manifest["models"]) yield return "models\\"+(string)((Dictionary<string,object>)item)["name"];
        var gemma=(Dictionary<string,object>)manifest["gemma"];
        foreach(object item in (object[])gemma["blobs"]) yield return "models\\ollama\\blobs\\"+((string)((Dictionary<string,object>)item)["digest"]).Replace(':','-');
        string tag=gemma.ContainsKey("tag")?(string)gemma["tag"]:"gemma4:12b";   // repository:version
        yield return "models\\ollama\\manifests\\registry.ollama.ai\\library\\"+tag.Replace(':','\\');
    }

    string Inside(string relative) {
        if(string.IsNullOrEmpty(relative) || Path.IsPathRooted(relative) || relative.Contains(":") ||
           relative.Split('/','\\').Any(part => part==".."))
            throw new InvalidOperationException("The installation manifest names a path outside this folder: "+relative+". Nothing was removed.");
        string full=Path.GetFullPath(Path.Combine(root,relative));
        if(!IsInside(full,root)) throw new InvalidOperationException("The installation manifest names a path outside this folder: "+relative);
        return full;
    }

    IEnumerable<string> AppPaths(Dictionary<string,object> manifest) {
        return Relative(manifest,"payload_files").Concat(ModelPaths(manifest)).Select(Inside);
    }

    IEnumerable<string> DataPaths(Dictionary<string,object> manifest) {
        return DataFiles.Concat(DataTrees).Select(name => Path.Combine(root,name))
            .Concat(Relative(manifest,"initial_state_files").Select(Inside)).Distinct(StringComparer.OrdinalIgnoreCase);
    }

    bool IsSelf(string path) {
        string name=Path.GetFileName(path);
        return IsInside(path,root) && Path.GetDirectoryName(path).Equals(root,StringComparison.OrdinalIgnoreCase) &&
               (name.Equals(ExeName,StringComparison.OrdinalIgnoreCase) || name.Equals(Manifest,StringComparison.OrdinalIgnoreCase));
    }

    // Python byte-code caches next to the application's own modules (never inside the user's data).
    IEnumerable<string> Caches(string folder) {
        foreach(string directory in SafeDirectories(folder)) {
            string name=Path.GetFileName(directory);
            if(folder==root && DataTrees.Contains(name,StringComparer.OrdinalIgnoreCase)) continue;
            if(name=="__pycache__") { yield return directory; continue; }
            foreach(string inner in Caches(directory)) yield return inner;
        }
    }

    static IEnumerable<string> SafeDirectories(string folder) {
        string[] entries;
        try { entries=Directory.GetDirectories(folder); } catch(IOException) { yield break; } catch(UnauthorizedAccessException) { yield break; }
        foreach(string entry in entries) if((File.GetAttributes(entry)&FileAttributes.ReparsePoint)==0) yield return entry;
    }

    List<string> RunningFromHere() {
        var names=new SortedSet<string>(StringComparer.OrdinalIgnoreCase);
        int me=Process.GetCurrentProcess().Id;
        foreach(var process in Process.GetProcesses()) {
            try { if(process.Id!=me && IsInside(process.MainModule.FileName,root)) names.Add(Path.GetFileName(process.MainModule.FileName)); }
            catch(Exception) { }  // system processes or other users' processes cannot belong to this folder
            finally { process.Dispose(); }
        }
        return names.ToList();
    }

    // -- removal ------------------------------------------------------------------------------------
    void Delete(string path) {
        if(!File.Exists(path) && !Directory.Exists(path)) return;
        if(!IsInside(path,root)) { failures.Add(path+": outside the installation"); return; }
        if(dryRun) { planned.Add(path.Substring(root.Length+1)); return; }
        try {
            var attributes=File.GetAttributes(path);
            if((attributes&FileAttributes.ReparsePoint)!=0) {
                // A link: remove the link itself, never what it points to.
                if((attributes&FileAttributes.Directory)!=0) Directory.Delete(path,false); else File.Delete(path);
                removed++;
                return;
            }
            if((attributes&FileAttributes.Directory)!=0) {
                foreach(string entry in Directory.GetFileSystemEntries(path)) Delete(entry);
                if(!Directory.EnumerateFileSystemEntries(path).Any()) Directory.Delete(path,false);
                return;
            }
            long length=new FileInfo(path).Length;
            if((attributes&FileAttributes.ReadOnly)!=0) File.SetAttributes(path,attributes&~FileAttributes.ReadOnly);
            File.Delete(path);
            freed+=length; removed++;
        } catch(IOException error) { failures.Add(path+": "+error.Message); }
        catch(UnauthorizedAccessException error) { failures.Add(path+": "+error.Message); }
    }

    // Desktop and Start menu shortcuts setup recorded. Each is removed only while it still opens this installation.
    void RemoveShortcuts() {
        string list=Path.Combine(root,Shortcuts);
        if(!File.Exists(list)) return;
        foreach(string line in File.ReadAllLines(list)) {
            string link=line.Trim();
            if(!link.EndsWith(".lnk",StringComparison.OrdinalIgnoreCase) || !File.Exists(link)) continue;
            string target;
            try { target=LinkTarget(link); } catch(Exception) { continue; }
            if(string.IsNullOrEmpty(target) || !IsInside(target,root)) continue;  // replaced by something else: not ours
            if(dryRun) { planned.Add(link); continue; }
            try { File.Delete(link); removed++; }
            catch(IOException error) { failures.Add(link+": "+error.Message); }
            catch(UnauthorizedAccessException error) { failures.Add(link+": "+error.Message); }
        }
    }

    static string LinkTarget(string link) {
        object shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
        try {
            object shortcut=shell.GetType().InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[] { link });
            try { return (string)shortcut.GetType().InvokeMember("TargetPath",BindingFlags.GetProperty,null,shortcut,null); }
            finally { Marshal.ReleaseComObject(shortcut); }
        } finally { Marshal.ReleaseComObject(shell); }
    }

    void RemoveEmptyFolders(Dictionary<string,object> manifest) {
        var tops=new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "models","tools","licenses" };
        foreach(string relative in Relative(manifest,"payload_files")) {
            string[] parts=relative.Split('/','\\');
            if(parts.Length>1) tops.Add(parts[0]);
        }
        if(deleteData) foreach(string tree in DataTrees) tops.Add(tree);
        foreach(string top in tops) {
            string folder=Path.Combine(root,top);
            if(Directory.Exists(folder) && (File.GetAttributes(folder)&FileAttributes.ReparsePoint)==0) PruneEmpty(folder);
        }
    }

    void PruneEmpty(string folder) {
        foreach(string inner in SafeDirectories(folder)) PruneEmpty(inner);
        if(!dryRun && !Directory.EnumerateFileSystemEntries(folder).Any()) TryRemove(folder);
    }

    bool TryRemove(string folder) {
        try { Directory.Delete(folder,false); return true; }
        catch(IOException) { return false; } catch(UnauthorizedAccessException) { return false; }
    }

    // -- reporting ----------------------------------------------------------------------------------
    void Summary(bool rootRemoved) {
        var text=new StringBuilder();
        text.Append(failures.Count==0 ? "AudioBook Studio was removed." : "AudioBook Studio was partly removed.");
        text.Append(" Freed "+Size(freed)+".\n\n");
        if(failures.Count>0)
            text.Append(failures.Count+" item(s) could not be removed, for example:\n"+failures[0]+
                        "\n\nClose programs using these files and run "+ExeName+" again.\n\n");
        if(!deleteData && DataPaths(null).Any(path => File.Exists(path) || Directory.Exists(path)))
            text.Append("Your data was kept in:\n"+root+"\n(settings, voices, work, export). Delete that folder yourself when you no longer need it.\n\n");
        else if(rootRemoved) text.Append("The installation folder was removed.\n\n");
        text.Append("The shared setup download cache can be deleted separately:\n"+
                    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"AudioBookStudio-Installer"));
        MessageBox.Show(text.ToString(),Title,MessageBoxButtons.OK,failures.Count==0 ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
    }

    void Report(string file,int code,string error) {
        var kept=Directory.Exists(root) ? Directory.EnumerateFileSystemEntries(root).Select(Path.GetFileName).OrderBy(name => name).ToList() : new List<string>();
        WriteReport(file,code,error,new Dictionary<string,object> {
            {"root",root},{"removed_files",removed},{"freed_bytes",freed},{"failures",failures},{"kept",kept},
            {"planned",planned},{"deleted_data",deleteData},{"temporary_copy",Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location)}});
    }

    static void WriteReport(string file,int code,string error,Dictionary<string,object> details) {
        if(string.IsNullOrEmpty(file)) return;
        var result=details ?? new Dictionary<string,object>();
        result["code"]=code;
        result["error"]=error;
        File.WriteAllText(file,new JavaScriptSerializer().Serialize(result),new UTF8Encoding(false));
    }

    string Size(IEnumerable<string> paths) { return Size(paths.Sum(path => Measure(path))); }

    static long Measure(string path) {
        try {
            if(File.Exists(path)) return new FileInfo(path).Length;
            if(!Directory.Exists(path) || (File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0) return 0;
            return Directory.GetFiles(path).Sum(file => Measure(file))+SafeDirectories(path).Sum(folder => Measure(folder));
        } catch(IOException) { return 0; } catch(UnauthorizedAccessException) { return 0; }
    }

    static string Size(long bytes) {
        return bytes>=1L<<30 ? (bytes/(double)(1L<<30)).ToString("0.0")+" GB" : (bytes/(double)(1L<<20)).ToString("0")+" MB";
    }

    // -- running from a temporary copy --------------------------------------------------------------
    static bool IsInside(string path,string folder) {
        return Path.GetFullPath(path).StartsWith(Path.GetFullPath(folder).TrimEnd('\\')+"\\",StringComparison.OrdinalIgnoreCase);
    }

    static string Quote(string value) { return "\""+value.Replace("\"","").TrimEnd('\\')+"\""; }

    static int Relaunch(string self,string target,Dictionary<string,string> options) {
        string folder=Path.Combine(Path.GetTempPath(),TempPrefix+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        string copy=Path.Combine(folder,ExeName);
        File.Copy(self,copy);
        var arguments=new StringBuilder("--target "+Quote(target)+" --wait "+Process.GetCurrentProcess().Id);
        foreach(string flag in new[] { "--yes","--delete-data" }) if(options.ContainsKey(flag)) arguments.Append(" "+flag);
        if(options.ContainsKey("--report")) arguments.Append(" --report "+Quote(options["--report"]));
        Process.Start(new ProcessStartInfo(copy,arguments.ToString()) { UseShellExecute=false,WorkingDirectory=folder });
        return 0;
    }

    static void WaitFor(int id) {
        try { using(var process=Process.GetProcessById(id)) process.WaitForExit(30000); }
        catch(ArgumentException) { }  // already exited
    }

    static void CleanTemporaryCopy(string self) {
        string folder=Path.GetDirectoryName(self);
        if(!Path.GetFileName(folder).StartsWith(TempPrefix) || !IsInside(folder,Path.GetTempPath())) return;
        Process.Start(new ProcessStartInfo("cmd.exe","/c ping 127.0.0.1 -n 3 > nul & rmdir /s /q "+Quote(folder)) {
            UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=Path.GetTempPath() });
    }
}
