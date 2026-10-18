// Windowless process host. The managed service and its children share a job.
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

class QuietLauncher {
    [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
        public long PerProcess, PerJob; public uint Flags;
        public UIntPtr Minimum, Maximum; public uint Active;
        public UIntPtr Affinity; public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct IoCounters {
        public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
    }
    [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
        public BasicLimits Basic; public IoCounters Io;
        public UIntPtr ProcessMemory, JobMemory, PeakProcess, PeakJob;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr attrs, string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr job, int type, ref ExtendedLimits data, uint length);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);

    static int Main(string[] args) {
        if (args.Length != 6) return 64;
        IntPtr job = IntPtr.Zero;
        try {
            using (var output = new StreamWriter(args[3], true))
            using (var error = new StreamWriter(args[4], true)) {
                output.AutoFlush = error.AutoFlush = true;
                var info = new ProcessStartInfo(args[0], args[1]) {
                    WorkingDirectory = args[2], UseShellExecute = false, CreateNoWindow = true,
                    RedirectStandardOutput = true, RedirectStandardError = true,
                    RedirectStandardInput = true
                };
                using (var child = new Process { StartInfo = info }) {
                    child.OutputDataReceived += (sender, e) => { if (e.Data != null) { lock(output) output.WriteLine(e.Data); } };
                    child.ErrorDataReceived += (sender, e) => { if (e.Data != null) { lock(error) error.WriteLine(e.Data); } };
                    if (args[5] == "job") {
                        job = CreateJobObject(IntPtr.Zero, null);
                        var limits = new ExtendedLimits();
                        limits.Basic.Flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                        if (job == IntPtr.Zero || !SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(limits)))
                            throw new System.ComponentModel.Win32Exception();
                    }
                    child.Start();
                    if (job != IntPtr.Zero && !AssignProcessToJobObject(job, child.Handle)) {
                        if (!child.HasExited) child.Kill();
                        throw new System.ComponentModel.Win32Exception();
                    }
                    child.StandardInput.Close();
                    child.BeginOutputReadLine(); child.BeginErrorReadLine();
                    child.WaitForExit(Int32.MaxValue);
                    if (job != IntPtr.Zero) {
                        CloseHandle(job); job = IntPtr.Zero;
                        child.WaitForExit();
                    } else {
                        // A heartbeat may leave long-lived services running.
                        child.CancelOutputRead(); child.CancelErrorRead();
                    }
                    return child.ExitCode;
                }
            }
        } catch (Exception ex) {
            try { File.AppendAllText(args[4], DateTime.UtcNow.ToString("o") + " " + ex.Message + Environment.NewLine); } catch { }
            return 1;
        } finally { if (job != IntPtr.Zero) CloseHandle(job); }
    }
}
