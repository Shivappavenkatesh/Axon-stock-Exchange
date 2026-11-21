"""Compatibility runtime entrypoint.

The canonical implementation lives in axon_aone.orchestration.main.
This module remains so `python -m axon_aone.main` and existing imports
continue to work without duplicating runtime logic.
"""

from axon_aone.orchestration.main import main, parse_runtime_args, run_cli, run_scheduled

__all__ = ["main", "parse_runtime_args", "run_cli", "run_scheduled"]


if __name__ == "__main__":
    run_cli()
