#!/usr/bin/env python3
"""
Shared helpers for the create-spack-development scripts: setup.py, new_env.py,
spack_build.py, spack_shell.py and the single-step scripts (spack_concretize.py,
spack_pkgs_install.py, spack_mod_refresh.py).

Environments are the directories under environments/ that hold a spack.yaml.
Each manifest includes a generated, gitignored paths.yaml that points its
install tree and module root at <outputs_dir>/<env>/. setup.py records paths in
var/setup_state.yaml; the build scripts read it, render slurm_env_step.j2 and
submit it with sbatch (Singularity runs on compute nodes only).

Paths are kept in their logical form (e.g. /scratch/prj/...) rather than the
form a symlink resolves to (e.g. /cephfs/...), so binds, install prefixes,
RPATHs and modulefiles all carry the readable path.
"""

import argparse
import datetime
import os
import re
import shlex
import subprocess
import sys

try:
    import jinja2
    import yaml
except ImportError:
    print("Error: jinja2 and pyyaml are required. pip install jinja2 pyyaml", file=sys.stderr)
    sys.exit(1)

DEFAULT_PARTITION = "interruptible_cpu"
SPACK_IN_CONTAINER = "/opt/spack/bin/spack"
PATHS_FILE = "paths.yaml"
ENV_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
STATE_KEYS = (
    "repo_dir",
    "outputs_dir",
    "spack_version",
    "sif_path",
    "spack_user_config_path",
    "packages_repo_path",
    "packages_branch",
)

STEPS = {
    "concretize": {
        "title": "Concretize",
        "spack_args": "concretize -f",
        "compiler_check": True,
    },
    "install": {
        "title": "Install",
        "spack_args": "install --yes-to-all -p ${INSTALL_CONCURRENT_PACKAGES} -j ${INSTALL_JOBS}",
        "compiler_check": True,
    },
    "mod_refresh": {
        "title": "Module refresh",
        "spack_args": "module tcl refresh -y",
        "compiler_check": False,
    },
}
STEP_ORDER = ["concretize", "install", "mod_refresh"]


def _logical_cwd():
    # os.getcwd() returns the resolved path (e.g. /cephfs/...) even when the
    # shell reached the directory through a symlink; $PWD keeps /scratch/...
    cwd = os.getcwd()
    pwd = os.environ.get("PWD")
    if pwd and os.path.isabs(pwd) and _samefile(pwd, cwd):
        return pwd
    return cwd


