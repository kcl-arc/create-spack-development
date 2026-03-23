#!/usr/bin/env python3
"""
Submit helper for er-spack-development.

Reads package_installs/<package>.yaml and submits one or more Slurm jobs
based on versions + flags defined there.
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
import time

try:
    import jinja2
    import yaml
except ImportError:
    print("Error: jinja2 and pyyaml are required. pip install jinja2 pyyaml", file=sys.stderr)
    sys.exit(1)

DEFAULT_SIF = "/software/containers/singularity/spack/spack_v1_1_1.sif"
DEFAULT_PARTITION_CPU = "interruptible_cpu"
DEFAULT_PARTITION_GPU = "interruptible_gpu"
DEFAULT_SPACK_CONFIG_HOME = ".spack_er_kcl_v1_1_1"
DEFAULT_SLURM_ARGS = "#SBATCH --ntasks=4\n#SBATCH --mem-per-cpu=4096"


def _load_yaml(path):
    with open(path) as fh:
        return yaml.safe_load(fh)


def infer_arch_from_host():
    """
    Infer spack target arch (zen2/zen4) from host CPU model.
    Raises SystemExit if we cannot confidently infer.
    """
    model_text = ""
    try:
        with open("/proc/cpuinfo") as fh:
            model_text = fh.read()
    except Exception:
        model_text = ""

    # Common identifiers for AMD Zen generations on HPC systems.
    haystack = model_text.lower()
    if re.search(r"zen\s*4|epyc\s*9|genoa|bergamo", haystack):
        return "zen4"
    if re.search(r"zen\s*2|epyc\s*7|rome", haystack):
        return "zen2"

    # Fallback to lscpu output if available.
    try:
        proc = subprocess.run(["/usr/bin/lscpu"], capture_output=True, text=True, check=False)
        haystack = (proc.stdout or "").lower() + " " + (proc.stderr or "").lower()
        if re.search(r"zen\s*4|epyc\s*9|genoa|bergamo", haystack):
            return "zen4"
        if re.search(r"zen\s*2|epyc\s*7|rome", haystack):
            return "zen2"
    except Exception:
        pass

    raise SystemExit(
        "Could not infer --arch from host. Please pass --arch zen2 or --arch zen4."
    )


def main():
    parser = argparse.ArgumentParser(description="Submit spack jobs from package_installs/<pkg>.yaml")
    parser.add_argument("--outputs-dir", required=True, help="Outputs dir created by setup.py")
    parser.add_argument("--repo-dir", default=None, help="Repo inputs dir (defaults to this script's directory)")
    parser.add_argument("--package", required=True, help="Package name, matching package_installs/<package>.yaml")
    parser.add_argument("--version", default=None, help="Package version key from the YAML (if omitted, inferred when unique)")
    parser.add_argument("--arch", default=None, help="Target arch: zen2 or zen4 (if omitted, inferred from host)")
    parser.add_argument("--extra-flags", default="", help="Extra spec flags appended to YAML flags (optional)")
    parser.add_argument("--slurm-args", default=DEFAULT_SLURM_ARGS, help="Base SBATCH directives")
    parser.add_argument("--sif-path", default=DEFAULT_SIF, help="SIF image path")
    parser.add_argument(
        "--spack-config-dir",
        default=None,
        help="SPACK_USER_CONFIG_PATH (default: $HOME/.spack_er_kcl_v1_1_1)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print job script(s), do not sbatch")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.abspath(args.repo_dir) if args.repo_dir else script_dir

    outputs_dir = os.path.abspath(os.path.expanduser(args.outputs_dir))
    build_results_dir = os.path.join(outputs_dir, "build_results")
    os.makedirs(build_results_dir, exist_ok=True)

    home = os.path.expanduser("~")
    spack_config_dir = (
        os.path.abspath(os.path.expanduser(args.spack_config_dir))
        if args.spack_config_dir
        else os.path.join(home, DEFAULT_SPACK_CONFIG_HOME)
    )

    pkg_yaml = os.path.join(repo_dir, "package_installs", f"{args.package}.yaml")
    if not os.path.exists(pkg_yaml):
        raise SystemExit(f"Cannot find {pkg_yaml}")

    data = _load_yaml(pkg_yaml) or {}
    versions = data.get("versions")
    if not isinstance(versions, dict) or not versions:
        raise SystemExit(f"{pkg_yaml} must contain a non-empty top-level 'versions' mapping")

    # Choose version(s)
    if args.version:
        if args.version not in versions:
            raise SystemExit(f"Version '{args.version}' not found in {pkg_yaml}. Available: {', '.join(sorted(versions.keys()))}")
        version_keys = [args.version]
    else:
        if len(versions) != 1:
            raise SystemExit(
                f"--version not provided and multiple versions exist in {pkg_yaml}: {', '.join(sorted(versions.keys()))}. "
                "Pass --version to disambiguate."
            )
        version_keys = [next(iter(versions.keys()))]

    # Resolve arch constraint
    host_arch = args.arch or infer_arch_from_host()
    yaml_archs = data.get("archs")
    if yaml_archs is not None:
        if not isinstance(yaml_archs, list) or not yaml_archs:
            raise SystemExit(f"{pkg_yaml} has invalid 'archs' (expected non-empty list) ")
        if host_arch not in yaml_archs:
            raise SystemExit(f"Resolved arch '{host_arch}' is not listed in YAML archs: {yaml_archs}")

    # GPU aware partition / SBATCH gres
    gpus = data.get("gpus") or 0
    if gpus and not isinstance(gpus, int):
        raise SystemExit(f"{pkg_yaml} has 'gpus' but it is not an integer")

    partition = DEFAULT_PARTITION_GPU if gpus else DEFAULT_PARTITION_CPU
    slurm_args = args.slurm_args or ""
    if gpus:
        gres_line = f"#SBATCH --gres gpu:{gpus}"
        if gres_line not in slurm_args:
            slurm_args = slurm_args.rstrip() + "\n" + gres_line + "\n"

    job_template_path = os.path.join(repo_dir, "slurm_job.j2")
    with open(job_template_path) as fh:
        tpl = jinja2.Template(fh.read())

    submitted_any = False
    for version in version_keys:
        version_flags_list = versions.get(version)
        if not isinstance(version_flags_list, list):
            raise SystemExit(f"{pkg_yaml}['versions']['{version}'] must be a list of flag strings")

        for flags_entry in version_flags_list:
            flags_entry = "" if flags_entry is None else str(flags_entry)
            full_flags = flags_entry.strip()
            if args.extra_flags:
                if full_flags:
                    full_flags = full_flags + " " + args.extra_flags.strip()
                else:
                    full_flags = args.extra_flags.strip()

            # Unique build name per flags variant
            seed = f"{args.package}:{version}:{host_arch}:{full_flags}"
            digest = hashlib.sha256(seed.encode()).hexdigest()[:10]
            build_name = f"{args.package}_{version}_{host_arch}_{digest}"

            output_file = os.path.join(build_results_dir, f"build_{build_name}.out")
            job_path = os.path.join(build_results_dir, f"{build_name}.sh")

            ctx = {
                "partition": partition,
                "slurm_args": slurm_args,
                "package": args.package,
                "version": version,
                "arch": host_arch,
                "flags": full_flags,
                "repo_dir": repo_dir,
                "outputs_dir": outputs_dir,
                "spack_user_config_path": spack_config_dir,
                "build_name": build_name,
                "build_results_dir": build_results_dir,
                "output_file": output_file,
                "sif_path": args.sif_path,
                "spack_in_container": "/opt/spack/bin/spack",
            }

            script = tpl.render(**ctx)
            if args.dry_run:
                print(script)
                continue

            with open(job_path, "w") as fh:
                fh.write(script)

            result = subprocess.run(
                ["sbatch", "--parsable", "--output", output_file, "--constraint", host_arch, job_path],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(result.stderr, file=sys.stderr)
                raise SystemExit(1)

            submitted_any = True
            print(f"Submitted {build_name}: {result.stdout.strip()}")

    if not submitted_any and args.dry_run:
        print("Dry run completed (no sbatch submission).")


if __name__ == "__main__":
    main()
