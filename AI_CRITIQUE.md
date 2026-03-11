# AI Code Critique

## Original AI-Generated Code

Below is the original code the AI produced for the SRT video streamer:

```python
import os
import sys
import subprocess
import threading
import time
import signal


log_file = None

def log_print(*args, **kwargs):
    """Print to both console and log file"""
    message = ' '.join(str(arg) for arg in args)
    print(*args, **kwargs)
    if log_file:
        log_file.write(message + '\n')
        log_file.flush()


SRT_HOST = "127.0.0.1"
SRT_PORT = 9000
LATENCY = 120

def build_stream_command(input_file):

    srt_url = f"srt://{SRT_HOST}:{SRT_PORT}?mode=caller&latency={LATENCY}"

    command = f"""ffmpeg -re -stream_loop -1 -i "{input_file}" \
    -c:v libx264 \
    -preset veryfast \
    -tune zerolatency \
    -b:v 2000k \
    -maxrate 2000k \
    -bufsize 4000k \
    -pix_fmt yuv420p \
    -f mpegts "{srt_url}" """

    return command.strip()


def build_fallback_command():

    srt_url = f"srt://{SRT_HOST}:{SRT_PORT}?mode=caller&latency={LATENCY}"
    command = f"""ffmpeg -re \
    -f lavfi -i testsrc=size=1280x720:rate=30 \
    -c:v libx264 \
    -preset veryfast \
    -tune zerolatency \
    -pix_fmt yuv420p \
    -f mpegts "{srt_url}" """
    return command.strip()


def stats_loop(process):

    while True:

        if process.poll() is not None:
            break

        ''' Simulated SRT stats (FFmpeg CLI does not expose easily)'''

        rtt = round(15 + (time.time() % 5), 2)
        loss = round((time.time() % 1) * 0.01, 4)

        log_print(f"[STATS] RTT: {rtt} ms | Packet Loss: {loss}%")

        time.sleep(1)



def run_stream(command):

    log_print("\nStarting FFmpeg pipeline:\n")
    log_print(command)
    log_print("\n--------------------------------\n")

    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    '''
    Start stats monitoring thread
    '''

    stats_thread = threading.Thread(
        target=stats_loop,
        args=(process,),
        daemon=True
    )

    stats_thread.start()

    try:

        for line in process.stderr:

            log_print(line.strip())

            if "error" in line.lower():
                log_print("\n[ERROR] Stream failure detected")
                process.terminate()
                return False

    except KeyboardInterrupt:
        process.terminate()

    return process.wait() == 0


# --------------------------------
# Graceful Shutdown
# --------------------------------

def shutdown(sig, frame):
    log_print("\nShutting down streamer")
    if log_file:
        log_file.close()
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


def main():
    global log_file

    log_file = open('logs.txt', 'w', encoding='utf-8')

    if len(sys.argv) < 2:
        log_print("\nUsage: python streamer.py <video_file>\n")
        sys.exit(1)

    input_file = sys.argv[1]

    if not os.path.exists(input_file):
        log_print(f"\nFile not found: {input_file}\n")
        sys.exit(1)

    log_print("\nStarting primary video stream...\n")

    primary_command = build_stream_command(input_file)

    success = run_stream(primary_command)

    if not success:

        log_print("\nSwitching to fallback stream...\n")

        fallback_command = build_fallback_command()

        run_stream(fallback_command)


if __name__ == "__main__":
    main()
```

---

## What Was Wrong With It

### 1. Incorrect SRT Mode Flag (`mode=caller` instead of `mode=listener`) — **Critical Bug**

The AI set `mode=caller` in the SRT URL for both the primary and fallback FFmpeg commands:

```python
srt_url = f"srt://{SRT_HOST}:{SRT_PORT}?mode=caller&latency={LATENCY}"
```

In SRT, a **caller** tries to connect to an already-running listener on the other end. Since this script *is* the streaming source (the publisher), it needs to be in **listener** mode so that a receiver/player (e.g. `ffplay`, VLC) can connect to it. With `mode=caller`, FFmpeg immediately failed with:

```
[srt @ 0x...] Connection to srt://127.0.0.1:9000?mode=caller&latency=120 failed: Input/output error
```

This caused the primary stream to fail instantly every time, immediately triggering the fallback — which also failed for the same reason.

### 2. No `try/finally` Around the Log File — **Resource Leak**

The original `main()` opened the log file but had no `try/finally` block to guarantee it was closed on exit. If the program crashed or hit an early `sys.exit()` (e.g. missing arguments, file not found), the log file handle would leak without being flushed/closed properly.

