#!/usr/bin/env python3
"""
Setup script for create-spack-development.

Renders Spack config templates into a per-user config directory and points
Spack's environments_root at this repo's git-managed environments/ dir: each
environments/<name>/spack.yaml is the Spack environment <name>. Writes
var/setup_state.yaml (read by the other scripts), a generated paths.yaml for
every environment (per-env install tree and module root under
<outputs_dir>/<env>/) and instructions.md.

No Slurm job is needed: Spack treats any directory with a spack.yaml under
environments_root as a managed environment (Singularity is not available on
login nodes). Re-run with -y to reuse the saved answers without prompting.

This is intended for non-privileged testing with the Singularity image.
"""

import argparse
import os
import re
import sys

try:
    from er_spack_common import (
        ENVS_DIR,
        REPO_DIR,
        STATE_PATH,
        TEMPLATE_DIR,
        VAR_DIR,
        check_manifest,
        discover_envs,
        git_branch,
        load_setup_state,
        logical_path,
        read_meta,
        template_env,
        write_paths_yaml,
        write_setup_state,
    )
except ModuleNotFoundError as e:
    if e.name != "er_spack_common":
        raise
    sys.exit("Cannot import er_spack_common. Run ./setup.py from the create-spack-development checkout.")

DEFAULT_SIF = "/software/containers/singularity/spack/spack_v1_2_1.sif"
DEFAULT_SPACK_VERSION = "1.2.1"
DEFAULT_SPACK_CONFIG_HOME_PREFIX = ".spack_er_kcl_v"
DEFAULT_PACKAGES_BRANCH = "develop"


def _prompt(text, default):
    resp = input(f"{text} [{default}]: ").strip()
    return resp if resp else default


def _choose(arg_value, label, default, assume_yes):
    """The CLI value if given, else the default (saved or built-in), prompting unless -y."""
    if arg_value is not None:
        return arg_value
    if assume_yes:
        return default
    return _prompt(label, default)


def spack_version_to_spack_config_home_basename(spack_version):
    # Expected format is x.y.z; if it isn't, we still attempt a stable tag.
    m = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)\s*$", spack_version)
    if m:
        major, minor, patch = m.group(1), m.group(2), m.group(3)
        return f"{DEFAULT_SPACK_CONFIG_HOME_PREFIX}{major}_{minor}_{patch}"

    safe = spack_version.strip().replace(".", "_").replace("-", "_")
    return f"{DEFAULT_SPACK_CONFIG_HOME_PREFIX}{safe}"


def _home_relative(path, home):
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(home, path)
    return os.path.normpath(path)


