#!/usr/bin/env python3
"""
Setup script for er-spack-development.

Renders Spack config templates into a per-user config directory and prepares an
environments dir (env manifests, source_cache, build_results, build_stage) plus
an outputs dir (per-env apps/ and modules/), all separate from the git repo
inputs (an er-spack-packages checkout).

The Spack environment is created by writing <envs_dir>/<environment_name>/spack.yaml
directly: Spack treats any directory with a spack.yaml under environments_root as
a managed environment, so no Slurm job is needed at setup time (Singularity is not
available on login nodes).

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

DEFAULT_SIF = "/software/containers/singularity/spack/spack_v1_2_1.sif"
DEFAULT_SPACK_VERSION = "1.2.1"
DEFAULT_SPACK_CONFIG_HOME_PREFIX = ".spack_er_kcl_v"
DEFAULT_ENVIRONMENT_NAME = "arc-ops-env"
DEFAULT_PACKAGES_BRANCH = "develop"

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


def _git_current_branch(repo_dir):
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def main():
    parser = argparse.ArgumentParser(description="Configure er-spack-development environment")
    parser.add_argument(
        "--outputs-dir",
        default=None,
        help="Outputs root: per-env apps/ and modules/ under <outputs-dir>/<environment_name>/. Default: <repo_parent>/../installs",
    )
    parser.add_argument(
        "--envs-dir",
        default=None,
        help="Environments root: <envs-dir>/<environment_name>/spack.yaml plus source_cache/, build_results/, build_stage/, setup_state.yaml. Default: <repo_parent>/environments",
    )
    parser.add_argument(
        "--repo-dir",
        default=None,
        help="er-spack-packages checkout (defaults to <setup.py_dir>/../er-spack-packages).",
    )
    parser.add_argument(
        "--spack-config-home",
        default=None,
        help="Per-user Spack config home (default derived from --spack-version, e.g. $HOME/.spack_er_kcl_v1_2_1).",
    )
    parser.add_argument(
        "--spack-version",
        default=None,
        help="Spack version tag to use (default: 1.2.1). Used mainly for config-home naming.",
    )
    parser.add_argument(
        "--sif-path",
        default=None,
        help=f"SIF image path (default: {DEFAULT_SIF})",
    )
    parser.add_argument(
        "--environment-name",
        default=None,
        help=f"Name of the Spack environment under <envs-dir>/ (default: {DEFAULT_ENVIRONMENT_NAME}).",
    )
    parser.add_argument(
        "--packages-branch",
        default=None,
        help=(
            f"er-spack-packages branch to use (default: {DEFAULT_PACKAGES_BRANCH}). "
            "Recorded in setup_state.yaml and checked against the clone; not checked out for you."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["test", "development"],
        default="development",
        help="test/development affects the printed message (no Slack/integration in this repo).",
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
    home = os.path.expanduser("~")
    default_envs_dir = os.path.join(parent_dir, "environments")
    default_outputs_dir = os.path.abspath(os.path.join(parent_dir, "..", "installs"))
    default_repo_dir = os.path.abspath(os.path.join(script_dir, "..", "er-spack-packages"))

    template_dir = os.path.join(script_dir, "config", "templates")
    if not os.path.isdir(template_dir):
        print(f"Error: template dir not found: {template_dir}", file=sys.stderr)
        sys.exit(1)
    packages_yaml_source = os.path.join(script_dir, "config", "packages.yaml")
    if not os.path.isfile(packages_yaml_source):
        print(f"Error: packages.yaml not found: {packages_yaml_source}", file=sys.stderr)
        sys.exit(1)

    repo_dir = os.path.abspath(os.path.expanduser(args.repo_dir)) if args.repo_dir else default_repo_dir

    local_repo_root = os.path.join(repo_dir, "local_packages", "spack_repo", "kcl")
    if not os.path.isfile(os.path.join(local_repo_root, "repo.yaml")):
        print(
            f"Error: er-spack-packages repository not found at {local_repo_root} "
            "(expected local_packages/spack_repo/kcl/repo.yaml). Clone er-spack-packages "
            "next to this repo (or pass --repo-dir) with an up-to-date checkout.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.envs_dir is None:
        use_default = _prompt_yes_no(
            f"--envs-dir not passed. Use default environments dir '{default_envs_dir}'?",
            default=True,
        )
        envs_dir = (
            default_envs_dir
            if use_default
            else _prompt_path("Environments dir", default_envs_dir, home)
        )
    else:
        envs_dir = os.path.abspath(os.path.expanduser(args.envs_dir))

    if args.outputs_dir is None:
        use_default = _prompt_yes_no(
            f"--outputs-dir not passed. Use default outputs dir '{default_outputs_dir}'?",
            default=True,
        )
        outputs_dir = (
            default_outputs_dir
            if use_default
            else _prompt_path("Outputs dir", default_outputs_dir, home)
        )
    else:
        outputs_dir = os.path.abspath(os.path.expanduser(args.outputs_dir))

    spack_version = _prompt("Spack version", DEFAULT_SPACK_VERSION) if args.spack_version is None else args.spack_version
    sif_path = _prompt("SIF image path", DEFAULT_SIF) if args.sif_path is None else args.sif_path

    default_spack_config_home_abs = os.path.join(
        home, spack_version_to_spack_config_home_basename(spack_version)
    )
    if args.spack_config_home is None:
        spack_config_dir = _prompt_path("Spack config home", default_spack_config_home_abs, home)
    else:
        spack_config_home_arg = os.path.expanduser(args.spack_config_home)
        if os.path.isabs(spack_config_home_arg):
            spack_config_dir = os.path.abspath(spack_config_home_arg)
        else:
            spack_config_dir = os.path.abspath(os.path.join(home, spack_config_home_arg))

    environment_name = (
        args.environment_name
        if args.environment_name is not None
        else _prompt("Spack environment name", DEFAULT_ENVIRONMENT_NAME)
    ).strip()
    if not environment_name:
        environment_name = DEFAULT_ENVIRONMENT_NAME

    packages_branch = (
        args.packages_branch
        if args.packages_branch is not None
        else _prompt("er-spack-packages branch", DEFAULT_PACKAGES_BRANCH)
    ).strip() or DEFAULT_PACKAGES_BRANCH

    source_cache_path = os.path.join(envs_dir, "source_cache")
    build_stage_path = os.path.join(envs_dir, "build_stage")
    build_results_path = os.path.join(envs_dir, "build_results")
    install_prefix = os.path.join(outputs_dir, "install")

    for d in [
        envs_dir,
        source_cache_path,
        build_stage_path,
        build_results_path,
        spack_config_dir,
        install_prefix,
    ]:
        os.makedirs(d, exist_ok=True)

    current_branch = _git_current_branch(repo_dir)
    if current_branch is None:
        print(f"Note: could not determine the current branch of {repo_dir} (not a git checkout?).")
    elif current_branch != packages_branch:
        print(
            f"Warning: {repo_dir} is on branch '{current_branch}' but '{packages_branch}' "
            "was given as the branch to use for builds.",
            file=sys.stderr,
        )

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    ctx = {
        "spack_config_basename": spack_version_to_spack_config_home_basename(spack_version),
        "install_prefix": install_prefix,
        "envs_dir": envs_dir,
        "build_stage_path": build_stage_path,
        "source_cache_path": source_cache_path,
        "reuse": args.reuse,
        "local_packages_path": local_repo_root,
        "builtin_destination": os.path.join(envs_dir, "package_repos", "spack-packages"),
    }

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

    env_dir = os.path.join(envs_dir, environment_name)
    env_spack_yaml = os.path.join(env_dir, "spack.yaml")
    env_install_root = os.path.join(outputs_dir, environment_name)
    if os.path.isfile(env_spack_yaml):
        print(f"Spack environment already exists: {env_spack_yaml}")
    else:
        os.makedirs(env_dir, exist_ok=True)
        env_tpl = env.get_template("spack_env.yaml.j2")
        with open(env_spack_yaml, "w") as f:
            f.write(
                env_tpl.render(
                    environment_name=environment_name,
                    env_install_root=env_install_root,
                    reuse=args.reuse,
                )
            )
        print(f"Wrote {env_spack_yaml}")

    instructions_template_path = os.path.join(script_dir, "instructions.md.j2")
    if not os.path.isfile(instructions_template_path):
        print(f"Error: missing template: {instructions_template_path}", file=sys.stderr)
        sys.exit(1)

    instructions_out_path = os.path.join(parent_dir, "instructions.md")
    setup_state_path = os.path.join(envs_dir, "setup_state.yaml")

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
        environment_name=environment_name,
        repo_dir=repo_dir,
        packages_branch=packages_branch,
        envs_dir=envs_dir,
        outputs_dir=outputs_dir,
        script_dir=script_dir,
        env_manifest_path=env_spack_yaml,
        build_results_dir=build_results_path,
        env_install_root=env_install_root,
        spack_in_container=SPACK_IN_CONTAINER,
    )
    with open(instructions_out_path, "w") as fh:
        fh.write(instructions_txt)
    print(f"Wrote {instructions_out_path}")

    state_yaml_lines = [
        "setup:",
        f"  repo_dir: {_yaml_quote(script_dir)}",
        f"  outputs_dir: {_yaml_quote(outputs_dir)}",
        f"  envs_dir: {_yaml_quote(envs_dir)}",
        f"  spack_version: {_yaml_quote(spack_version)}",
        f"  sif_path: {_yaml_quote(sif_path)}",
        f"  spack_user_config_path: {_yaml_quote(spack_config_dir)}",
        f"  environments_root: {_yaml_quote(envs_dir)}",
        f"  environment_name: {_yaml_quote(environment_name)}",
        f"  packages_repo_path: {_yaml_quote(repo_dir)}",
        f"  packages_branch: {_yaml_quote(packages_branch)}",
        f"  reuse: {args.reuse}",
    ]
    with open(setup_state_path, "w") as fh:
        fh.write("\n".join(state_yaml_lines) + "\n")
    print(f"Wrote {setup_state_path}")

    print()
    print(MODE_MESSAGES[args.mode])
    print("Environment:")
    print(f"  export SPACK_USER_CONFIG_PATH={spack_config_dir}")
    print()
    print("Singularity binds (as used by the batch scripts):")
    for d in [script_dir, repo_dir, envs_dir, outputs_dir, spack_config_dir]:
        print(f"  --bind {d}:{d}")
    print()
    print("Batch steps (each submits a Slurm job; chain with --wait):")
    print(f"  ./spack_concretize.py -e {environment_name}")
    print(f"  ./spack_pkgs_install.py -e {environment_name}")
    print(f"  ./spack_mod_refresh.py -e {environment_name}")
    print()
    print(f"See {instructions_out_path} for a singularity shell command and environment management.")


if __name__ == "__main__":
    main()
