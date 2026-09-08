import codecs
import os
import selectors
import signal
import subprocess
import time


def run_process(command, cwd=None, env=None, cancel=None, on_output=None, timeout=300):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("操作已取消")
    completed = False
    process = subprocess.Popen(
        command, cwd=cwd, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, start_new_session=True,
    )
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    output = ""
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("操作已取消")
                if time.monotonic() >= deadline:
                    raise TimeoutError("命令执行超时")
                for key, _ in selector.select(0.1):
                    data = os.read(key.fd, 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        text = decoder.decode(b"", final=True)
                    else:
                        text = decoder.decode(data)
                    output = (output + text)[-1048576:]
                    if on_output and text:
                        on_output(text)
        process.wait()
        if cancel is not None and cancel.is_set():
            raise InterruptedError("操作已取消")
        completed = True
        return subprocess.CompletedProcess(command, process.returncode, output, "")
    finally:
        if not completed:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        process.stdout.close()
