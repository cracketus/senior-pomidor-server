#!/usr/bin/env python3
import argparse
import os
import signal
import subprocess  # nosec B404
import sys
import tempfile
import time
from pathlib import Path


class StepTimeoutError(RuntimeError):
    pass


def timeout_handler(signum, frame):
    raise StepTimeoutError("step timed out")


def run_command(args, timeout=8):
    print(f"\n$ {' '.join(args)}", flush=True)
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)  # nosec B603
    except Exception as exc:
        print(f"command failed to run: {type(exc).__name__}: {exc}", flush=True)
        return
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.stderr:
        print(result.stderr.rstrip(), flush=True)
    print(f"exit_code={result.returncode}", flush=True)


def print_device_info():
    print("== Environment ==", flush=True)
    print(f"python={sys.executable} {sys.version.split()[0]}", flush=True)
    print(f"user={os.getuid()} groups={os.getgroups()}", flush=True)
    for path in ["/dev/media0", "/dev/video0", "/dev/v4l-subdev0"]:
        p = Path(path)
        if p.exists():
            st = p.stat()
            print(f"{path}: mode={oct(st.st_mode & 0o777)} uid={st.st_uid} gid={st.st_gid}", flush=True)
        else:
            print(f"{path}: missing", flush=True)
    run_command(["rpicam-hello", "--list-cameras"], timeout=8)


def test_picamera2(output_path: Path, timeout_seconds: int) -> bool:
    print("\n== Picamera2 Capture ==", flush=True)
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)
    try:
        from picamera2 import Picamera2

        infos = Picamera2.global_camera_info()
        print(f"global_camera_info={infos}", flush=True)
        if not infos:
            print("FAIL: Picamera2 sees no cameras", flush=True)
            return False

        picam2 = Picamera2()
        config = picam2.create_still_configuration(main={"size": (640, 480)})
        print(f"config={config}", flush=True)
        picam2.configure(config)
        picam2.start()
        time.sleep(1.0)
        picam2.capture_file(str(output_path))
        picam2.stop()

        if output_path.exists() and output_path.stat().st_size > 0:
            print(f"PASS: wrote {output_path} ({output_path.stat().st_size} bytes)", flush=True)
            return True
        print(f"FAIL: output file missing or empty: {output_path}", flush=True)
        return False
    except StepTimeoutError as exc:
        print(f"FAIL: {exc}", flush=True)
        return False
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", flush=True)
        return False
    finally:
        signal.alarm(0)


def test_opencv(timeout_seconds: int) -> bool:
    print("\n== OpenCV V4L2 Probe ==", flush=True)
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)
    try:
        import cv2

        cap = cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)
        print(f"is_opened={cap.isOpened()}", flush=True)
        if not cap.isOpened():
            return False
        ok, frame = cap.read()
        cap.release()
        print(f"read_ok={ok}", flush=True)
        if ok and frame is not None:
            print(f"frame_shape={frame.shape}", flush=True)
            return True
        return False
    except StepTimeoutError as exc:
        print(f"FAIL: {exc}", flush=True)
        return False
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", flush=True)
        return False
    finally:
        signal.alarm(0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(Path(tempfile.gettempdir()) / "picamera2-smoke-test.jpg"))
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.unlink(missing_ok=True)

    print_device_info()
    picamera_ok = test_picamera2(output_path, args.timeout)
    opencv_ok = test_opencv(6)

    print("\n== Summary ==", flush=True)
    print(f"picamera2_capture={picamera_ok}", flush=True)
    print(f"opencv_v4l2_probe={opencv_ok}", flush=True)
    if picamera_ok:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
