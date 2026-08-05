"""The sanitizer as a program, so it can be run somewhere the API is not.

    python -m image_sanitizer --source <quarantined> --output <clean.png> \
        --max-width 12000 --max-height 12000 --max-pixels 60000000 \
        --max-frames 1 --max-output-bytes 41943040

One JSON object on stdout, always, whether it worked or not. The caller reads a
code rather than an exit status and a traceback, for the reason every other typed
boundary in this service exists: a stack trace is not a verdict about a drawing,
and it is not safe to show anybody.

The limits arrive as arguments rather than being read from a config here, because
this program must not know where the service keeps anything. It reads one file,
writes one file, and that is the whole of its access.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
from pathlib import Path

from .sanitize import SanitizerRejected, sanitize_file


def confine(memory_bytes: int, cpu_seconds: int) -> None:
    """Ceilings the decoder cannot talk its way past.

    Belt and braces with whatever the container gives it, and the braces are worth
    having on their own: a limit the kernel enforces on this process is one that
    holds even when the program is started by hand, by a test, or on a machine
    whose operator forgot the `--memory` flag.

    `RLIMIT_AS` is address space rather than resident size, which is the strict
    reading — an allocation that would exceed it fails at `malloc` instead of after
    the pages are touched, so a bomb dies deterministically rather than when the
    machine happens to run out.
    """
    for what, limit in ((resource.RLIMIT_AS, memory_bytes), (resource.RLIMIT_CPU, cpu_seconds)):
        soft, hard = resource.getrlimit(what)
        ceiling = limit if hard == resource.RLIM_INFINITY else min(limit, hard)
        resource.setrlimit(what, (ceiling, ceiling))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="image_sanitizer")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-width", type=int, required=True)
    parser.add_argument("--max-height", type=int, required=True)
    parser.add_argument("--max-pixels", type=int, required=True)
    parser.add_argument("--max-frames", type=int, default=1)
    parser.add_argument("--max-output-bytes", type=int, required=True)
    parser.add_argument("--memory-bytes", type=int, default=0)
    parser.add_argument("--cpu-seconds", type=int, default=0)
    arguments = parser.parse_args(argv)

    if arguments.memory_bytes and arguments.cpu_seconds:
        confine(arguments.memory_bytes, arguments.cpu_seconds)

    try:
        page = sanitize_file(
            Path(arguments.source),
            arguments.max_width, arguments.max_height, arguments.max_pixels,
            arguments.max_frames, arguments.max_output_bytes,
        )
    except SanitizerRejected as refusal:
        print(json.dumps({"ok": False, "code": refusal.code, "message": refusal.message}))
        return 1
    except MemoryError:
        # What `RLIMIT_AS` produces when a decode asks for more than it may have.
        # A code rather than a crash: the customer's file is the reason, and this is
        # the one refusal that means "this would have taken the machine down".
        print(json.dumps({"ok": False, "code": "INPUT_PIXELS_TOO_MANY",
                          "message": "The image needs more memory than a drawing may use."}))
        return 1
    except Exception as error:  # noqa: BLE001 - a decoder failure is not a stack trace
        print(json.dumps({"ok": False, "code": "INPUT_DECODE_FAILED",
                          "message": "The image could not be read.",
                          "detail": type(error).__name__}))
        return 1

    Path(arguments.output).write_bytes(page.png)
    print(json.dumps({
        "ok": True,
        "width": page.width,
        "height": page.height,
        "source_format": page.source_format,
        "bytes": len(page.png),
    }))
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point itself
    sys.exit(main())
