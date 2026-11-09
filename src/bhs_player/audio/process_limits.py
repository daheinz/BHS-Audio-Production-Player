"""Windows decoder jobs: bound memory and terminate children if the player exits."""
import os


def attach_decoder_job(process):
    if os.name != "nt":
        return None
    import ctypes as c
    from ctypes import wintypes as w
    class Basic(c.Structure):
        _fields_ = [("process_time",c.c_longlong),("job_time",c.c_longlong),
                    ("flags",w.DWORD),("min_working",c.c_size_t),("max_working",c.c_size_t),
                    ("active",w.DWORD),("affinity",c.c_size_t),("priority",w.DWORD),("scheduling",w.DWORD)]
    class IO(c.Structure):
        _fields_ = [(name,c.c_ulonglong) for name in ("read_ops","write_ops","other_ops","read_bytes","write_bytes","other_bytes")]
    class Limits(c.Structure):
        _fields_ = [("basic",Basic),("io",IO),("process_memory",c.c_size_t),
                    ("job_memory",c.c_size_t),("peak_process",c.c_size_t),("peak_job",c.c_size_t)]
    kernel = c.WinDLL("kernel32",use_last_error=True)
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.CreateJobObjectW.argtypes = [c.c_void_p,w.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [w.HANDLE,c.c_int,c.c_void_p,w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE,w.HANDLE]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    job = kernel.CreateJobObjectW(None,None)
    if not job:
        raise OSError(c.get_last_error(),"Cannot create decoder isolation job")
    limits = Limits()
    limits.basic.flags = 0x100 | 0x2000  # process memory, kill on job close
    limits.process_memory = 512*1024*1024
    if not kernel.SetInformationJobObject(job,9,c.byref(limits),c.sizeof(limits)) or not kernel.AssignProcessToJobObject(job,w.HANDLE(int(process._handle))):
        error = c.get_last_error()
        kernel.CloseHandle(job)
        raise OSError(error,"Cannot apply decoder memory/lifetime limits")
    return kernel,job


def close_decoder_job(job):
    if job is not None:
        kernel,handle = job
        kernel.CloseHandle(handle)
