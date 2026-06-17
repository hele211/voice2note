"""Transcribe an audio file to text using whisper.cpp (`whisper-cli`), offline.

whisper-cli only reads flac/mp3/ogg/wav, so we convert the memo to 16 kHz mono WAV
with ffmpeg first. The audio is also copied out of the TCC-protected Voice Memos
folder beforehand: the Python process has Full Disk Access, but ffmpeg/whisper-cli
(separate child binaries) do not inherit it and would get "Operation not permitted".
"""
import shutil
import subprocess
import tempfile
from pathlib import Path


def build_ffmpeg_cmd(src, wav_out, ffmpeg_bin="ffmpeg"):
    return [
        ffmpeg_bin, "-nostdin", "-y", "-loglevel", "error",
        "-i", str(src),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        str(wav_out),
    ]


def build_whisper_cmd(wav_path, model_path, out_prefix, whisper_bin="whisper-cli", language="auto"):
    return [
        whisper_bin,
        "-m", str(model_path),
        "-f", str(wav_path),
        "-l", language,
        "-otxt", "-of", str(out_prefix),
        "-nt", "-np",
    ]


def read_transcript(txt_path):
    path = Path(txt_path)
    if not path.exists():
        raise RuntimeError("whisper-cli produced no transcript file")
    return path.read_text(encoding="utf-8").strip()


def transcribe(audio_path, model_path, whisper_bin="whisper-cli", ffmpeg_bin="ffmpeg",
               language="auto", runner=subprocess.run):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # 1. Copy out of the protected folder (Python has FDA; ffmpeg does not).
        local_audio = tmp / Path(audio_path).name
        shutil.copyfile(audio_path, local_audio)
        # 2. Convert to 16 kHz mono WAV for whisper.cpp.
        wav = tmp / "audio.wav"
        fp = runner(build_ffmpeg_cmd(local_audio, wav, ffmpeg_bin),
                    capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL)
        if fp.returncode != 0:
            raise RuntimeError(f"ffmpeg failed (exit {fp.returncode}): {(fp.stderr or '')[-500:]}")
        # 3. Transcribe.
        out_prefix = tmp / "out"
        wp = runner(build_whisper_cmd(wav, model_path, out_prefix, whisper_bin, language),
                    capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL)
        if wp.returncode != 0:
            raise RuntimeError(f"whisper-cli failed (exit {wp.returncode}): {(wp.stderr or '')[-500:]}")
        return read_transcript(f"{out_prefix}.txt")