def _samefile(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def logical_path(path):
    """Absolute, normalised path with symlinks left unresolved."""
    path = os.path.expanduser(str(path))
    if not os.path.isabs(path):
        path = os.path.join(_logical_cwd(), path)
    return os.path.normpath(path)


def _find_repo_dir():
    # __file__ is built from os.getcwd(), so prefer the script path as typed.
    here = os.path.dirname(os.path.abspath(__file__))
    if sys.argv and sys.argv[0]:
        candidate = os.path.dirname(logical_path(sys.argv[0]))
        if _samefile(candidate, here):
            return candidate
    return here


REPO_DIR = _find_repo_dir()
ENVS_DIR = os.path.join(REPO_DIR, "environments")
VAR_DIR = os.path.join(REPO_DIR, "var")
STATE_PATH = os.path.join(VAR_DIR, "setup_state.yaml")
TEMPLATE_DIR = os.path.join(REPO_DIR, "config", "templates")


def quote_cmd(cmd):
    return " ".join(shlex.quote(str(c)) for c in cmd)


def template_env():
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


# --- setup state -------------------------------------------------------------


def read_setup_state():
    """var/setup_state.yaml for this checkout as a dict, or None."""
    if not os.path.isfile(STATE_PATH):
        return None
    try:
        with open(STATE_PATH) as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError:
        return None
    setup = data.get("setup") if isinstance(data, dict) else None
    if not isinstance(setup, dict):
        return None
    if not setup.get("repo_dir") or not _samefile(setup["repo_dir"], REPO_DIR):
        return None
    return setup


def load_setup_state(required=True):
    """Validated setup state plus derived var/ paths; exits (or returns None) if setup.py hasn't run."""
    setup = read_setup_state()
    missing = [k for k in STATE_KEYS if not (setup or {}).get(k)]
    if setup is None or missing:
        if not required:
            return None
        sys.exit(f"No usable {STATE_PATH} for this checkout. Run ./setup.py first.")
    var_dir = os.path.join(setup["repo_dir"], "var")
    setup["var_dir"] = var_dir
    setup["build_results_dir"] = os.path.join(var_dir, "build_results")
    return setup


def write_setup_state(state):
    os.makedirs(VAR_DIR, exist_ok=True)
    with open(STATE_PATH, "w") as fh:
        fh.write("# Written by setup.py; re-run ./setup.py (or ./setup.py -y) to change.\n")
        yaml.safe_dump({"setup": {k: state[k] for k in STATE_KEYS}}, fh, default_flow_style=False, sort_keys=False)


def container_binds(state):
    """Host paths bound at the same path inside the container."""
    paths = [
        state["repo_dir"],
        state["packages_repo_path"],
        state["outputs_dir"],
        state["spack_user_config_path"],
    ]
    return list(dict.fromkeys(paths))


# --- environments ------------------------------------------------------------


def manifest_path(env):
    return os.path.join(ENVS_DIR, env, "spack.yaml")


def discover_envs():
    """Names of the directories under environments/ that hold a spack.yaml."""
    names = []
    if not os.path.isdir(ENVS_DIR):
        return names
    for entry in sorted(os.listdir(ENVS_DIR)):
        if entry.startswith(".") or not os.path.isdir(os.path.join(ENVS_DIR, entry)):
            continue
        if not os.path.isfile(manifest_path(entry)):
            print(f"Note: skipping environments/{entry}/ (no spack.yaml)", file=sys.stderr)
            continue
        if not ENV_NAME_RE.fullmatch(entry):
            print(
                f"Note: skipping environments/{entry}/ (names may use letters, digits, '_', '.', '-')",
                file=sys.stderr,
            )
            continue
        names.append(entry)
    return names


def read_meta(env):
    """Optional environments/<env>/meta.yaml (same schema as bespoke environments)."""
    path = os.path.join(ENVS_DIR, env, "meta.yaml")
    if not os.path.isfile(path):
        return {}
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        sys.exit(f"environments/{env}/meta.yaml: expected a mapping, e.g. 'constraint: zen3'")
    return data


def includes_paths_yaml(spack):
    """True if a manifest's spack: mapping lists paths.yaml under include:."""
    include = spack.get("include") or []
    entries = include if isinstance(include, list) else [include]
    entries = [e.get("path") if isinstance(e, dict) else e for e in entries]
    return PATHS_FILE in [os.path.normpath(str(e)) for e in entries if e]


def check_manifest(env):
    """Problems that stop paths.yaml from applying, each with the fix; [] if none."""
    rel = f"environments/{env}/spack.yaml"
    try:
        with open(manifest_path(env)) as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as e:
        return [f"{rel}: not valid YAML ({e})"]
    spack = data.get("spack") if isinstance(data, dict) else None
    if not isinstance(spack, dict):
        return [f"{rel}: no top-level 'spack:' mapping"]

    problems = []
    if not includes_paths_yaml(spack):
        problems.append(
            f"{rel}: add 'include: [{PATHS_FILE}]' under 'spack:' "
            "(it sets this environment's install tree and module root)"
        )
    config = spack.get("config")
    if isinstance(config, dict) and "install_tree" in config:
        problems.append(f"{rel}: remove 'config: install_tree:' (it overrides {PATHS_FILE})")
    modules = spack.get("modules")
    if isinstance(modules, dict):
        for set_name, settings in modules.items():
            if isinstance(settings, dict) and "roots" in settings:
                problems.append(f"{rel}: remove 'modules: {set_name}: roots:' (it overrides {PATHS_FILE})")
    return problems


def write_paths_yaml(env, state):
    """(Re)write environments/<env>/paths.yaml from the setup state."""
    text = template_env().get_template("paths.yaml.j2").render(
        environment_name=env,
        env_install_root=os.path.join(state["outputs_dir"], env),
    )
    path = os.path.join(ENVS_DIR, env, PATHS_FILE)
    try:
        with open(path) as fh:
            if fh.read() == text:
                return
    except FileNotFoundError:
        pass
    with open(path, "w") as fh:
        fh.write(text)


def prepare_envs(envs, state, write=True):
    """Exit on manifest problems; otherwise refresh each paths.yaml."""
    failed = False
    for env in envs:
        problems = check_manifest(env)
        for problem in problems:
            print(f"Error: {problem}", file=sys.stderr)
        failed = failed or bool(problems)
        if not problems and write:
            write_paths_yaml(env, state)
    if failed:
        sys.exit(1)


def constraint_for(env, args):
    """--constraint if given ('' for none), else 'constraint' from meta.yaml."""
    if args.constraint is not None:
        return args.constraint or None
    return read_meta(env).get("constraint") or None


def _env_choice(available):
    if not available:
        return "No environments under environments/ yet; create one with ./new_env.py <name>."
    return "Environments: " + ", ".join(available)


def resolve_envs(args):
    """Environments for -e (repeatable) / --all; the only one if neither is given."""
    available = discover_envs()
    if args.all:
        if args.envs:
            sys.exit("Use -e or --all, not both.")
        if not available:
            sys.exit(_env_choice(available))
        return available
    if not args.envs:
        if len(available) == 1:
            return available
        sys.exit("Pass -e <env> (repeatable) or --all. " + _env_choice(available))
    names = list(dict.fromkeys(args.envs))
    unknown = [n for n in names if n not in available]
    if unknown:
        sys.exit(f"Unknown environment: {', '.join(unknown)}. " + _env_choice(available))
    return names


def resolve_env(args):
    """The single environment for -e; the only one if -e is omitted."""
    available = discover_envs()
    if args.env is None:
        if len(available) == 1:
            return available[0]
        sys.exit("Pass -e <env>. " + _env_choice(available))
    if args.env not in available:
        sys.exit(f"Unknown environment: {args.env}. " + _env_choice(available))
    return args.env


# --- command line ------------------------------------------------------------


def _base_parser(description, passthrough, example):
    parser = argparse.ArgumentParser(
        description=description,
        epilog=f"Arguments after '--' are passed to {passthrough}, e.g. -- {example}",
    )
    parser.add_argument(
        "--partition",
        default=DEFAULT_PARTITION,
        help=f"Slurm partition (default: {DEFAULT_PARTITION})",
    )
    parser.add_argument(
        "--constraint",
        default=None,
        help="Slurm --constraint (default: 'constraint' in the environment's meta.yaml; '' for none)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=f"Print the {passthrough} command (and job script) instead of running it",
    )
    return parser


def build_step_parser(description):
    parser = _base_parser(description, "sbatch", "--ntasks=8 --mem-per-cpu=8192")
    parser.add_argument(
        "-e",
        "--environment-name",
        dest="envs",
        action="append",
        metavar="ENV",
        help="Environment under environments/ (repeatable; optional when there is only one)",
    )
    parser.add_argument("--all", action="store_true", help="Every environment under environments/")
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for each environment's last job to finish (sbatch --wait); environments then run one after another",
    )
    return parser


