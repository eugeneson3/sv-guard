from app.settings import (
    DEFAULT_SETTINGS_YAML,
    EditorSettings,
    Settings,
    default_settings_path,
    ensure_settings_file,
    load_settings,
    parse_settings,
)


def test_default_template_parses_cleanly():
    settings, warnings = parse_settings(DEFAULT_SETTINGS_YAML)
    assert settings == Settings()
    assert warnings == []


def test_overrides():
    settings, warnings = parse_settings("editor:\n  tab_width: 2\n  insert_spaces: false\n")
    assert settings.editor == EditorSettings(tab_width=2, insert_spaces=False)
    assert warnings == []


def test_bad_values_fall_back_with_warnings():
    text = "editor:\n  tab_width: 99\n  insert_spaces: 'yes'\n  font_size: true\n  bogus: 1\nother: {}\n"
    settings, warnings = parse_settings(text)
    assert settings == Settings()
    assert len(warnings) == 5
    assert any("editor.tab_width" in w and "1..16" in w for w in warnings)
    assert any("unknown setting 'editor.bogus'" in w for w in warnings)
    assert any("unknown setting section 'other'" in w for w in warnings)


def test_invalid_yaml_uses_defaults():
    settings, warnings = parse_settings("editor: [unclosed\n")
    assert settings == Settings()
    assert "not valid YAML" in warnings[0]


def test_missing_file_is_silent(tmp_path):
    assert load_settings(tmp_path / "nope.yaml") == (Settings(), [])


def test_ensure_creates_template_once(tmp_path):
    path = tmp_path / "sub" / "settings.yaml"
    ensure_settings_file(path)
    assert path.read_text(encoding="utf-8") == DEFAULT_SETTINGS_YAML
    path.write_text("editor:\n  tab_width: 8\n", encoding="utf-8")
    ensure_settings_file(path)
    assert load_settings(path)[0].editor.tab_width == 8


def test_config_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SVGUARD_CONFIG_DIR", str(tmp_path))
    assert default_settings_path() == tmp_path / "settings.yaml"
