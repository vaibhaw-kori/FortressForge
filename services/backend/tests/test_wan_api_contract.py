"""Wan I2V API contract tests — no GPU, no 14B download.

Verifies our wrapper passes EXACTLY the kwargs accepted by the installed
WanImageToVideoPipeline.__call__, using inspect + a fake pipeline.
Catches regressions like `image=` on the T2V class or `fps=`/`callback=`.
"""

from __future__ import annotations

import inspect

import pytest


def _needs_diffusers():
    return pytest.importorskip("diffusers")


def _i2v_params() -> set[str]:
    _needs_diffusers()
    from diffusers import WanImageToVideoPipeline

    return set(inspect.signature(WanImageToVideoPipeline.__call__).parameters)


def _ctx():
    from aura_backend.inference.wan_config import WanGenerationConfig, WanModelConfig
    from aura_backend.inference.wan_pipeline import PipelineContext

    return PipelineContext(
        job_id="job-1",
        session_id="sess-1",
        experience_id="aurora",
        capture_ref="local:/tmp/x.jpg",
        config=WanGenerationConfig(
            prompt="a cinematic test prompt",
            negative_prompt="bad",
            width=480,
            height=832,
            num_frames=48,
        ),
        model_config=WanModelConfig(),
    )


class TestInferenceKwargsContract:
    def test_all_kwargs_accepted_by_installed_api(self):
        params = _i2v_params()
        from aura_backend.inference.wan_pipeline import build_inference_kwargs

        ctx = _ctx()
        # capture_image must be set (preprocessing output); use a tiny PIL image.
        PILImage = pytest.importorskip("PIL.Image")
        ctx.capture_image = PILImage.new("RGB", (8, 8))
        kwargs = build_inference_kwargs(ctx)
        unknown = set(kwargs) - params
        assert not unknown, f"kwargs rejected by installed API: {unknown}"

    def test_forbidden_legacy_kwargs_absent(self):
        from aura_backend.inference.wan_pipeline import build_inference_kwargs

        PILImage = pytest.importorskip("PIL.Image")
        ctx = _ctx()
        ctx.capture_image = PILImage.new("RGB", (8, 8))
        kwargs = build_inference_kwargs(ctx)
        for bad in ("fps", "callback", "callback_steps", "seed", "image_embeds", "latents"):
            assert bad not in kwargs, f"legacy kwarg {bad} must not be passed"

    def test_output_type_is_pil(self):
        from aura_backend.inference.wan_pipeline import build_inference_kwargs

        PILImage = pytest.importorskip("PIL.Image")
        ctx = _ctx()
        ctx.capture_image = PILImage.new("RGB", (8, 8))
        assert build_inference_kwargs(ctx)["output_type"] == "pil"

    def test_image_is_first_positional_capable(self):
        # I2V requires image; our kwargs must include a PIL image.
        from aura_backend.inference.wan_pipeline import build_inference_kwargs

        PILImage = pytest.importorskip("PIL.Image")
        ctx = _ctx()
        img = PILImage.new("RGB", (8, 8))
        ctx.capture_image = img
        assert build_inference_kwargs(ctx)["image"] is img


class TestInferenceStageWithFakePipeline:
    def test_stage_calls_fake_with_contract_kwargs(self):
        from aura_backend.inference.wan_pipeline import InferenceStage

        PILImage = pytest.importorskip("PIL.Image")
        ctx = _ctx()
        ctx.capture_image = PILImage.new("RGB", (8, 8))

        seen: dict = {}

        class _Out:
            frames = [[PILImage.new("RGB", (4, 4)) for _ in range(3)]]

        class _FakePipeline:
            def __call__(self, **kwargs):
                seen.update(kwargs)
                return _Out()

        ctx.pipeline = _FakePipeline()
        out = InferenceStage()(ctx)
        assert "image" in seen  # would have raised TypeError on T2V class
        assert seen["output_type"] == "pil"
        # Default 4s@12fps snaps 48 -> 49 on the VAE temporal lattice.
        assert seen["num_frames"] == 49
        assert out.video_frames is not None and len(out.video_frames) == 3
        assert out.metadata.get("inference_complete") is True


