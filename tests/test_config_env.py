"""Local .env loading must be deterministic, optional and safe for reload/deployment."""
import os
import subprocess
import sys
from pathlib import Path

from app import config
from app.config import Settings, load_repository_env
from app.saas.training import TrainingEngine


def test_repository_env_loads_expected_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("TRAINING_PHONE_ENABLED=true\nPUBLIC_BASE_URL=https://local.example\n")
    monkeypatch.delenv("TRAINING_PHONE_ENABLED", raising=False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("DIDM_LOAD_DOTENV", "true")

    assert load_repository_env(env)
    s = Settings()
    assert s.training_phone_enabled is True
    assert s.public_base_url == "https://local.example"


def test_process_environment_has_precedence(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql://must-not-win.invalid/db\nMIGRATE_ON_START=true\n")
    monkeypatch.setenv("DIDM_LOAD_DOTENV", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./didm.db")
    monkeypatch.setenv("MIGRATE_ON_START", "false")

    assert load_repository_env(env)
    s = Settings()
    assert s.database_url == "sqlite:///./didm.db"
    assert s.migrate_on_start is False


def test_environment_loading_opt_out(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("TRAINING_PHONE_ENABLED=true\n")
    monkeypatch.delenv("TRAINING_PHONE_ENABLED", raising=False)
    monkeypatch.setenv("DIDM_LOAD_DOTENV", "false")

    assert load_repository_env(env) is False
    assert Settings().training_phone_enabled is False


def test_only_repository_dotenv_name_is_configured():
    assert config.LOCAL_ENV_FILE.name == ".env"
    assert config.LOCAL_ENV_FILE.parent == config.REPOSITORY_ROOT
    assert config.LOCAL_ENV_FILE.name not in {".env.demo", ".env.example", "demo.env"}


def test_reload_child_process_keeps_safe_database_override():
    env = os.environ.copy()
    env.update({
        "DIDM_LOAD_DOTENV": "true",
        "DATABASE_URL": "sqlite:///./didm.db",
        "MIGRATE_ON_START": "false",
        "TRAINING_PHONE_ENABLED": "true",
    })
    result = subprocess.run(
        [sys.executable, "-c", "from app.config import settings; "
         "print(settings.database_url, settings.migrate_on_start, settings.training_phone_enabled)"],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == "sqlite:///./didm.db False True"


def test_phone_availability_requires_complete_runtime_configuration():
    complete = Settings()
    complete.training_phone_enabled = True
    complete.training_webhook_secret = "present"
    complete.public_base_url = "https://local.example"
    assert TrainingEngine(complete, sarvam=object()).phone_available() is True

    for field in ("training_webhook_secret", "public_base_url"):
        incomplete = Settings()
        incomplete.training_phone_enabled = True
        incomplete.training_webhook_secret = "present"
        incomplete.public_base_url = "https://local.example"
        setattr(incomplete, field, "")
        assert TrainingEngine(incomplete, sarvam=object()).phone_available() is False

    complete.training_phone_enabled = False
    assert TrainingEngine(complete, sarvam=object()).phone_available() is False
    complete.training_phone_enabled = True
    assert TrainingEngine(complete, sarvam=None).phone_available() is False
