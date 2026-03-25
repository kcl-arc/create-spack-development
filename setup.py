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
import re
import subprocess
import sys

try:
    import jinja2
except ImportError:
    print("Error: jinja2 required. pip install jinja2", file=sys.stderr)
    sys.exit(1)

DEFAULT_SIF = "/software/containers/singularity/spack/spack_v1_1_1.sif"
DEFAULT_SPACK_VERSION = "1.1.1"
DEFAULT_SPACK_CONFIG_HOME_PREFIX = ".spack_er_kcl_v"

SPACK_IN_CONTAINER = "/opt/spack/bin/spack"

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


def _prompt(text, default=None):
    suffix = f" [{default}]" if default is not None else ""
    resp = input(f"{text}{suffix}: ").strip()
    return resp if resp else default


def _prompt_yes_no(text, default=True):
    hint = "[Y/n]" if default else "[y/N]"
    resp = input(f"{text} {hint}: ").strip().lower()
    if not resp:
        return default
    if resp in ("y", "yes"):
        return True
    if resp in ("n", "no"):
        return False
    print("Please answer yes or no.", file=sys.stderr)
    return _prompt_yes_no(text, default=default)


def _prompt_optional_env_name(text):
    resp = input(f"{text} (blank = do not create/use): ").strip()
    return resp


def spack_version_to_spack_config_home_basename(spack_version):
    # Expected format is x.y.z; if it isn't, we still attempt a stable tag.
    m = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)\s*$", spack_version)
    if m:
        major, minor, patch = m.group(1), m.group(2), m.group(3)
        return f"{DEFAULT_SPACK_CONFIG_HOME_PREFIX}{major}_{minor}_{patch}"

    safe = spack_version.strip().replace(".", "_").replace("-", "_")
    return f"{DEFAULT_SPACK_CONFIG_HOME_PREFIX}{safe}"


def _prompt_path(text, default_abs, home):
    resp = input(f"{text} [{default_abs}]: ").strip()
    if not resp:
        return default_abs
    resp = os.path.expanduser(resp)
    if not os.path.isabs(resp):
        resp = os.path.join(home, resp)
    return os.path.abspath(resp)


def _yaml_quote(value):
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f"\"{text}\""