class TestPipelinePlacement:
    def test_model_offload_skips_blind_to_device(self):
        from aura_backend.inference.wan_loader import place_pipeline_on_device

        calls: list = []

        class _FakePipe:
            def to(self, device):
                calls.append(("to", device))
                return self

            def enable_model_cpu_offload(self):
                calls.append(("model_offload",))

            def enable_sequential_cpu_offload(self):
                calls.append(("seq_offload",))

        place_pipeline_on_device(_FakePipe(), enable_offload=True, offload_to_cpu=False, device="cuda")
        assert calls == [("model_offload",)]

    def test_plain_move_then_optional_sequential(self):
        from aura_backend.inference.wan_loader import place_pipeline_on_device

        calls: list = []

        class _FakePipe:
            def to(self, device):
                calls.append(("to", device))
                return self

            def enable_model_cpu_offload(self):
                calls.append(("model_offload",))

            def enable_sequential_cpu_offload(self):
                calls.append(("seq_offload",))

        place_pipeline_on_device(_FakePipe(), enable_offload=False, offload_to_cpu=True, device="cuda")
        assert calls == [("to", "cuda"), ("seq_offload",)]


class TestOffloadFolder:
    def test_empty_string_falls_back_to_volume(self, tmp_path, monkeypatch):
        from aura_backend.inference.wan_loader import resolve_offload_folder

        monkeypatch.setenv("AURA_WAN_OFFLOAD_FOLDER", "")
        # Empty must resolve to the explicit preferred path, never system /tmp.
        out = resolve_offload_folder(str(tmp_path / "off"))
        assert out == str(tmp_path / "off")

    def test_uncreatable_path_uses_temp(self, tmp_path):
        import tempfile

        from aura_backend.inference.wan_loader import resolve_offload_folder

        # A directory can never be created *inside* a regular file, on any OS.
        blocker = tmp_path / "afile"
        blocker.write_bytes(b"x")
        bad = str(blocker / "off")
        out = resolve_offload_folder(bad)
        assert out.startswith(tempfile.gettempdir())
        assert out != bad

    def test_explicit_preferred_path_used_verbatim(self, tmp_path):
        from aura_backend.inference.wan_loader import resolve_offload_folder

        # No env consulted here: the caller applies the env-or-default first.
        out = resolve_offload_folder(str(tmp_path / "mine"))
        assert out == str(tmp_path / "mine")


class TestGeneratorDeviceMatchesPipeline:
    def test_pure_cuda_pipeline_uses_cuda_generator(self):
        from aura_backend.inference.wan_pipeline import _pipeline_generator_device

        class _Tensor:
            def __init__(self, type_): self.type = type_

        class _P:
            class _M:
                def parameters(self_inner):
                    return [type("P", (), {"device": _Tensor("cuda")})()]

            transformer = _M()

        assert _pipeline_generator_device(_P()) == "cuda"

    def test_cpu_pipeline_uses_cpu_generator(self):
        from aura_backend.inference.wan_pipeline import _pipeline_generator_device

        class _Tensor:
            def __init__(self, type_): self.type = type_

        class _P:
            class _M:
                def parameters(self_inner):
                    return [type("P", (), {"device": _Tensor("cpu")})()]

            transformer = _M()

        assert _pipeline_generator_device(_P()) == "cpu"

    def test_offloaded_pipeline_falls_back_to_default(self):
        from aura_backend.inference.wan_pipeline import _pipeline_generator_device

        # With disk offload, all parameters report "meta" (no resident device).
        class _Tensor:
            def __init__(self, type_): self.type = type

        class _P:
            class _M:
                def parameters(self_inner):
                    return [type("P", (), {"device": _Tensor("meta")})()]

            transformer = _M()

        # CUDA box → falls back to cuda; CPU-only box → cpu. Either is
        # the right answer here (the offload code re-places during the call).
        assert _pipeline_generator_device(_P()) in {"cuda", "cpu"}


class _FakeCV2Writer:
    def __init__(self, path, *args):
        self._path = str(path)
        self._frames = 0

    def write(self, frame):
        self._frames += 1

    def release(self):
        with open(self._path, "wb") as f:
            # Realistic payload (>1KB so the file-size validation passes).
            f.write(b"fake-mp4-frame" * 32 * max(1, self._frames))


