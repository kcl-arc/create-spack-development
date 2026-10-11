#!/usr/bin/env python3
"""
Submit a Slurm job to rebuild the tcl modules for Spack environment(s):
spack -e <env> module tcl refresh -y.

Run directly (not via sbatch). Reads var/setup_state.yaml (written by setup.py).
"""

import sys

try:
    from er_spack_common import build_step_parser, parse_args, run_steps
except ModuleNotFoundError as e:
    if e.name != "er_spack_common":
        raise
    sys.exit(
        "Cannot import er_spack_common. Run this script directly from the "
        "create-spack-development checkout; it submits its own Slurm jobs, so "
        "don't submit it with sbatch."
    )


def main():
    parser = build_step_parser("Refresh tcl modules for Spack environment(s) via Slurm")
    args = parse_args(parser)
    run_steps(args, ["mod_refresh"])


if __name__ == "__main__":
    main()
