import pytest
from sqlmodel import SQLModel, create_engine


@pytest.fixture
def db_engine(tmp_path):
    """A throwaway sqlite DB, schema created, isolated per test.

    Modules under test import `engine` by name at module load time (same
    pattern the rest of the codebase uses), so a test needs to patch that
    name directly, e.g. `monkeypatch.setattr("Hub.KeymapResolver.engine",
    db_engine)` - patching db_manager.db_manager.engine has no effect on
    already-imported references.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    return engine
