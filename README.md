# create-spack-development

User-cloneable setup for personal Spack builds and for developing packages and environments on the HPC. Spack runs in a Singularity container (default `/software/containers/singularity/spack/spack_v1_2_1.sif`; definition files are in this repo).

Environments are git-managed: each `environments/<name>/spack.yaml` is the Spack environment `<name>`.

## Prerequisites

Python 3 with `jinja2` and `pyyaml` (`pip install jinja2 pyyaml`).

## Setup

```bash
cd /scratch/prj/my_prj/spack/control
git clone <create-spack-development-url>
git clone <create-spack-packages-url>         # setup expects branch develop by default
cd create-spack-development
./setup.py                                      # prompts; Enter accepts the default
./setup.py -y                                   # later re-runs: reuse the saved answers
```

## Environments

```bash
git switch -c my-envs                           # keep your environments on your own branch
./new_env.py my-env --constraint zen3           # blank environment; constraint goes in meta.yaml
./new_env.py my-env --from ../create-spack-environments/environments/bespoke/arc-zen3-cpu   # or copy one
# add specs under specs: in environments/my-env/spack.yaml
git add environments/my-env && git commit -m "my-env: add specs"
```

Rules for `spack.yaml` (checked before every build):

- keep `include: [paths.yaml]` (generated, gitignored; sets the install tree and module root)
- don't set `config: install_tree` or `modules: <set>: roots`

```bash
git add -f environments/my-env/spack.lock       # optional: keep the concretized lock (ignored by default)
```

To promote an environment to `create-spack-environments`, copy `spack.yaml` (and `meta.yaml`) to `environments/bespoke/<name>/` there, remove the `include:` line and add the production `modules: default: roots: tcl:`.

To build one environment against another `create-spack-packages` branch, clone it again and override `repos:` in that `spack.yaml` (a user-specific path, so keep it on your own branch):

```yaml
spack:
  repos:
    local_packages: /scratch/prj/my_prj/spack/control/create-spack-packages-feature/local_packages/spack_repo/kcl
```

## Build

Run from a login node; the scripts submit their own Slurm jobs (don't `sbatch` them).

```bash
./spack_build.py -e my-env                      # concretize -> install -> module refresh, chained
./spack_concretize.py -e my-env                 # single steps: also spack_pkgs_install.py, spack_mod_refresh.py
./spack_build.py -e env-a -e env-b              # several environments (or --all)
./spack_build.py -e my-env -- --ntasks=8 --mem-per-cpu=8192   # extra sbatch options
./spack_build.py -e my-env --dry-run            # print the sbatch commands and job scripts
```

`-e` can be left out when there is only one environment. `--constraint` defaults to `constraint` in `meta.yaml`. Logs and build results (with commits of both repos): `var/build_results/`.

## Shell

```bash
./spack_shell.py -e my-env                      # srun + container shell, environment active
./spack_shell.py -e my-env -- --time=4:00:00    # extra srun options
```

## Modules

```bash
export MODULEPATH=/scratch/prj/my_prj/spack/installs/my-env/modules:${MODULEPATH}
module avail
```

## Setup options

- `--repo-dir PATH`: create-spack-packages clone (default `<repo_parent>/create-spack-packages`)
- `--packages-branch BRANCH`: branch expected in that clone (default `develop`; warns if different)
- `--outputs-dir PATH`: installs and modules go to `<outputs-dir>/<env>/apps` and `.../modules` (default `<repo_parent>/../installs`)
- `--spack-version X.Y.Z`: default `1.2.1`
- `--sif-path PATH`: container image
- `--spack-config-home PATH`: default `${HOME}/.spack_er_kcl_v1_2_1`
- `-y`, `--yes`: no prompts; use the saved (or default) values

## Layout

| What | Where |
|------|-------|
| Environments (tracked) | `environments/<env>/spack.yaml`, optional `meta.yaml` |
| Generated per environment (ignored) | `environments/<env>/paths.yaml`, `spack.lock`, `.spack-env/` |
| Setup state, caches, logs (ignored) | `var/` |
| Generated commands (ignored) | `instructions.md` |
| Installs, modules | `<outputs-dir>/<env>/apps`, `<outputs-dir>/<env>/modules` |
| Spack config | `${HOME}/.spack_er_kcl_v1_2_1/` |
