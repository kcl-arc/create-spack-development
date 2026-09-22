#!/usr/bin/env python3
"""
Submit a Slurm job to install a Spack environment:
spack -e <env> install --yes-to-all -p 4 -j <cpus/4>.

Reads <envs_dir>/setup_state.yaml (written by setup.py) for defaults.
"""

from er_spack_common import build_step_parser, submit_step


def main():
    parser = build_step_parser("Install a Spack environment (spack install) via Slurm")
    args = parser.parse_args()
    submit_step(
        args,
        step_id="install",
        step_title="Install",
        spack_step_args="install --yes-to-all -p ${INSTALL_CONCURRENT_PACKAGES} -j ${INSTALL_JOBS}",
        compiler_check=True,
    )


if __name__ == "__main__":
    main()
