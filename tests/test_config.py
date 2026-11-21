"""Settings: defaults, persistence, language routing metadata, portable mode."""

from __future__ import annotations

import json

import pytest

from lcsc_core.routing import DEFAULT_LANGUAGE
from services import config


@pytest.fixture()
def isolated(monkeypatch, workdir):
    """Point every config/state location at a temporary directory."""
    monkeypatch.setenv("KICAD_LIBGEN_LCSC_CONFIG_DIR", str(workdir / "cfg"))
    monkeypatch.setenv("KICAD_LIBGEN_LCSC_LOG_DIR", str(workdir / "logs"))
    monkeypatch.setenv("KICAD_LIBGEN_LCSC_CACHE_DIR", str(workdir / "cache"))
    monkeypatch.delenv("KICAD_LIBGEN_LCSC_PORTABLE", raising=False)
    return workdir


class TestDefaults:
    def test_defaults_are_sane(self, isolated):
        settings = config.Settings()
        assert settings.language == DEFAULT_LANGUAGE
        assert settings.page_size == config.DEFAULT_PAGE_SIZE
        assert settings.cache_ttl == config.DEFAULT_CACHE_TTL
        assert settings.request_interval == pytest.approx(
            config.DEFAULT_REQUEST_INTERVAL_MS / 1000)
        assert settings.database_path.endswith("components.db")

    def test_unknown_language_is_normalised(self, isolated):
        assert config.Settings(language="de_DE").language == DEFAULT_LANGUAGE
        assert config.Settings(language="en_US").language == "en_US"

    def test_page_size_snaps_to_an_allowed_value(self, isolated):
        assert config.Settings(page_size=45).page_size in config.PAGE_SIZES
        assert config.Settings(page_size=1000).page_size == max(config.PAGE_SIZES)

    def test_limits_are_clamped(self, isolated):
        settings = config.Settings(http_timeout=9999, request_interval_ms=-50,
                                   batch_delay_ms=99999)
        assert settings.http_timeout == 120
        assert settings.request_interval_ms == 0
        assert settings.batch_delay_ms == 10000

    def test_language_label_matches_the_routing_table(self, isolated):
        assert config.Settings(language="en_US").language_label.startswith("English")


class TestPersistence:
    def test_round_trip(self, isolated):
        settings = config.Settings(language="en_US", page_size=60, cache_ttl=0)
        path = settings.save()
        assert path.exists()
        reloaded = config.Settings.load()
        assert reloaded.language == "en_US"
        assert reloaded.page_size == 60
        assert reloaded.cache_ttl == 0

    def test_malformed_file_falls_back_to_defaults(self, isolated):
        target = config.settings_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{not json", encoding="utf-8")
        assert config.Settings.load().language == DEFAULT_LANGUAGE

    def test_unknown_keys_are_ignored(self, isolated):
        target = config.settings_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"language": "en_US", "nonsense": 1}), encoding="utf-8")
        settings = config.Settings.load()
        assert settings.language == "en_US"
        assert not hasattr(settings, "nonsense")

    def test_recent_databases_are_deduplicated_and_capped(self, isolated):
        settings = config.Settings()
        for index in range(12):
            settings.add_recent(isolated / f"db{index}.db")
        settings.add_recent(isolated / "db11.db")
        assert len(settings.recent_databases) == config.MAX_RECENT_DATABASES
        assert settings.recent_databases[0].endswith("db11.db")
        assert settings.database_path.endswith("db11.db")

    def test_to_dict_has_no_private_path(self, isolated):
        settings = config.Settings()
        settings.save()
        assert "source_path" not in settings.to_dict()
        assert settings.config_folder.exists()


class TestLocations:
    def test_state_and_cache_live_under_the_override(self, isolated):
        assert config.log_dir() == isolated / "logs"
        assert config.cache_dir() == isolated / "cache"

    def test_sync_folder_detection(self):
        assert config.sync_folder_name("/home/u/OneDrive/parts.db") == "OneDrive"
        assert config.sync_folder_name("C:/Users/u/Dropbox/x.db") == "Dropbox"
        assert config.sync_folder_name("C:/Users/u/KiCadLibGenLCSC/x.db") is None