def build_shell_parser(description):
    parser = _base_parser(description, "srun", "--cpus-per-task=8 --time=4:00:00")
    parser.add_argument(
        "-e",
        "--environment-name",
        dest="env",
        metavar="ENV",
        help="Environment under environments/ (optional when there is only one)",
    )
    return parser


def parse_args(parser, argv=None):
    """Parse the script's own options; anything after '--' goes to args.passthrough."""
    argv = list(sys.argv[1:] if argv is None else argv)
    passthrough = []
    if "--" in argv:
        i = argv.index("--")
        argv, passthrough = argv[:i], argv[i + 1:]
    args = parser.parse_args(argv)
    args.passthrough = passthrough
    return args


# --- provenance --------------------------------------------------------------


def _git(repo, *args):
    try:
        result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def git_branch(repo):
    return _git(repo, "branch", "--show-current") or None


def git_info(repo, pathspec=None):
    """Commit, branch and dirty flag (YAML true/false/null) for build results."""
    status_args = ["status", "--porcelain"] + (["--", pathspec] if pathspec else [])
    status = _git(repo, *status_args)
    return {
        "commit": _git(repo, "rev-parse", "HEAD") or "unknown",
        "branch": git_branch(repo) or "unknown",
        "dirty": "null" if status is None else ("true" if status else "false"),
    }


