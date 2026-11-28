"""Keep automated worker-state persistence isolated from local VTT user data."""
import os
import tempfile
from pathlib import Path

_state_dir = Path(tempfile.mkdtemp(prefix="vtt-pytest-state-"))
os.environ["VTT_JOB_STATE_DB"] = str(_state_dir / "jobs.sqlite3")