```python
def main():
    global log_file
    log_file = open('logs.txt', 'w', encoding='utf-8')
    # ... if sys.exit(1) is called here, log_file is never closed
```

### 3. Potential Double-Close of the Log File

The `shutdown()` signal handler closes `log_file`, and if a `try/finally` also closes it, the file could be closed twice. While Python's `file.close()` is idempotent, the `shutdown()` handler calling `sys.exit(0)` while `main()` is still in a `finally` block can cause unexpected behavior.

### 4. Overly Broad Error Detection

The error-checking logic matches any line from FFmpeg's stderr containing the word "error" (case-insensitive):

```python
if "error" in line.lower():
    log_print("\n[ERROR] Stream failure detected")
    process.terminate()
    return False
```

FFmpeg prints many informational and warning messages to stderr (it uses stderr for *all* its output). Some of these may contain the word "error" in a non-critical context (e.g. codec error-resilience settings, harmless format warnings). This overly broad check can terminate the stream prematurely on benign output.

### 5. Simulated (Fake) SRT Statistics

The `stats_loop()` function generates fake RTT and packet loss values using arithmetic on `time.time()`:

```python
rtt = round(15 + (time.time() % 5), 2)
loss = round((time.time() % 1) * 0.01, 4)
```

These numbers look plausible but are completely fabricated — they don't reflect actual SRT connection quality. While the inline comment acknowledges this ("Simulated SRT stats"), the printed output `[STATS] RTT: ...` gives no indication to the user that these are simulated, which is misleading.

### 6. Use of `shell=True` With User Input

The FFmpeg command is run with `shell=True` and the input file path is interpolated directly into the command string:

```python
process = subprocess.Popen(command, shell=True, ...)
```

If the input file path contains shell metacharacters (e.g. `; rm -rf /` or backticks), this could lead to command injection. Using `shell=True` with untrusted/user-supplied input is a well-known security anti-pattern.

### 7. No `process.wait()` After `process.terminate()` in Error Path

When an error is detected, the code calls `process.terminate()` and immediately returns `False` without waiting for the process to actually exit:

```python
if "error" in line.lower():
    log_print("\n[ERROR] Stream failure detected")
    process.terminate()
    return False  # no process.wait() — zombie process risk
```

This can leave the FFmpeg process in a zombie state, and the port may remain bound, causing the fallback stream to also fail to bind to the same SRT port.

---

## How It Was Fixed / Improved

### Fix 1: Changed SRT Mode to `listener` — **Primary Fix**

Updated both `build_stream_command()` and `build_fallback_command()` to use `mode=listener`:

```python
srt_url = f"srt://{SRT_HOST}:{SRT_PORT}?mode=listener&latency={LATENCY}"
```

This allows the streamer to bind to port 9000 and wait for incoming SRT connections, which is the correct behavior for a streaming source. After this fix, the primary stream started encoding and transmitting frames successfully.

### Fix 2: Added `try/finally` for Log File Cleanup

Wrapped the body of `main()` in a `try/finally` block to ensure the log file is always closed, even on unexpected exits:

```python
def main():
    global log_file
    log_file = open('logs.txt', 'w', encoding='utf-8')
    try:
        # ... main logic ...
    finally:
        if log_file:
            log_file.close()
```

### Fix 3: Cleaned Up FFmpeg Command Formatting

Reformatted the FFmpeg command from multiline backslash-continuation style to a single-line command inside a triple-quoted string. This avoids issues with trailing whitespace after backslashes (which would silently break the line continuation in Python) and makes the actual command that gets executed easier to inspect in logs:

```python
command = f"""
ffmpeg -re -stream_loop -1 -i "{input_file}" -c:v libx264 -preset veryfast -tune zerolatency -b:v 2000k -maxrate 2000k -bufsize 4000k -pix_fmt yuv420p -f mpegts "{srt_url}"
"""
```

---

## Summary

| Issue | Severity | Status |
|-------|----------|--------|
| Wrong SRT mode (`caller` → `listener`) | **Critical** | ✅ Fixed |
| Log file resource leak (no `try/finally`) | Medium | ✅ Fixed |
| FFmpeg command formatting (backslash continuations) | Low | ✅ Fixed |
| Potential double-close of log file | Low | ⚠️ Noted |
| Overly broad error string matching | Medium | ⚠️ Noted |
| Fake/simulated SRT statistics | Low | ⚠️ Noted |
| `shell=True` with user input | Medium | ⚠️ Noted |
| No `process.wait()` after terminate | Medium | ⚠️ Noted |

The critical fix — changing `mode=caller` to `mode=listener` — was the difference between the streamer failing instantly and successfully encoding/transmitting video over SRT.
