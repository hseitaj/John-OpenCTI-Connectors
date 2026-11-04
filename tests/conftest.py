import sys
from pathlib import Path

# fake_opencti and run_connector live next to the tests.
sys.path.insert(0, str(Path(__file__).resolve().parent))
