from __future__ import annotations

from app.media_config import _type_matches


class TestTypeMatches:
    def test_wildcard_matches_any(self) -> None:
        assert _type_matches(["all"], "photo") is True
        assert _type_matches(["all"], "video") is True

    def test_wildcard_matches_none(self) -> None:
        assert _type_matches(["all"], None) is True

    def test_exact_type_match(self) -> None:
        assert _type_matches(["photo"], "photo") is True

    def test_partial_type_match(self) -> None:
        assert _type_matches(["doc"], "document") is True

    def test_no_match(self) -> None:
        assert _type_matches(["photo"], "video") is False

    def test_no_match_none_type(self) -> None:
        assert _type_matches(["photo"], None) is False

    def test_multiple_types_one_matches(self) -> None:
        assert _type_matches(["photo", "video", "audio"], "audio") is True

    def test_multiple_types_none_match(self) -> None:
        assert _type_matches(["photo", "video"], "sticker") is False

    def test_empty_list_returns_false(self) -> None:
        assert _type_matches([], "photo") is False

    def test_empty_list_with_none(self) -> None:
        assert _type_matches([], None) is False
