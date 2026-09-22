#!/usr/bin/env python3
"""
Submit a Slurm job to rebuild the tcl modules for a Spack environment:
spack -e <env> module tcl refresh -y.

Reads <envs_dir>/setup_state.yaml (written by setup.py) for defaults.
"""

from er_spack_common import build_step_parser, submit_step


def main():
    parser = build_step_parser("Refresh tcl modules for a Spack environment via Slurm")
    args = parser.parse_args()
    submit_step(
        args,
        step_id="mod_refresh",
        step_title="Module refresh",
        spack_step_args="module tcl refresh -y",
        compiler_check=False,
    )


if __name__ == "__main__":
    main()
