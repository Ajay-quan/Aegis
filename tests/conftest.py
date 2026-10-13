"""Root test configuration."""
import sys
import os

# macOS/iCloud sync-conflict copies ("test_x 2.py") must never be collected as tests.
collect_ignore_glob = ["* 2.py", "**/* 2.py"]

# Tests must not read a developer's personal .env (set before settings are imported).
os.environ["AEGIS_ENV_FILE"] = ""

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest_plugins = ["tests.fixtures.conftest"]


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
async def _isolated_control_plane(tmp_path):
    """Every test gets its own durable control plane (SQLite file) - never the dev DB."""
    from adapters.relational_store.control_store import ControlStore
    from apps.api import dependencies as deps
    from apps.api.main import app
    from services.learning_runtime import LearningRuntime

    store = ControlStore(f"sqlite+aiosqlite:///{tmp_path}/control.db")
    await store.create_schema()
    runtime = LearningRuntime(store, hash_secret="test-secret")
    app.dependency_overrides[deps.get_control_store] = lambda: store
    app.dependency_overrides[deps.get_runtime] = lambda: runtime
    yield store
    app.dependency_overrides.pop(deps.get_control_store, None)
    app.dependency_overrides.pop(deps.get_runtime, None)
    await store.close()


@pytest.fixture(autouse=True)
def _no_rate_limits(monkeypatch):
    """Shared in-process buckets would make unrelated tests flaky; rate-limit tests opt back in."""
    from core.config.settings import settings
    monkeypatch.setattr(settings, "rate_limit_backend", "off")
