from pathlib import Path


def test_settings_sources_never_define_a_browser_ai_key_field() -> None:
    root = Path(__file__).resolve().parents[2]
    paths = [
        root / "api/v1/schemas/preferences.py",
        root / "frontend/assets/features/settings/view.mjs",
        root / "frontend/assets/data-sources/public.mjs",
        root / "frontend/assets/data-sources/operator.mjs",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "api" + "_key" not in combined.lower()
    assert "openai" + "_api" not in combined.lower()
    assert "secret" not in combined.lower()