class _FakeCV2Capture:
    def __init__(self, path):
        self._path = str(path)

    def isOpened(self):
        import os

        return os.path.exists(self._path)

    def get(self, prop):
        import os

        if prop == _FakeCV2.CAP_PROP_FRAME_COUNT:
            return 10
        if prop == _FakeCV2.CAP_PROP_FPS:
            return 12.0
        if prop == _FakeCV2.CAP_PROP_FRAME_WIDTH:
            return 64
        if prop == _FakeCV2.CAP_PROP_FRAME_HEIGHT:
            return 80
        return 0

    def release(self):
        pass


class _FakeCV2:
    CAP_PROP_FRAME_COUNT = 7
    CAP_PROP_FPS = 5
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    COLOR_RGB2BGR = 4
    VideoWriter = _FakeCV2Writer
    VideoCapture = _FakeCV2Capture

    @staticmethod
    def VideoWriter_fourcc(*args):
        return 0

    @staticmethod
    def cvtColor(arr, code):
        return arr


def _install_fake_cv2(monkeypatch):
    import importlib.machinery
    import sys

    mod = _FakeCV2
    mod.__spec__ = importlib.machinery.ModuleSpec("cv2", loader=None)
    monkeypatch.setitem(sys.modules, "cv2", mod)


class _FakeStorage:
    def __init__(self):
        self.blobs = {}

    def put(self, key, data, content_type="application/octet-stream"):
        self.blobs[key] = bytes(data)
        return key

    def get(self, key):
        return self.blobs[key]

    def get_url(self, key):
        return f"/api/v1/storage/{key}"


class TestEncodeValidateOrdering:
    def _ctx10(self):
        from aura_backend.inference.wan_config import WanGenerationConfig, WanModelConfig
        from aura_backend.inference.wan_pipeline import PipelineContext

        PILImage = pytest.importorskip("PIL.Image")
        return PipelineContext(
            job_id="job-order-1",
            session_id="sess-1",
            experience_id="aurora",
            capture_ref="captures/x.jpg",
            config=WanGenerationConfig(
                prompt="a cinematic test prompt",
                width=64,
                height=80,
                num_frames=10,
                fps=12,
            ),
            model_config=WanModelConfig(),
        ), [PILImage.new("RGB", (64, 80)) for _ in range(10)]

    def test_encode_keeps_file_validation_passes_cleanup_removes(
        self, monkeypatch
    ):
        _install_fake_cv2(monkeypatch)
        import aura_backend.storage as storage_mod
        from aura_backend.inference.wan_pipeline import (
            CleanupStage,
            OutputValidationStage,
            VideoEncodingStage,
        )

        fake_storage = _FakeStorage()
        monkeypatch.setattr(storage_mod, "get_storage", lambda: fake_storage)

        ctx, frames = self._ctx10()
        ctx.video_frames = frames
        ctx = VideoEncodingStage()(ctx)
        import os

        # THE regression: encoder must NOT delete the temp file; validation
        # runs next and needs it on disk.
        assert os.path.exists(ctx.output_path), "encoder deleted file before validation"
        ctx = OutputValidationStage()(ctx)
        assert ctx.metadata.get("validation_passed") is True
        assert ctx.video_asset is not None
        # Durable copy exists under the job key.
        assert ctx.video_asset.key in fake_storage.blobs
        ctx = CleanupStage()(ctx)
        assert not os.path.exists(ctx.output_path), "cleanup must remove temp file"
        assert ctx.metadata.get("cleanup_done") is True

    def test_validation_fails_cleanly_when_file_truly_missing(self, monkeypatch):
        _install_fake_cv2(monkeypatch)
        from aura_backend.errors import ValidationFailed
        from aura_backend.inference.wan_pipeline import (
            OutputValidationStage,
            PipelineError,
        )

        ctx, _ = self._ctx10()
        ctx.output_path = "/definitely/not/here.mp4"
        with pytest.raises(PipelineError) as ei:
            OutputValidationStage()(ctx)
        assert isinstance(ei.value.original_error, ValidationFailed)
        assert "not found" in str(ei.value.original_error).lower()


