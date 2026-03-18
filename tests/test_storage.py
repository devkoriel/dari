import json

from src.storage import JsonStore


class TestJsonStore:
    def test_save_and_load(self, tmp_path):
        path = tmp_path / "store.json"
        store = JsonStore(path)
        store.set("dday_dates", "Anniversary", "2024-06-15")
        store.save()

        store2 = JsonStore(path)
        assert store2.get("dday_dates", "Anniversary") == "2024-06-15"

    def test_default_sections(self, tmp_path):
        path = tmp_path / "store.json"
        store = JsonStore(path)
        assert store.get_section("dday_dates") == {}
        assert store.get_section("learn_mode") == {}
        assert store.get_section("user_stats") == {}

    def test_corrupt_file_recovery(self, tmp_path):
        path = tmp_path / "store.json"
        path.write_text("NOT VALID JSON {{{")
        store = JsonStore(path)
        assert store.get_section("dday_dates") == {}

    def test_delete_key(self, tmp_path):
        path = tmp_path / "store.json"
        store = JsonStore(path)
        store.set("dday_dates", "test", "2024-01-01")
        store.delete("dday_dates", "test")
        assert store.get("dday_dates", "test") is None

    def test_get_default(self, tmp_path):
        path = tmp_path / "store.json"
        store = JsonStore(path)
        assert store.get("dday_dates", "missing") is None
        assert store.get("dday_dates", "missing", "fallback") == "fallback"

    def test_atomic_write(self, tmp_path):
        path = tmp_path / "store.json"
        store = JsonStore(path)
        store.set("dday_dates", "test", "2024-01-01")
        store.save()

        # Verify the file is valid JSON
        with open(path) as f:
            data = json.load(f)
        assert data["dday_dates"]["test"] == "2024-01-01"

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "subdir" / "nested" / "store.json"
        store = JsonStore(path)
        store.set("learn_mode", "123", True)
        store.save()
        assert path.exists()

    def test_get_section_returns_copy(self, tmp_path):
        path = tmp_path / "store.json"
        store = JsonStore(path)
        store.set("dday_dates", "test", "2024-01-01")
        section = store.get_section("dday_dates")
        section["test"] = "mutated"
        assert store.get("dday_dates", "test") == "2024-01-01"
