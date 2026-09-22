#!/usr/bin/env python3
"""
Submit a Slurm job to concretize a Spack environment:
spack -e <env> concretize -f (always forced, for determinism).

Reads <envs_dir>/setup_state.yaml (written by setup.py) for defaults.
"""

from er_spack_common import build_step_parser, submit_step


def main():
    parser = build_step_parser("Concretize a Spack environment (spack concretize -f) via Slurm")
    args = parser.parse_args()
    submit_step(
        args,
        step_id="concretize",
        step_title="Concretize",
        spack_step_args="concretize -f",
        compiler_check=True,
    )


if __name__ == "__main__":
    main()
