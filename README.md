# Peel

Extract the audio track from any video and save it as **MP3** or **WAV**.
Two versions: a browser app (GitHub Pages) and a Python CLI.

*RU: Достаёт аудиодорожку из видео и сохраняет в MP3 или WAV. Две версии — в браузере и в командной строке.*

## Browser

Open `index.html`, or enable **Settings → Pages → Deploy from branch → main / root**
and use `https://<user>.github.io/<repo>/`.

- Drag a video in, pick MP3 (128–320 kbps) or WAV (16/24 bit), 44.1/48 kHz, stereo/mono
- Trim: drag the two handles on the waveform to keep only the part you need
- Loudness: peak −1 dB, or −14 LUFS (streaming) / −16 LUFS (podcasts), measured per ITU-R BS.1770
- Fades: smooth fade in and out (0.5 / 1 / 3 s) to avoid clicks at the cut
- Runs fully locally — nothing is uploaded
- Reads what the browser can decode (MP4/AAC, MOV, WEBM; MKV in Chromium). For anything else, use the CLI

## CLI

Needs Python 3.8+ and [ffmpeg](https://ffmpeg.org/download.html)
(or `pip install imageio-ffmpeg` as a bundled fallback).

```bash
python peel.py clip.mp4                      # MP3 320 kbps
python peel.py clip.mp4 -f wav --bits 24     # WAV 24 bit
python peel.py ./videos -r -o ./audio        # whole folder, recursive
python peel.py a.mov --rate 48000 --mono
python peel.py clip.mp4 --start 0:12 --end 0:45 --fade 1
python peel.py clip.mp4 --normalize stream   # -14 LUFS
```

| Option | |
|---|---|
| `-f mp3\|wav` | output format |
| `-b 128\|192\|256\|320` | MP3 bitrate |
| `--bits 16\|24\|32` | WAV bit depth (32 = float) |
| `--rate 44100\|48000` | sample rate (default: original) |
| `--mono` | mix to mono |
| `--start` / `--end` | trim, e.g. `12`, `0:12`, `1:02:03.5` |
| `--normalize peak\|stream\|podcast` | −1 dB peak / −14 LUFS / −16 LUFS |
| `--fade SEC` | fade in and out |
| `-t N` | audio track index |
| `-o DIR` | output folder |
| `-r` | include subfolders |
| `--overwrite` | replace existing files |

## License

MIT © BeyondiDentity
