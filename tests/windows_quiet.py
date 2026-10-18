"""Verify console suppression, exit codes, and child cleanup on Windows."""
import argparse
import ctypes
import os
from pathlib import Path
import subprocess
import time

from heartdevspace.core import Manager, hidden_run, NO_WINDOW


FIXTURE = r'''
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
class Fixture {
    [DllImport("kernel32.dll")] static extern IntPtr GetConsoleWindow();
    static int Main(string[] args) {
        Console.WriteLine("console=" + GetConsoleWindow().ToInt64());
        Console.WriteLine("pid=" + Process.GetCurrentProcess().Id);
        if (args[0] == "exit") return 73;
        if (args[0] == "child") File.WriteAllText(args[1], "console=" + GetConsoleWindow().ToInt64());
        if (args[0] == "parent") {
            var child = Process.Start(new ProcessStartInfo(
                Process.GetCurrentProcess().MainModule.FileName, "child \"" + args[1] + "\"") {
                UseShellExecute=false, CreateNoWindow=true
            });
            Console.WriteLine("child=" + child.Id);
        }
        Thread.Sleep(120000);
        return 0;
    }
}
'''


def check(home):
    if os.name != 'nt' or home.exists():
        raise ValueError('Run on Windows with a new disposable directory.')
    manager = Manager(home)
    source, fixture = home / 'fixture.cs', home / 'fixture.exe'
    source.write_text(FIXTURE, encoding='utf-8')
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    hidden_run([str(compiler), '/nologo', '/out:' + str(fixture), str(source)])
    out, err = home / 'out.log', home / 'err.log'
    base = [manager.settings['quiet_launcher'], str(fixture)]
    tail = [str(home), str(out), str(err), 'job']
    result = subprocess.run(base + ['exit'] + tail, creationflags=NO_WINDOW, timeout=10)
    assert result.returncode == 73, result.returncode
    assert 'console=0' in out.read_text()
    out.unlink()
    child_report = home / 'child.txt'
    process = subprocess.Popen(base + [subprocess.list2cmdline(['parent', str(child_report)])] + tail, creationflags=NO_WINDOW)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handles = []
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            lines = out.read_text().splitlines() if out.exists() else []
            if child_report.exists() and child_report.read_text() == 'console=0' and any(s.startswith('child=') for s in lines):
                break
            time.sleep(.1)
        assert [s for s in lines if s.startswith('console=')] == ['console=0'], lines
        assert child_report.read_text() == 'console=0'
        parent = int(next(s for s in lines if s.startswith('pid=')).split('=')[1])
        child = int(next(s for s in lines if s.startswith('child=')).split('=')[1])
        for pid in (parent, child):
            handle = kernel.OpenProcess(0x100001, False, pid)
            assert handle, ctypes.get_last_error()
            handles.append(handle)
        assert kernel.TerminateProcess(handles[0], 74)
        assert process.wait(timeout=10) == 74
        assert kernel.WaitForSingleObject(handles[1], 5000) == 0, 'Child survived the managed service'
        print('PASS: parent and child have no console; exit codes preserved; job cleans up child')
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        for handle in handles:
            if kernel.WaitForSingleObject(handle, 1000) != 0:
                kernel.TerminateProcess(handle, 1)
            kernel.CloseHandle(handle)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, required=True)
    check(parser.parse_args().home.resolve())
