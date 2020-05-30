import os
import signal
import subprocess
import threading
import time


def run_subprocess(*args, timeout=None, **kwargs):
    start_time = time.time()
    proc = subprocess.Popen(*args, **kwargs)

    if timeout is not None:
        def timeout_killer():
            try:
                os.kill(proc.pid, signal.SIGXCPU)
            except Exception:
                pass
        timer = threading.Timer(timeout, timeout_killer)
        timer.start()

    proc.wait()
    end_time = time.time()
    if timeout is not None:
        timer.cancel()

    return proc, end_time - start_time
