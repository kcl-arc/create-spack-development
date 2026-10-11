#!/usr/bin/env python3
"""
Submit concretize -> install -> module refresh for Spack environment(s) as a
chain of Slurm jobs; each job starts only if the previous one succeeded, and a
failure cancels the rest of the chain.

Run directly (not via sbatch). Reads var/setup_state.yaml (written by setup.py).
"""

import sys

try:
    from er_spack_common import STEP_ORDER, build_step_parser, parse_args, run_steps
except ModuleNotFoundError as e:
    if e.name != "er_spack_common":
        raise
    sys.exit(
        "Cannot import er_spack_common. Run this script directly from the "
        "create-spack-development checkout; it submits its own Slurm jobs, so "
        "don't submit it with sbatch."
    )


def main():
    parser = build_step_parser("Concretize, install and refresh modules for Spack environment(s) via chained Slurm jobs")
    args = parse_args(parser)
    run_steps(args, STEP_ORDER)


if __name__ == "__main__":
    main()