def _install_fake_imageio(monkeypatch, tmp_path):
    import importlib.machinery
    import sys
    import types

    calls: dict = {}

    class _Writer:
        def __init__(self, path, **kwargs):
            calls["path"] = str(path)
            calls["kwargs"] = kwargs
            self._frames = 0

        def append_data(self, arr):
            self._frames += 1

        def close(self):
            with open(calls["path"], "wb") as f:
                f.write(b"fake-h264" * 200 * max(1, self._frames))

    pkg = types.ModuleType("imageio")
    pkg.__path__ = []
    pkg.__spec__ = importlib.machinery.ModuleSpec("imageio", loader=None)
    v2 = types.ModuleType("imageio.v2")
    v2.__spec__ = importlib.machinery.ModuleSpec("imageio.v2", loader=None)
    v2.get_writer = lambda path, **kw: _Writer(path, **kw)
    pkg.v2 = v2
    ff = types.ModuleType("imageio_ffmpeg")
    ff.__spec__ = importlib.machinery.ModuleSpec("imageio_ffmpeg", loader=None)
    monkeypatch.setitem(sys.modules, "imageio", pkg)
    monkeypatch.setitem(sys.modules, "imageio.v2", v2)
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", ff)
    return calls


class TestH264Encoding:
    def test_prefers_libx264_with_browser_params(self, monkeypatch, tmp_path):
        from aura_backend.inference.wan_pipeline import write_mp4_video

        PILImage = pytest.importorskip("PIL.Image")
        calls = _install_fake_imageio(monkeypatch, tmp_path)
        out = tmp_path / "v.mp4"
        codec, size = write_mp4_video(out, [PILImage.new("RGB", (64, 80)) for _ in range(3)], 12)
        assert codec == "h264"
        assert size > 1000
        assert calls["kwargs"]["codec"] == "libx264"
        assert "-pix_fmt" in calls["kwargs"]["ffmpeg_params"]
        assert "yuv420p" in calls["kwargs"]["ffmpeg_params"]
        assert "faststart" in " ".join(calls["kwargs"]["ffmpeg_params"])

    def test_neither_backend_raises_import_error(self, monkeypatch, tmp_path):
        import sys

        from aura_backend.inference import wan_pipeline as wp

        monkeypatch.delitem(sys.modules, "imageio", raising=False)
        monkeypatch.delitem(sys.modules, "imageio.v2", raising=False)
        monkeypatch.delitem(sys.modules, "imageio_ffmpeg", raising=False)
        monkeypatch.delitem(sys.modules, "cv2", raising=False)
        # Force find_spec to miss for both backends.
        import importlib.util as _ilu

        real_find = _ilu.find_spec
        monkeypatch.setattr(
            _ilu, "find_spec", lambda name: None if name in ("imageio", "imageio_ffmpeg", "cv2") else real_find(name)
        )
        # Sanity: the real cv2 must not leak in (laptop has none anyway).
        assert "cv2" not in sys.modules
        PILImage = pytest.importorskip("PIL.Image")
        with pytest.raises(ImportError):
            wp.write_mp4_video(tmp_path / "v.mp4", [PILImage.new("RGB", (8, 8))], 12)


class TestTemporalLattice:
    def test_snap_matches_pipeline_floor(self):
        from aura_backend.inference.wan_config import snap_num_frames

        assert snap_num_frames(48) == 49  # default 4s @ 12fps
        assert snap_num_frames(81) == 81  # already on lattice
        assert snap_num_frames(8) == 9
        assert snap_num_frames(45) == 45

    def test_config_snaps_by_default(self):
        from aura_backend.inference.wan_config import WanGenerationConfig

        cfg = WanGenerationConfig(prompt="a cinematic test prompt")
        assert cfg.num_frames == 49

    def test_ftfy_importable_for_wan_prompt_cleaning(self):
        # diffusers' Wan basic_clean calls ftfy.fix_text; without the package
        # prompt encoding dies with NameError deep inside inference.
        ftfy = pytest.importorskip("ftfy")
        assert ftfy.fix_text("hello") == "hello"
