#!/usr/bin/env python3
"""
Setup script for er-spack-development.

Renders Spack config templates into a per-user config directory and prepares
an outputs directory (install/source_cache/build_results) that is *separate*
from the git repo inputs (local_packages/ and package_installs/).

This is intended for non-privileged testing with the Singularity image.
"""

import argparse
import os
import sys

try:
    import jinja2
except ImportError:
    print("Error: jinja2 required. pip install jinja2", file=sys.stderr)
    sys.exit(1)

DEFAULT_SIF = "/software/containers/singularity/spack/spack_v1_1_1.sif"
DEFAULT_SPACK_CONFIG_HOME = ".spack_er_kcl_v1_1_1"

MODE_MESSAGES = {
    "test": (
        "Setup complete (test mode).\n"
        "Run a smoke build to validate the Singularity workflow before production cutover.\n"
    ),
    "development": (
        "Setup complete (development mode).\n"
        "Use for pre-production validation and iterative recipe updates.\n"
    ),
}


def main():
    parser = argparse.ArgumentParser(description="Configure er-spack-development environment")
    parser.add_argument(
        "--outputs-dir",
        required=True,
        help="Where outputs go (install/, source_cache/, build_results/). Create as a sibling of this repo.",
    )
    parser.add_argument(
        "--repo-dir",
        default=None,
        help="Repo inputs location (defaults to <setup.py_dir>/../er-spack-packages).",
    )
    parser.add_argument(
        "--spack-config-dir",
        default=None,
        help="Per-user Spack config directory (default: $HOME/.spack_er_kcl_v1_1_1). "
        "If you put it under --outputs-dir, ensure it includes $USER.",
    )
    parser.add_argument(
        "--mode",
        choices=["test", "development"],
        default="development",
        help="test/development affects the printed message (no Slack/integration in this repo).",
    )
    parser.add_argument(
        "--sif-path",
        default=DEFAULT_SIF,
        help=f"SIF image path (default: {DEFAULT_SIF})",
    )
    parser.add_argument(
        "--reuse",
        choices=["true", "false"],
        default="false",
        help="Spack concretizer reuse (default: false)",
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_repo_dir = os.path.abspath(os.path.join(script_dir, "..", "er-spack-packages"))
    repo_dir = os.path.abspath(args.repo_dir) if args.repo_dir else default_repo_dir

    template_dir = os.path.join(script_dir, "config", "templates")
    if not os.path.isdir(template_dir):
        print(f"Error: template dir not found: {template_dir}", file=sys.stderr)
        sys.exit(1)
    packages_yaml_source = os.path.join(script_dir, "config", "packages.yaml")
    if not os.path.isfile(packages_yaml_source):
        print(f"Error: packages.yaml not found: {packages_yaml_source}", file=sys.stderr)
        sys.exit(1)

    outputs_dir = os.path.abspath(os.path.expanduser(args.outputs_dir))
    os.makedirs(outputs_dir, exist_ok=True)

    home = os.path.expanduser("~")
    spack_config_dir = (
        os.path.abspath(os.path.expanduser(args.spack_config_dir))
        if args.spack_config_dir
        else os.path.join(home, DEFAULT_SPACK_CONFIG_HOME)
    )

    # repo inputs (git-pulled)
    local_packages_path = os.path.join(repo_dir, "local_packages")
    package_installs_path = os.path.join(repo_dir, "package_installs")

    # project outputs (separate from the git repo)
    install_prefix = os.path.join(outputs_dir, "install")
    source_cache_path = os.path.join(outputs_dir, "source_cache")
    build_results_path = os.path.join(outputs_dir, "build_results")

    if not os.path.isdir(local_packages_path):
        print(f"Error: local_packages not found at: {local_packages_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(package_installs_path):
        print(f"Error: package_installs not found at: {package_installs_path}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(spack_config_dir, exist_ok=True)
    os.makedirs(install_prefix, exist_ok=True)
    os.makedirs(source_cache_path, exist_ok=True)
    os.makedirs(build_results_path, exist_ok=True)

    ctx = {
        "install_prefix": install_prefix,
        "local_packages_path": local_packages_path,
        "source_cache_path": source_cache_path,
        "sif_path": args.sif_path,
        "reuse": args.reuse,
    }

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    for name in ["config.yaml", "concretizer.yaml", "modules.yaml", "repos.yaml"]:
        template_name = f"{name}.j2"
        try:
            tpl = env.get_template(template_name)
        except jinja2.TemplateNotFound:
            continue
        out_path = os.path.join(spack_config_dir, name)
        with open(out_path, "w") as f:
            f.write(tpl.render(**ctx))
        print(f"Wrote {out_path}")

    packages_yaml_dest = os.path.join(spack_config_dir, "packages.yaml")
    if os.path.lexists(packages_yaml_dest):
        os.remove(packages_yaml_dest)
    os.symlink(packages_yaml_source, packages_yaml_dest)
    print(f"Linked {packages_yaml_dest} -> {packages_yaml_source}")

    print()
    print(MODE_MESSAGES[args.mode])
    print("Environment:")
    print(f"  export SPACK_USER_CONFIG_PATH={spack_config_dir}")
    print()
    print("Bind mounts for singularity exec:")
    print(f"  --bind {script_dir}:{script_dir}  (for er-spack-development config/packages.yaml symlink target)")
    print(f"  --bind {repo_dir}:{repo_dir}  (for local_packages + package_installs)")
    print(f"  --bind {outputs_dir}:{outputs_dir}  (for install/, source_cache/, build_results/)")
    print(f"  --bind {spack_config_dir}:{spack_config_dir}  (for config in SPACK_USER_CONFIG_PATH)")
    print()
    print("Interactive install:")
    print(
        f"  singularity exec --bind {script_dir}:{script_dir} --bind {repo_dir}:{repo_dir} --bind {outputs_dir}:{outputs_dir} "
        f"--bind {spack_config_dir}:{spack_config_dir} {args.sif_path} /opt/spack/bin/spack install <spec>"
    )
    print()
    print("Batch: use submit_example.py to submit builds from package_installs/<pkg>.yaml.")


if __name__ == "__main__":
    main()
