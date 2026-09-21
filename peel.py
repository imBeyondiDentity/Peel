#!/usr/bin/env python3
"""
Peel — extract the audio track from video files into MP3 or WAV.

Examples:
  python peel.py clip.mp4
  python peel.py clip.mp4 -f wav --bits 24
  python peel.py ./videos -r -f mp3 -b 320 -o ./audio
  python peel.py a.mov b.mkv --rate 48000 --mono
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXT = {
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".flv",
    ".wmv", ".mpg", ".mpeg", ".ts", ".mts", ".3gp", ".ogv",
}
WAV_CODEC = {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_f32le"}


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # optional fallback: pip install imageio-ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


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


def build_cmd(ff, src, dst, a):
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(src), "-vn", "-map", f"0:a:{a.track}"]
    if a.format == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{a.bitrate}k"]
    else:
        cmd += ["-c:a", WAV_CODEC[a.bits]]
    if a.rate:
        cmd += ["-ar", str(a.rate)]
    if a.mono:
        cmd += ["-ac", "1"]
    cmd.append(str(dst))
    return cmd


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
    ap.add_argument("-t", "--track", type=int, default=0,
                    help="audio track index if the video has several")
    ap.add_argument("-o", "--out", type=Path,
                    help="output folder (default: next to each video)")
    ap.add_argument("-r", "--recursive", action="store_true",
                    help="search subfolders")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace existing output files")
    a = ap.parse_args()

    ff = find_ffmpeg()
    if not ff:
        sys.exit("ffmpeg not found. Install it (brew/apt/winget install "
                 "ffmpeg) or run: pip install imageio-ffmpeg")

    files = collect(a.inputs, a.recursive)
    if not files:
        sys.exit("No video files found.")
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)

    ok = skipped = failed = 0
    for i, src in enumerate(files, 1):
        folder = a.out or src.parent
        dst = folder / f"{src.stem}.{a.format}"
        tag = f"[{i}/{len(files)}]"
        if dst.exists() and not a.overwrite:
            print(f"{tag} skip  {dst.name} (exists, use --overwrite)")
            skipped += 1
            continue
        print(f"{tag} {src.name} -> {dst.name}", end=" ", flush=True)
        r = subprocess.run(build_cmd(ff, src, dst, a),
                           capture_output=True, text=True)
        if r.returncode == 0 and dst.exists():
            print(f"✓ {human(dst.stat().st_size)}")
            ok += 1
        else:
            err = r.stderr.strip().splitlines()
            msg = err[-1] if err else "unknown error"
            if "matches no streams" in r.stderr:
                msg = "no audio track"
            print(f"✗ {msg}")
            failed += 1
            if dst.exists():
                dst.unlink()

    print(f"\nDone: {ok} ok, {skipped} skipped, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
