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
    static readonly string[] OwnedTrees={"runtime",".venv",".install",".downloads",".desktop","tools\\ffmpeg","tools\\ollama","licenses\\ffmpeg"};
    static readonly string[] OwnedFiles={"install.log","startup.log",Marker};
    // The user's own work. Kept unless the user explicitly asks to delete it.
    static readonly string[] DataFiles={"settings.json","characters.json","volumes.json"};
    static readonly string[] DataTrees={"voices","work","export"};

    readonly string root;
    readonly bool dryRun;
    bool deleteData,deleteAudio,deleteBackups,deleteModels,modern;
    string ManifestPath { get { return Path.Combine(root,modern?InstallationPaths.Manifest:Manifest); } }
    string ShortcutsPath { get { return Path.Combine(root,modern?InstallationPaths.State+"/shortcuts.txt":Shortcuts); } }
    IEnumerable<string> ProgramTrees { get { return modern ? new[]{"Data/Program/runtime","Data/Program/.venv","Data/Program/tools/ffmpeg","Data/Program/tools/ollama","Data/Program/licenses/ffmpeg","Data/State/install","Data/State/downloads","Data/State/desktop","Data/State/logs"} : OwnedTrees; } }
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
            job.deleteAudio=options.ContainsKey("--delete-audiobooks"); job.deleteBackups=options.ContainsKey("--delete-backups"); job.deleteModels=options.ContainsKey("--delete-models");
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
            throw new RunningException("Close AudioBook Studio before uninstalling.\n\nStill running from this folder: "+string.Join(", ",running));
        bool hasData=DataPaths(manifest).Any(path => File.Exists(path) || Directory.Exists(path));
        if(!quiet) {
            string question="Remove AudioBook Studio from this folder?\n\n"+root+"\n\n"+
                "This removes the program, its private Python, TTS engine, FFmpeg and Ollama "+
                "("+Size(AppPaths(manifest).Concat(ProgramTrees.Select(tree => Path.Combine(root,tree))))+").\n\n"+
                "Your audiobooks, backups, models, settings and voices are kept unless you explicitly choose to delete them.\n\n"+
                "Your manuscripts are not touched: they stay in the folders you chose. "+
                "The setup EXE and unknown files you placed here are kept.\n\nContinue?";
            if(MessageBox.Show(question,Title,MessageBoxButtons.YesNo,MessageBoxIcon.Question,MessageBoxDefaultButton.Button2)!=DialogResult.Yes)
                return 5;
            if(hasData) {
                string data="Also delete your AudioBook Studio data in this folder ("+Size(DataPaths(manifest))+")?\n\n"+
                    "• settings, characters and the list of volumes\n• fixed voices (voices folder)\n"+
                    "• generated passages and chapter audio (work folder)\n\n"+
                    "No keeps them in this folder. Yes deletes them permanently.";
                deleteRequested=MessageBox.Show(data,Title,MessageBoxButtons.YesNo,MessageBoxIcon.Warning,MessageBoxDefaultButton.Button2)==DialogResult.Yes;
            }
            deleteAudio=AskDelete("finished audiobooks",modern?"Audiobooks":"export");
            deleteBackups=AskDelete("project and migration backups",modern?"Backups":"projects-backup");
            deleteModels=AskDelete("downloaded models (you would need to download them again)","models");
        }
        deleteData=deleteRequested;
        RemoveShortcuts();
        foreach(string tree in ProgramTrees) Delete(Path.Combine(root,tree));
        foreach(string file in modern?new[]{Marker}:OwnedFiles) Delete(Path.Combine(root,modern?InstallationPaths.State+"/"+file:file));
        foreach(string path in AppPaths(manifest)) if(!IsSelf(path)) Delete(path);
        foreach(string cache in Caches(modern?InstallationPaths.At(root,InstallationPaths.Program):root)) Delete(cache);
        if(deleteData) foreach(string path in DataPaths(manifest)) Delete(path);
        if(deleteAudio) Delete(Path.Combine(root,modern?"Audiobooks":"export"));
        if(deleteBackups) Delete(Path.Combine(root,modern?"Backups":"projects-backup"));
        if(deleteModels) foreach(string path in ModelPaths(manifest)) Delete(Inside(path));
        RemoveEmptyFolders(manifest);
        // Keep the uninstaller on failure; retain installation identity over preserved author data.
        if(failures.Count==0) {
            Delete(Path.Combine(root,ExeName)); Delete(ShortcutsPath);
            // Retain the installation identity for a safe reinstall over preserved data.
            if(deleteData && deleteAudio && deleteBackups && deleteModels) Delete(ManifestPath);
        }
        bool rootRemoved=!dryRun && failures.Count==0 && Directory.Exists(root) && !Directory.EnumerateFileSystemEntries(root).Any() && TryRemove(root);
        if(!quiet) Summary(rootRemoved);
        return failures.Count>0 ? 3 : 0;
    }

    bool AskDelete(string description,string folder) {
        if(!Directory.Exists(Path.Combine(root,folder))) return false;
        return MessageBox.Show("Also permanently delete "+description+"?\n\nNo keeps them. Yes deletes them.",Title,
            MessageBoxButtons.YesNo,MessageBoxIcon.Warning,MessageBoxDefaultButton.Button2)==DialogResult.Yes;
    }

    // -- what belongs to the installation -----------------------------------------------------------
    Dictionary<string,object> Inspect() {
        if(Path.GetPathRoot(root).TrimEnd('\\').Equals(root,StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("A drive root is never an AudioBook Studio installation.");
        if(!Directory.Exists(root)) throw new InvalidOperationException("Folder not found: "+root);
        if((File.GetAttributes(root)&FileAttributes.ReparsePoint)!=0)
            throw new InvalidOperationException("The installation folder is a link to another folder. Remove the link itself instead.");
        foreach(string directory in new[]{"Data","Data/State","Data/Program"}) {
            string path=Path.Combine(root,directory);
            if(Directory.Exists(path) && (File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0)
                throw new InvalidOperationException("An installation parent folder is a link. Nothing was removed: "+path);
        }
        modern=File.Exists(InstallationPaths.At(root,InstallationPaths.Manifest)) || File.Exists(InstallationPaths.At(root,InstallationPaths.Marker));
        string manifestFile=ManifestPath, marker=Path.Combine(root,modern?InstallationPaths.Marker:Marker);
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
        string parent=root;
        string[] components=relative.Replace('\\','/').Split('/');
        foreach(string part in components.Take(components.Length-1)) {
            parent=Path.Combine(parent,part);
            try {
                if((File.GetAttributes(parent)&FileAttributes.ReparsePoint)!=0)
                    throw new InvalidOperationException("A manifest path has a linked parent. Nothing was removed: "+parent);
            } catch(FileNotFoundException) { break; } catch(DirectoryNotFoundException) { break; }
        }
        return full;
    }

    IEnumerable<string> AppPaths(Dictionary<string,object> manifest) {
        foreach(string relative in Relative(manifest,"payload_files")) {
            string normalized=relative.Replace('\\','/');
            if(normalized.StartsWith("models/",StringComparison.OrdinalIgnoreCase) || normalized.StartsWith("Data/User/",StringComparison.OrdinalIgnoreCase) ||
               normalized.StartsWith("Audiobooks/",StringComparison.OrdinalIgnoreCase) || normalized.StartsWith("Backups/",StringComparison.OrdinalIgnoreCase) ||
               DataFiles.Contains(normalized,StringComparer.OrdinalIgnoreCase) || DataTrees.Any(tree=>normalized.StartsWith(tree+"/",StringComparison.OrdinalIgnoreCase))) continue;
            if(modern && !normalized.StartsWith("Data/Program/",StringComparison.OrdinalIgnoreCase) && normalized!="AudioBook Studio.exe" &&
               normalized!=ExeName && normalized!="Data/README.txt") throw new InvalidOperationException("Unexpected program path in installation manifest.");
            yield return Inside(relative);
        }
    }

    IEnumerable<string> DataPaths(Dictionary<string,object> manifest) {
        if(modern) return new[]{InstallationPaths.At(root,InstallationPaths.User)};
        return DataFiles.Concat(new[]{"voices","work","projects-state"}).Select(name => Path.Combine(root,name))
            .Concat(Relative(manifest,"initial_state_files").Where(name=>DataFiles.Contains(name,StringComparer.OrdinalIgnoreCase) ||
                name.Replace('\\','/').StartsWith("voices/",StringComparison.OrdinalIgnoreCase)).Select(Inside)).Distinct(StringComparer.OrdinalIgnoreCase);
    }

    bool IsSelf(string path) {
        string name=Path.GetFileName(path);
        return IsInside(path,root) && Path.GetDirectoryName(path).Equals(root,StringComparison.OrdinalIgnoreCase) &&
               (name.Equals(ExeName,StringComparison.OrdinalIgnoreCase) || name.Equals(Manifest,StringComparison.OrdinalIgnoreCase));
    }

    // Python byte-code caches next to the application's own modules (never inside the user's data).
    IEnumerable<string> Caches(string folder) {
        if(!Directory.Exists(folder)) yield break;
        foreach(string directory in SafeDirectories(folder)) {
            string name=Path.GetFileName(directory);
            if(folder==root && new[]{"models","Data","Audiobooks","Backups","projects-backup"}.Contains(name,StringComparer.OrdinalIgnoreCase)) continue;
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
        string list=ShortcutsPath;
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
        if(modern) { string program=InstallationPaths.At(root,InstallationPaths.Program); if(Directory.Exists(program)) PruneEmpty(program); return; }
        var tops=new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "tools","licenses" };
        foreach(string relative in Relative(manifest,"payload_files")) {
            string[] parts=relative.Split('/','\\');
            if(parts.Length>1 && parts[0]!="models" && !DataTrees.Contains(parts[0])) tops.Add(parts[0]);
        }
        if(deleteData) foreach(string tree in new[]{"voices","work"}) tops.Add(tree);
        if(deleteModels) tops.Add("models");
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
            text.Append("Your data was kept in:\n"+root+"\nYou can reinstall here. Keep Audiobooks, Backups, models and Data/User while you need them.\n\n");
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
        foreach(string flag in new[] { "--yes","--delete-data","--delete-audiobooks","--delete-backups","--delete-models" }) if(options.ContainsKey(flag)) arguments.Append(" "+flag);
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
        string script="Start-Sleep -Seconds 2; $target='"+folder.Replace("'","''")+"'; "+
            "$resolved=[IO.Path]::GetFullPath($target); if ([IO.Path]::GetDirectoryName($resolved) -eq [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\\') "+
            "-and [IO.Path]::GetFileName($resolved).StartsWith('"+TempPrefix+"')) { Remove-Item -LiteralPath $resolved -Recurse -Force }";
        string encoded=Convert.ToBase64String(Encoding.Unicode.GetBytes(script));
        Process.Start(new ProcessStartInfo("powershell.exe","-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand "+encoded) {
            UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=Path.GetTempPath() });
    }
}
