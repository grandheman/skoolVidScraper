import os


def _register_cuda_dlls():
    """
    On Windows, ctranslate2 loads cuBLAS/cuDNN via LoadLibrary and does not
    search pip's nvidia-*-cu12 packages by default. Add their bin dirs to the
    DLL search path (located dynamically so this works on any machine).
    """
    if os.name != "nt":
        return
    try:
        import nvidia
    except ImportError:
        return
    for root in nvidia.__path__:
        for lib in ("cublas", "cudnn"):
            bin_dir = os.path.join(root, lib, "bin")
            if os.path.isdir(bin_dir):
                os.add_dll_directory(bin_dir)
                # ctranslate2's loader uses the classic search order (reads PATH),
                # so add_dll_directory alone is not enough on Windows.
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]


_register_cuda_dlls()

# faster-whisper decodes audio itself via bundled PyAV, so system ffmpeg is
# not required for transcription (it is still needed by yt-dlp's merge path).
from faster_whisper import WhisperModel

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3", ".wav")


class Transcriber:
    """Loads a faster-whisper model once and returns transcript segments."""

    def __init__(self, model_size: str = "small.en", device: str = "auto",
                 compute_type: str = "auto"):
        # "auto" tries CUDA and falls back to CPU so it runs on any machine.
        if device == "auto":
            try:
                self.model = WhisperModel(model_size, device="cuda",
                                          compute_type="float16")
                self.device = "cuda"
            except Exception:
                self.model = WhisperModel(model_size, device="cpu",
                                          compute_type="int8")
                self.device = "cpu"
        else:
            resolved_compute = compute_type
            if compute_type == "auto":
                resolved_compute = "float16" if device == "cuda" else "int8"
            self.model = WhisperModel(model_size, device=device,
                                      compute_type=resolved_compute)
            self.device = device

    def run_asr(self, media_path: str) -> tuple:
        """Transcribe a file. Returns (segments: list[dict], info: dict)."""
        segment_iter, info = self.model.transcribe(media_path, beam_size=5)
        segments = [
            {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in segment_iter
        ]
        return segments, {"language": info.language, "duration": round(info.duration, 2)}
