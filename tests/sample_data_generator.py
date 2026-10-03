"""Import the generator from the existing hyphenated sample-data directory."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def load_generator():
    source = Path(__file__).resolve().parents[1] / "sample-data" / "generate.py"
    spec = spec_from_file_location("synthetic_sample_data_generator", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {source}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
