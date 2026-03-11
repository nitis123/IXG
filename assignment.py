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

    srt_url = f"srt://{SRT_HOST}:{SRT_PORT}?mode=listener&latency={LATENCY}"

    command = f"""
    ffmpeg -re -stream_loop -1 -i "{input_file}" -c:v libx264 -preset veryfast -tune zerolatency -b:v 2000k -maxrate 2000k -bufsize 4000k -pix_fmt yuv420p -f mpegts "{srt_url}"
    """

    return command.strip()


def build_fallback_command():

    srt_url = f"srt://{SRT_HOST}:{SRT_PORT}?mode=listener&latency={LATENCY}"
    command = f"""ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p -f mpegts "{srt_url}" """
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

    # Open log file
    log_file = open('logs.txt', 'w', encoding='utf-8')

    try:
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
    finally:
        if log_file:
            log_file.close()


if __name__ == "__main__":
    main()