def main():
    parser = argparse.ArgumentParser(description="Configure er-spack-development environment")
    parser.add_argument(
        "--outputs-dir",
        default=None,
        help="Where outputs go (install/, source_cache/, build_results/). Default: <repo_parent>/spackages",
    )
    parser.add_argument(
        "--repo-dir",
        default=None,
        help="Repo inputs location (defaults to <setup.py_dir>/../er-spack-packages).",
    )
    parser.add_argument(
        "--spack-config-home",
        default=None,
        help="Per-user Spack config home (default derived from --spack-version, e.g. $HOME/.spack_er_kcl_v1_1_1).",
    )
    parser.add_argument(
        "--spack-config-dir",
        default=None,
        help="Alias for --spack-config-home (kept for compatibility).",
    )
    parser.add_argument(
        "--spack-version",
        default=None,
        help="Spack version tag to use (default: 1.1.1). Used mainly for config-home naming.",
    )
    parser.add_argument(
        "--mode",
        choices=["test", "development"],
        default="development",
        help="test/development affects the printed message (no Slack/integration in this repo).",
    )
    parser.add_argument(
        "--sif-path",
        default=None,
        help=f"SIF image path (default: {DEFAULT_SIF})",
    )
    parser.add_argument(
        "--environment-name",
        default=None,
        help="Name of Spack environment under outputs-dir/environments/ (blank disables env creation/usage).",
    )
    parser.add_argument(
        "--reuse",
        choices=["true", "false"],
        default="false",
        help="Spack concretizer reuse (default: false)",
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
    default_outputs_dir = os.path.join(parent_dir, "spackages")
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

    if args.outputs_dir is None:
        use_default_outputs = _prompt_yes_no(
            f"--outputs-dir not passed. Use default outputs dir '{default_outputs_dir}'?",
            default=True,
        )
        if not use_default_outputs:
            outputs_dir = _prompt_path("Outputs dir", default_outputs_dir, home=os.path.expanduser("~"))
        else:
            outputs_dir = os.path.abspath(default_outputs_dir)
    else:
        outputs_dir = os.path.abspath(os.path.expanduser(args.outputs_dir))
    os.makedirs(outputs_dir, exist_ok=True)

    home = os.path.expanduser("~")
    spack_version = _prompt("Spack version", DEFAULT_SPACK_VERSION) if args.spack_version is None else args.spack_version
    sif_path = _prompt("SIF image path", DEFAULT_SIF) if args.sif_path is None else args.sif_path

    default_spack_config_home_basename = spack_version_to_spack_config_home_basename(spack_version)
    default_spack_config_home_abs = os.path.join(home, default_spack_config_home_basename)

    spack_config_home_arg = args.spack_config_home or args.spack_config_dir
    if spack_config_home_arg is None:
        spack_config_dir = _prompt_path("Spack config home", default_spack_config_home_abs, home)
    else:
        spack_config_home_arg = os.path.expanduser(spack_config_home_arg)
        if os.path.isabs(spack_config_home_arg):
            spack_config_dir = os.path.abspath(spack_config_home_arg)
        else:
            spack_config_dir = os.path.abspath(os.path.join(home, spack_config_home_arg))

    environment_name = ""
    if args.environment_name is None:
        environment_name = _prompt_optional_env_name("Name of a Spack environment")
    else:
        environment_name = args.environment_name.strip()

    environment_root = os.path.join(outputs_dir, "environments")
    os.makedirs(environment_root, exist_ok=True)

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
        "environment_root": environment_root,
        "sif_path": sif_path,
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

    # Create the Spack environment if requested.
    if environment_name:
        env_dir = os.path.join(environment_root, environment_name)
        env_spack_yaml = os.path.join(env_dir, "spack.yaml")
        if os.path.isfile(env_spack_yaml):
            print(f"Spack environment already exists: {env_spack_yaml}")
        else:
            cmd = [
                "singularity",
                "exec",
                "--bind",
                f"{script_dir}:{script_dir}",
                "--bind",
                f"{repo_dir}:{repo_dir}",
                "--bind",
                f"{outputs_dir}:{outputs_dir}",
                "--bind",
                f"{spack_config_dir}:{spack_config_dir}",
                sif_path,
                "sh",
                "-c",
                f"export SPACK_USER_CONFIG_PATH='{spack_config_dir}'; {SPACK_IN_CONTAINER} env create '{environment_name}'",
            ]
            print("Creating Spack environment inside container...")
            subprocess.run(cmd, check=True)

    # Generate instructions.md from a template in the repo root.
    instructions_template_path = os.path.join(script_dir, "instructions.md.j2")
    if not os.path.isfile(instructions_template_path):
        print(f"Error: missing template: {instructions_template_path}", file=sys.stderr)
        sys.exit(1)

    instructions_out_path = os.path.join(parent_dir, "instructions.md")
    setup_state_path = os.path.join(parent_dir, "setup_state.yaml")

    instr_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(script_dir),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    instructions_tpl = instr_env.get_template("instructions.md.j2")
    instructions_txt = instructions_tpl.render(
        spack_version=spack_version,
        sif_path=sif_path,
        spack_user_config_path=spack_config_dir,
        environment_root=environment_root,
        environment_name=environment_name,
        repo_dir=repo_dir,
        outputs_dir=outputs_dir,
        script_dir=script_dir,
        spack_in_container=SPACK_IN_CONTAINER,
        setup_state_path=setup_state_path,
        use_spack_environment=bool(environment_name),
    )
    with open(instructions_out_path, "w") as fh:
        fh.write(instructions_txt)
    print(f"Wrote {instructions_out_path}")

    state_yaml_lines = [
        "setup:",
        f"  repo_dir: {_yaml_quote(script_dir)}",
        f"  outputs_dir: {_yaml_quote(outputs_dir)}",
        f"  spack_version: {_yaml_quote(spack_version)}",
        f"  sif_path: {_yaml_quote(sif_path)}",
        f"  spack_user_config_path: {_yaml_quote(spack_config_dir)}",
        f"  environments_root: {_yaml_quote(environment_root)}",
        f"  use_spack_environment: {'true' if environment_name else 'false'}",
        f"  environment_name: {_yaml_quote(environment_name)}",
    ]
    with open(setup_state_path, "w") as fh:
        fh.write("\n".join(state_yaml_lines) + "\n")
    print(f"Wrote {setup_state_path}")

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
    env_flag = f"-e {environment_name} " if environment_name else ""
    print(
        f"  singularity exec --bind {script_dir}:{script_dir} --bind {repo_dir}:{repo_dir} --bind {outputs_dir}:{outputs_dir} "
        f"--bind {spack_config_dir}:{spack_config_dir} {sif_path} {SPACK_IN_CONTAINER} {env_flag}install <spec>"
    )
    print()
    print("Batch: use spack_install.py to submit builds from package_installs/<pkg>.yaml.")


if __name__ == "__main__":
    main()
