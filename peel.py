#!/usr/bin/env python3
"""
Peel — extract the audio track from video files into MP3 or WAV,
with optional trim, loudness normalization and fades.

Examples:
  python peel.py clip.mp4
  python peel.py clip.mp4 -f wav --bits 24
  python peel.py clip.mp4 --start 0:12 --end 0:45 --fade 1
  python peel.py clip.mp4 --normalize stream        # -14 LUFS
  python peel.py ./videos -r -o ./audio --normalize peak
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXT = {
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".flv",
    ".wmv", ".mpg", ".mpeg", ".ts", ".mts", ".3gp", ".ogv",
}
WAV_CODEC = {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_f32le"}
LUFS = {"stream": -14, "podcast": -16}
PEAK_DB = -1.0


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # optional fallback: pip install imageio-ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def parse_time(s):
    """'90', '1:30', '1:02:03.5' -> seconds"""
    try:
        parts = [float(p) for p in s.split(":")]
    except ValueError:
        raise argparse.ArgumentTypeError(f"bad time: {s}")
    if not 1 <= len(parts) <= 3 or any(p < 0 for p in parts):
        raise argparse.ArgumentTypeError(f"bad time: {s}")
    t = 0.0
    for p in parts:
        t = t * 60 + p
    return t


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True,
                          errors="replace")


def probe(ff, src, track):
    """duration (s) and sample rate of the chosen audio track"""
    err = run([ff, "-hide_banner", "-i", str(src)]).stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err)
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None
    rates = re.findall(r"Audio:.*?(\d+) Hz", err)
    rate = int(rates[track]) if len(rates) > track else None
    return dur, rate, len(rates)


def collect(inputs, recursive):
    files = []
    for raw in inputs:
        p = Path(raw).expanduser()
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            files += sorted(f for f in it
                            if f.is_file() and f.suffix.lower() in VIDEO_EXT)
        elif p.is_file():
            files.append(p)
        else:
            print(f"  ! not found: {raw}", file=sys.stderr)
    return files


def input_args(ff, src, a, length):
    cmd = [ff, "-hide_banner", "-nostats"]
    if a.start:
        cmd += ["-ss", f"{a.start:.3f}"]
    cmd += ["-i", str(src)]
    if a.end is not None:
        cmd += ["-t", f"{length:.3f}"]
    return cmd + ["-vn", "-map", f"0:a:{a.track}"]


def norm_filter(ff, src, a, length, pre):
    """two-pass: measure, then return the correcting filter"""
    if a.normalize == "peak":
        err = run(input_args(ff, src, a, length)
                  + ["-af", ",".join(pre + ["volumedetect"]),
                     "-f", "null", "-"]).stderr
        m = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", err)
        if not m or m[1] == "-inf":
            return None, "silent, not normalized"
        gain = PEAK_DB - float(m[1])
        return f"volume={gain:.2f}dB", f"peak {PEAK_DB:g} dB"

    target = LUFS[a.normalize]
    base = f"loudnorm=I={target}:TP={PEAK_DB:g}:LRA=11"
    err = run(input_args(ff, src, a, length)
              + ["-af", ",".join(pre + [base + ":print_format=json"]),
                 "-f", "null", "-"]).stderr
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
    if not m:
        return None, "loudness not measured"
    d = json.loads(m[0])
    if "inf" in d["input_i"]:
        return None, "silent, not normalized"
    f = (f"{base}:measured_I={d['input_i']}:measured_TP={d['input_tp']}"
         f":measured_LRA={d['input_lra']}"
         f":measured_thresh={d['input_thresh']}"
         f":offset={d['target_offset']}:linear=true")
    return f, f"{target} LUFS (was {float(d['input_i']):.1f})"


def process(ff, src, dst, a):
    dur, src_rate, n_tracks = probe(ff, src, a.track)
    if n_tracks == 0:
        return False, "no audio track"
    if n_tracks <= a.track:
        return False, f"no audio track #{a.track} (has {n_tracks})"
    start = a.start or 0.0
    if dur is not None and start >= dur:
        return False, "start is past the end"
    end = a.end if a.end is not None else dur
    if dur is not None and end is not None:
        end = min(end, dur)
    length = end - start if end is not None else None

    pre = ["aformat=channel_layouts=mono"] if a.mono else []
    chain, notes = list(pre), []
    if a.normalize:
        f, note = norm_filter(ff, src, a, length, pre)
        notes.append(note)
        if f:
            chain.append(f)
    if a.fade:
        if length:
            fd = min(a.fade, length / 2)
            chain += [f"afade=t=in:st=0:d={fd:.3f}",
                      f"afade=t=out:st={length - fd:.3f}:d={fd:.3f}"]
        else:
            notes.append("length unknown, fades skipped")

    cmd = input_args(ff, src, a, length) + ["-loglevel", "error", "-y"]
    if chain:
        cmd += ["-af", ",".join(chain)]
    if a.format == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{a.bitrate}k"]
    else:
        cmd += ["-c:a", WAV_CODEC[a.bits]]
    rate = a.rate or (src_rate if a.normalize else None)
    if rate:  # loudnorm upsamples internally, so pin the rate
        cmd += ["-ar", str(rate)]
    cmd.append(str(dst))

    r = run(cmd)
    if r.returncode == 0 and dst.exists():
        return True, " · ".join(notes)
    lines = r.stderr.strip().splitlines()
    return False, lines[-1] if lines else "unknown error"


def human(n):
    return f"{n / 1048576:.1f} MB" if n > 1048576 else f"{n // 1024} KB"


def main():
    ap = argparse.ArgumentParser(
        prog="peel",
        description="Extract audio from video into MP3 or WAV.")
    ap.add_argument("inputs", nargs="+",
                    help="video files and/or folders")
    ap.add_argument("-f", "--format", choices=["mp3", "wav"],
                    default="mp3", help="output format (default: mp3)")
    ap.add_argument("-b", "--bitrate", type=int, default=320,
                    choices=[128, 192, 256, 320],
                    help="MP3 bitrate in kbps (default: 320)")
    ap.add_argument("--bits", type=int, default=16, choices=[16, 24, 32],
                    help="WAV bit depth; 32 = float (default: 16)")
    ap.add_argument("--rate", type=int, choices=[44100, 48000],
                    help="sample rate (default: keep original)")
    ap.add_argument("--mono", action="store_true",
                    help="mix down to mono")
    ap.add_argument("--start", type=parse_time,
                    help="trim start, e.g. 12 or 0:12 or 1:02:03.5")
    ap.add_argument("--end", type=parse_time,
                    help="trim end, same format")
    ap.add_argument("--normalize", choices=["peak", "stream", "podcast"],
                    help="peak = -1 dB peak, stream = -14 LUFS, "
                         "podcast = -16 LUFS")
    ap.add_argument("--fade", type=float, default=0,
                    help="fade in and out, seconds")
    ap.add_argument("-t", "--track", type=int, default=0,
                    help="audio track index if the video has several")
    ap.add_argument("-o", "--out", type=Path,
                    help="output folder (default: next to each video)")
    ap.add_argument("-r", "--recursive", action="store_true",
                    help="search subfolders")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace existing output files")
    a = ap.parse_args()

    if a.end is not None and a.end <= (a.start or 0):
        ap.error("--end must be after --start")
    if a.fade < 0:
        ap.error("--fade must be positive")

    ff = find_ffmpeg()
    if not ff:
        sys.exit("ffmpeg not found. Install it (brew/apt/winget install "
                 "ffmpeg) or run: pip install imageio-ffmpeg")

    files = collect(a.inputs, a.recursive)
    if not files:
        sys.exit("No video files found.")
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)

    trimmed = a.start is not None or a.end is not None
    ok = skipped = failed = 0
    for i, src in enumerate(files, 1):
        folder = a.out or src.parent
        name = src.stem + ("_cut" if trimmed else "")
        dst = folder / f"{name}.{a.format}"
        tag = f"[{i}/{len(files)}]"
        if dst.exists() and not a.overwrite:
            print(f"{tag} skip  {dst.name} (exists, use --overwrite)")
            skipped += 1
            continue
        print(f"{tag} {src.name} -> {dst.name}", end=" ", flush=True)
        success, note = process(ff, src, dst, a)
        if success:
            extra = f" · {note}" if note else ""
            print(f"✓ {human(dst.stat().st_size)}{extra}")
            ok += 1
        else:
            print(f"✗ {note}")
            failed += 1
            if dst.exists():
                dst.unlink()

    print(f"\nDone: {ok} ok, {skipped} skipped, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
