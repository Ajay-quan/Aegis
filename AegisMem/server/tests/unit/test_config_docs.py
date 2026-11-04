"""Configuration documentation must not drift from the real settings."""
import re
from pathlib import Path

from core.config.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_env_example_only_documents_real_settings():
    fields = {f.upper() for f in Settings.model_fields}
    keys = re.findall(r"^([A-Z0-9_]+)=", (ROOT / ".env.example").read_text(), re.M)
    assert keys and not [k for k in keys if k not in fields]
