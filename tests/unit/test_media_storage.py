from __future__ import annotations

from infrastructure.media.storage import mime_for_ext


class TestMimeForExt:
    def test_jpg(self) -> None:
        assert mime_for_ext("jpg") == "image/jpeg"

    def test_jpeg(self) -> None:
        assert mime_for_ext("jpeg") == "image/jpeg"

    def test_png(self) -> None:
        assert mime_for_ext("png") == "image/png"

    def test_gif(self) -> None:
        assert mime_for_ext("gif") == "image/gif"

    def test_webp(self) -> None:
        assert mime_for_ext("webp") == "image/webp"

    def test_mp4(self) -> None:
        assert mime_for_ext("mp4") == "video/mp4"

    def test_ogg(self) -> None:
        assert mime_for_ext("ogg") == "audio/ogg"

    def test_mp3(self) -> None:
        assert mime_for_ext("mp3") == "audio/mpeg"

    def test_unknown_extension(self) -> None:
        assert mime_for_ext("xyz") == "application/octet-stream"

    def test_empty_extension(self) -> None:
        assert mime_for_ext("") == "application/octet-stream"

    def test_mixed_case_not_supported(self) -> None:
        assert mime_for_ext("JPG") == "application/octet-stream"