def main():
    parser = argparse.ArgumentParser(
        description="Configure create-spack-development",
        epilog="Relative paths are taken from the current directory (--spack-config-home: from ${HOME}).",
    )
    parser.add_argument(
        "--outputs-dir",
        default=None,
        help="Outputs root: per-env apps/ and modules/ under <outputs-dir>/<env>/. Default: <repo_parent>/../installs",
    )
    parser.add_argument(
        "--repo-dir",
        default=None,
        help="create-spack-packages checkout. Default: <repo_parent>/create-spack-packages",
    )
    parser.add_argument(
        "--packages-branch",
        default=None,
        help=(
            f"create-spack-packages branch to use (default: {DEFAULT_PACKAGES_BRANCH}). "
            "Recorded in var/setup_state.yaml and checked against the clone; not checked out for you."
        ),
    )
    parser.add_argument(
        "--spack-version",
        default=None,
        help=f"Spack version tag (default: {DEFAULT_SPACK_VERSION}). Used mainly for config-home naming.",
    )
    parser.add_argument(
        "--sif-path",
        default=None,
        help=f"SIF image path (default: {DEFAULT_SIF})",
    )
    parser.add_argument(
        "--spack-config-home",
        default=None,
        help="Per-user Spack config home (default derived from --spack-version, e.g. ${HOME}/.spack_er_kcl_v1_2_1).",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Don't prompt: use the values saved by the last run (or the defaults)",
    )
    args = parser.parse_args()

    saved = load_setup_state(required=False) or {}
    parent_dir = os.path.dirname(REPO_DIR)
    home = os.path.expanduser("~")

    packages_yaml_source = os.path.join(REPO_DIR, "config", "packages.yaml")
    for required in (TEMPLATE_DIR, packages_yaml_source):
        if not os.path.exists(required):
            sys.exit(f"Error: not found: {required}")

    packages_repo_dir = logical_path(
        _choose(
            args.repo_dir,
            "create-spack-packages checkout",
            saved.get("packages_repo_path") or os.path.join(parent_dir, "create-spack-packages"),
            args.yes,
        )
    )
    local_repo_root = os.path.join(packages_repo_dir, "local_packages", "spack_repo", "kcl")
    if not os.path.isfile(os.path.join(local_repo_root, "repo.yaml")):
        sys.exit(
            f"Error: create-spack-packages repository not found at {local_repo_root} "
            "(expected local_packages/spack_repo/kcl/repo.yaml). Clone create-spack-packages "
            "next to this repo (or pass --repo-dir) with an up-to-date checkout."
        )

    packages_branch = (
        _choose(
            args.packages_branch,
            "create-spack-packages branch",
            saved.get("packages_branch") or DEFAULT_PACKAGES_BRANCH,
            args.yes,
        ).strip()
        or DEFAULT_PACKAGES_BRANCH
    )

    outputs_dir = logical_path(
        _choose(
            args.outputs_dir,
            "Outputs dir (installs and modules)",
            saved.get("outputs_dir") or os.path.normpath(os.path.join(parent_dir, "..", "installs")),
            args.yes,
        )
    )

    spack_version = _choose(
        args.spack_version,
        "Spack version",
        saved.get("spack_version") or DEFAULT_SPACK_VERSION,
        args.yes,
    ).strip()
    sif_path = _choose(args.sif_path, "SIF image path", saved.get("sif_path") or DEFAULT_SIF, args.yes).strip()

    default_spack_config_home = os.path.join(home, spack_version_to_spack_config_home_basename(spack_version))
    if saved.get("spack_user_config_path") and saved.get("spack_version") == spack_version:
        default_spack_config_home = saved["spack_user_config_path"]
    spack_config_dir = _home_relative(
        _choose(args.spack_config_home, "Spack config home", default_spack_config_home, args.yes),
        home,
    )

    source_cache_path = os.path.join(VAR_DIR, "source_cache")
    build_stage_path = os.path.join(VAR_DIR, "build_stage")
    build_results_path = os.path.join(VAR_DIR, "build_results")
    install_prefix = os.path.join(outputs_dir, "install")

    for d in [
        source_cache_path,
        build_stage_path,
        build_results_path,
        os.path.join(VAR_DIR, "package_repos"),
        os.path.join(VAR_DIR, "shell"),
        spack_config_dir,
        install_prefix,
    ]:
        os.makedirs(d, exist_ok=True)

    current_branch = git_branch(packages_repo_dir)
    if current_branch is None:
        print(f"Note: could not determine the current branch of {packages_repo_dir} (not a git checkout?).")
    elif current_branch != packages_branch:
        print(
            f"Warning: {packages_repo_dir} is on branch '{current_branch}' but '{packages_branch}' "
            "was given as the branch to use for builds.",
            file=sys.stderr,
        )

    env = template_env()
    ctx = {
        "spack_config_basename": spack_version_to_spack_config_home_basename(spack_version),
        "install_prefix": install_prefix,
        "envs_dir": ENVS_DIR,
        "build_stage_path": build_stage_path,
        "source_cache_path": source_cache_path,
        "local_packages_path": local_repo_root,
        "builtin_destination": os.path.join(VAR_DIR, "package_repos", "spack-packages"),
    }
    for name in ["config.yaml", "concretizer.yaml", "modules.yaml", "repos.yaml"]:
        out_path = os.path.join(spack_config_dir, name)
        with open(out_path, "w") as f:
            f.write(env.get_template(f"{name}.j2").render(**ctx))
        print(f"Wrote {out_path}")

    packages_yaml_dest = os.path.join(spack_config_dir, "packages.yaml")
    if os.path.lexists(packages_yaml_dest):
        os.remove(packages_yaml_dest)
    os.symlink(packages_yaml_source, packages_yaml_dest)
    print(f"Linked {packages_yaml_dest} -> {packages_yaml_source}")

    state = {
        "repo_dir": REPO_DIR,
        "outputs_dir": outputs_dir,
        "spack_version": spack_version,
        "sif_path": sif_path,
        "spack_user_config_path": spack_config_dir,
        "packages_repo_path": packages_repo_dir,
        "packages_branch": packages_branch,
    }
    write_setup_state(state)
    print(f"Wrote {STATE_PATH}")

    envs = discover_envs()
    for env_name in envs:
        write_paths_yaml(env_name, state)
        for problem in check_manifest(env_name):
            print(f"Warning: {problem}", file=sys.stderr)

    instructions_path = os.path.join(REPO_DIR, "instructions.md")
    with open(os.path.join(REPO_DIR, "instructions.md.j2")) as fh:
        instructions_txt = env.from_string(fh.read()).render(
            spack_version=spack_version,
            sif_path=sif_path,
            spack_user_config_path=spack_config_dir,
            repo_dir=REPO_DIR,
            packages_repo_dir=packages_repo_dir,
            packages_branch=packages_branch,
            outputs_dir=outputs_dir,
            build_results_dir=build_results_path,
        )
    with open(instructions_path, "w") as fh:
        fh.write(instructions_txt)
    print(f"Wrote {instructions_path}")

    print()
    print("Setup complete.")
    print()
    if envs:
        print("Environments (environments/<name>/spack.yaml):")
        width = max(len(e) for e in envs)
        for env_name in envs:
            constraint = read_meta(env_name).get("constraint")
            suffix = f"constraint: {constraint}" if constraint else "no constraint"
            print(f"  {env_name:<{width}}  ({suffix})")
    else:
        print("No environments under environments/ yet.")
    print()
    example = envs[0] if len(envs) == 1 else "<env>"
    print("Next (run directly; the scripts submit their own Slurm jobs):")
    if envs:
        print(f"  ./spack_build.py -e {example}  # concretize -> install -> module refresh")
        print(f"  ./spack_shell.py -e {example}  # interactive shell, environment active")
    print("  ./new_env.py <name>  # add an environment (--from <dir> to copy one)")
    print(f"See {instructions_path} for more.")


if __name__ == "__main__":
    main()
