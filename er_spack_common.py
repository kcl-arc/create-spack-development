#!/usr/bin/env python3
"""
Shared helpers for the er-spack-development batch step scripts
(spack_concretize.py, spack_pkgs_install.py, spack_mod_refresh.py).

Reads <envs_dir>/setup_state.yaml (written by setup.py) for paths and the
default environment, renders slurm_env_step.j2, and submits it with sbatch
(Singularity runs on compute nodes only).
"""

import argparse
import datetime
import os
import re
import subprocess
import sys

try:
    import jinja2
    import yaml
except ImportError:
    print("Error: jinja2 and pyyaml are required. pip install jinja2 pyyaml", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ENVS_DIR = os.path.join(os.path.abspath(os.path.join(SCRIPT_DIR, "..")), "environments")
DEFAULT_PARTITION = "interruptible_cpu"
DEFAULT_SLURM_ARGS = "#SBATCH --ntasks=4\n#SBATCH --mem-per-cpu=4096"
SPACK_IN_CONTAINER = "/opt/spack/bin/spack"


def build_step_parser(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "-e",
        "--environment-name",
        default=None,
        help="Spack environment name under <envs-dir>/ (default: environment from setup_state.yaml, e.g. arc-ops-env)",
    )
    parser.add_argument(
        "--envs-dir",
        default=None,
        help=f"Environments dir written by setup.py (default: {DEFAULT_ENVS_DIR})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the job script, do not sbatch")
    parser.add_argument("--wait", action="store_true", help="Pass sbatch --wait (return when the job finishes)")
    parser.add_argument(
        "--partition",
        default=DEFAULT_PARTITION,
        help=f"Slurm partition (default: {DEFAULT_PARTITION})",
    )
    parser.add_argument(
        "--constraint",
        default=None,
        help="Optional Slurm --constraint (e.g. zen3) matching the environment's target",
    )
    parser.add_argument(
        "--slurm-args",
        default=DEFAULT_SLURM_ARGS,
        help="Extra #SBATCH lines for the job (default matches setup defaults)",
    )
    return parser


def load_setup_state(envs_dir):
    state_path = os.path.join(envs_dir, "setup_state.yaml")
    if not os.path.isfile(state_path):
        sys.exit(
            f"Cannot find {state_path}. Run ./setup.py first "
            "(it writes setup_state.yaml into the environments dir)."
        )
    with open(state_path) as fh:
        data = yaml.safe_load(fh) or {}
    setup = data.get("setup")
    if not isinstance(setup, dict):
        sys.exit(f"No 'setup:' section in {state_path}; re-run ./setup.py.")
    return setup


def _require(setup, key, envs_dir):
    value = setup.get(key)
    if not value:
        sys.exit(f"Missing '{key}' in {os.path.join(envs_dir, 'setup_state.yaml')}; re-run ./setup.py.")
    return value


def submit_step(args, step_id, step_title, spack_step_args, compiler_check):
    envs_dir = (
        os.path.abspath(os.path.expanduser(args.envs_dir)) if args.envs_dir else DEFAULT_ENVS_DIR
    )
    setup = load_setup_state(envs_dir)

    environment_name = args.environment_name or setup.get("environment_name")
    if not environment_name:
        sys.exit("No environment name: pass -e/--environment-name or re-run ./setup.py.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", environment_name):
        sys.exit(
            f"Invalid environment name: {environment_name!r} "
            "(allowed: letters, digits, '_', '.', '-')"
        )

    env_manifest = os.path.join(envs_dir, environment_name, "spack.yaml")
    if not os.path.isfile(env_manifest):
        sys.exit(
            f"Cannot find {env_manifest}. Re-run ./setup.py (or create the environment "
            "manifest) before submitting batch steps."
        )

    outputs_dir = _require(setup, "outputs_dir", envs_dir)
    repo_dir = _require(setup, "packages_repo_path", envs_dir)
    spack_user_config_path = _require(setup, "spack_user_config_path", envs_dir)
    sif_path = _require(setup, "sif_path", envs_dir)

    build_results_dir = os.path.join(envs_dir, "build_results")
    os.makedirs(build_results_dir, exist_ok=True)

    safe_env_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", environment_name).strip("_") or "env"
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    build_name = f"{step_id}_{safe_env_name}_{stamp}"
    output_file = os.path.join(build_results_dir, f"{build_name}.out")
    job_path = os.path.join(build_results_dir, f"{build_name}.sh")

    job_template_path = os.path.join(SCRIPT_DIR, "slurm_env_step.j2")
    with open(job_template_path) as fh:
        tpl = jinja2.Template(fh.read(), trim_blocks=True, lstrip_blocks=True)

    ctx = {
        "step_id": step_id,
        "step_title": step_title,
        "spack_step_args": spack_step_args,
        "compiler_check": compiler_check,
        "partition": args.partition,
        "slurm_args": args.slurm_args,
        "environment_name": environment_name,
        "framework_dir": SCRIPT_DIR,
        "repo_dir": repo_dir,
        "envs_dir": envs_dir,
        "outputs_dir": outputs_dir,
        "spack_user_config_path": spack_user_config_path,
        "sif_path": sif_path,
        "spack_in_container": SPACK_IN_CONTAINER,
        "build_name": build_name,
        "build_results_dir": build_results_dir,
        "output_file": output_file,
    }

    script = tpl.render(**ctx)
    if args.dry_run:
        print(script)
        return

    with open(job_path, "w") as fh:
        fh.write(script)
    os.chmod(job_path, 0o755)

    sbatch_cmd = ["sbatch", "--parsable", "--output", output_file]
    if args.wait:
        sbatch_cmd.append("--wait")
    if args.constraint:
        sbatch_cmd.extend(["--constraint", args.constraint])
    sbatch_cmd.append(job_path)

    result = subprocess.run(sbatch_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    print(f"Submitted {build_name}: {result.stdout.strip()}")
    if args.wait:
        print(f"Job finished; output: {output_file}")
    else:
        print(f"Output will be written to {output_file}")
