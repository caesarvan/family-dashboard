#!/usr/local/bin/python3
"""Fixed Linux test-only wrapper: pace real FFmpeg, never fabricate output."""
import os
import sys

if not sys.platform.startswith('linux') or not sys.argv[1:]:
    raise SystemExit(64)
args = sys.argv[1:]
if args[-1].endswith('/display.mp4'):
    if args.count('-i') != 1:
        raise SystemExit(64)
    index = args.index('-i')
    args[index:index] = ['-re']
os.execv('/usr/bin/ffmpeg', ['/usr/bin/ffmpeg', *args])
