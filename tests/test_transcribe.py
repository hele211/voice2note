import tempfile, unittest
from types import SimpleNamespace
from pathlib import Path
from voice2note import transcribe


class TestTranscribe(unittest.TestCase):
    def test_build_ffmpeg_cmd(self):
        cmd = transcribe.build_ffmpeg_cmd("/x/a.m4a", "/tmp/a.wav", "ffmpeg")
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("/x/a.m4a", cmd)
        self.assertIn("/tmp/a.wav", cmd)
        self.assertIn("16000", cmd)
        self.assertIn("pcm_s16le", cmd)

    def test_build_whisper_cmd(self):
        cmd = transcribe.build_whisper_cmd("/tmp/a.wav", "/m/ggml-small.bin", "/tmp/out",
                                           "whisper-cli", "auto")
        self.assertEqual(cmd[0], "whisper-cli")
        self.assertIn("-m", cmd)
        self.assertIn("/m/ggml-small.bin", cmd)
        self.assertIn("-f", cmd)
        self.assertIn("/tmp/a.wav", cmd)
        self.assertIn("-otxt", cmd)
        self.assertIn("-of", cmd)
        self.assertIn("/tmp/out", cmd)
        self.assertIn("auto", cmd)

    def test_read_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "out.txt"
            p.write_text("  hello there \n", encoding="utf-8")
            self.assertEqual(transcribe.read_transcript(p), "hello there")

    def test_read_transcript_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                transcribe.read_transcript(Path(tmp) / "nope.txt")

    def test_transcribe_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "memo.m4a"
            audio.write_bytes(b"fake-audio-bytes")

            def fake_runner(cmd, capture_output=True, text=True, stdin=None, **kw):
                if cmd[0].endswith("ffmpeg"):
                    Path(cmd[-1]).write_bytes(b"RIFFfakewav")        # ffmpeg writes wav
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                of = cmd[cmd.index("-of") + 1]                       # whisper writes <of>.txt
                Path(of + ".txt").write_text("hello world", encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            out = transcribe.transcribe(audio, "/m/ggml-small.bin",
                                        whisper_bin="whisper-cli", ffmpeg_bin="ffmpeg",
                                        runner=fake_runner)
            self.assertEqual(out, "hello world")


if __name__ == "__main__":
    unittest.main()
