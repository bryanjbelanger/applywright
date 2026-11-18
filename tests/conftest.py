import pytest

from applywright.server import mcp_app
from applywright.storage.repository import JobRepository


@pytest.fixture
def mcp_setup(tmp_path):
    """Point the MCP handlers at a temporary database and import directory."""
    db_path = str(tmp_path / "jobs.db")
    import_dir = tmp_path / "imports"
    import_dir.mkdir()
    old = (mcp_app.DB_PATH, mcp_app.IMPORT_DIR, mcp_app._repo)
    mcp_app.DB_PATH, mcp_app.IMPORT_DIR, mcp_app._repo = db_path, str(import_dir), None
    yield db_path, str(import_dir)
    mcp_app.DB_PATH, mcp_app.IMPORT_DIR, mcp_app._repo = old


@pytest.fixture
def lifecycle_repo(tmp_path):
    return JobRepository(str(tmp_path / "lifecycle.db"))
