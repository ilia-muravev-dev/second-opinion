from second_opinion.config import load_settings


def test_defaults_are_sane(monkeypatch) -> None:
    monkeypatch.delenv("SO_PROVIDER", raising=False)
    settings = load_settings(_env_file=None)
    assert settings.provider == "anthropic"
    assert settings.max_request_tokens <= settings.max_pr_tokens


def test_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("SO_PROVIDER", "openai")
    monkeypatch.setenv("SO_MODEL", "some/free-model")
    settings = load_settings(_env_file=None)
    assert settings.provider == "openai"
    assert settings.model == "some/free-model"