# --- batch submission --------------------------------------------------------


def submit_step(args, state, env, step_id, dependency=None, wait=False):
    """Render slurm_env_step.j2 for one step of one environment and sbatch it.

    Returns the job id (a placeholder with --dry-run).
    """
    step = STEPS[step_id]
    build_results_dir = state["build_results_dir"]
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    build_name = f"{step_id}_{env}_{stamp}"
    output_file = os.path.join(build_results_dir, f"{build_name}.out")
    job_path = os.path.join(build_results_dir, f"{build_name}.sh")

    with open(os.path.join(REPO_DIR, "slurm_env_step.j2")) as fh:
        tpl = jinja2.Template(fh.read(), trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    script = tpl.render(
        step_id=step_id,
        step_title=step["title"],
        spack_step_args=step["spack_args"],
        compiler_check=step["compiler_check"],
        partition=args.partition,
        environment_name=env,
        dev_repo_dir=state["repo_dir"],
        binds=container_binds(state),
        spack_user_config_path=state["spack_user_config_path"],
        sif_path=state["sif_path"],
        spack_in_container=SPACK_IN_CONTAINER,
        build_name=build_name,
        build_results_dir=build_results_dir,
        output_file=output_file,
        dev_git=git_info(state["repo_dir"], f"environments/{env}"),
        packages_git=git_info(state["packages_repo_path"]),
    )

    sbatch_cmd = ["sbatch", "--parsable", "--output", output_file]
    constraint = constraint_for(env, args)
    if constraint:
        sbatch_cmd += ["--constraint", constraint]
    if dependency:
        # A failed step cancels the rest of the chain instead of leaving it pending.
        sbatch_cmd += [f"--dependency=afterok:{dependency}", "--kill-on-invalid-dep=yes"]
    if wait:
        sbatch_cmd.append("--wait")
    sbatch_cmd += args.passthrough
    sbatch_cmd.append(job_path)

    if args.dry_run:
        print(f"# --- {step['title']} for {env} ---")
        print("$ " + quote_cmd(sbatch_cmd))
        print(script)
        return f"<{step_id}_job_id>"

    os.makedirs(build_results_dir, exist_ok=True)
    with open(job_path, "w") as fh:
        fh.write(script)
    os.chmod(job_path, 0o755)

    if wait:
        print(f"Submitting {build_name} and waiting for it to finish...", flush=True)
    try:
        result = subprocess.run(sbatch_cmd, capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit("sbatch not found: run this on a cluster login node.")
    job_id = result.stdout.strip().split(";")[0]
    if result.returncode != 0:
        print(result.stderr, end="", file=sys.stderr)
        if wait and job_id:
            sys.exit(f"Job {job_id} ({build_name}) did not complete successfully. Output: {output_file}")
        sys.exit(1)
    print(f"Submitted {build_name}: job {job_id}")
    print(f"  output: {output_file}")
    return job_id


def run_steps(args, step_ids):
    """Submit step_ids for each selected environment, each step after the previous succeeds."""
    state = load_setup_state()
    envs = resolve_envs(args)
    prepare_envs(envs, state, write=not args.dry_run)
    for env in envs:
        job_id = None
        for i, step_id in enumerate(step_ids):
            last = i == len(step_ids) - 1
            job_id = submit_step(args, state, env, step_id, dependency=job_id, wait=args.wait and last)
