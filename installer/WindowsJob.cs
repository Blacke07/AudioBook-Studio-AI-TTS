// Own only the launcher's child processes, including Ollama and the TTS engine.
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

sealed class WindowsJob : IDisposable {
    SafeFileHandle handle;
    [StructLayout(LayoutKind.Sequential)] struct Basic {
        public long ProcessTime,JobTime;
        public uint Flags;
        public UIntPtr Minimum,Maximum;
        public uint Active;
        public UIntPtr Affinity;
        public uint Priority,Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct Counters {
        public ulong ReadOperations,WriteOperations,OtherOperations,ReadBytes,WriteBytes,OtherBytes;
    }
    [StructLayout(LayoutKind.Sequential)] struct Limits {
        public Basic Basic;
        public Counters IO;
        public UIntPtr ProcessMemory,JobMemory,PeakProcessMemory,PeakJobMemory;
    }
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern SafeFileHandle CreateJobObject(IntPtr attributes,string name);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern bool SetInformationJobObject(SafeFileHandle job,int kind,ref Limits limits,uint size);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern bool AssignProcessToJobObject(SafeFileHandle job,IntPtr process);
    public WindowsJob() {
        handle=CreateJobObject(IntPtr.Zero,null);
        if(handle.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
        var limits=new Limits(); limits.Basic.Flags=0x2000; // KILL_ON_JOB_CLOSE
        if(!SetInformationJobObject(handle,9,ref limits,(uint)Marshal.SizeOf(typeof(Limits)))) {
            int error=Marshal.GetLastWin32Error(); handle.Dispose(); throw new Win32Exception(error);
        }
    }
    public void Attach(Process process) {
        if(!AssignProcessToJobObject(handle,process.Handle)) throw new Win32Exception(Marshal.GetLastWin32Error());
    }
    public void Dispose() { handle.Dispose(); }
}
