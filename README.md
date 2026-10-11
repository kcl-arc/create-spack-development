# create-spack-development

User-cloneable Spack environment for creating personal builds or developing packages and environments. Uses a Singularity container at `/software/containers/singularity/spack/spack_v1_2_1.sif` as default, others can be specified during setup.

Singularity definition files are included in the root of this repository.

- **Personal builds**: Maintain your own Spack package recipes and builds on the HPC
- **Environments**: Use the environment created by setup to create a named Spack environment that can be, e.g. containerised.

Package specs are entered through Spack environments (see below). The `package_installs/<package>.yaml` format is no longer used.

## Prerequisites

- Python 3 with jinja2 (`pip install jinja2`)
- pyyaml (`pip install pyyaml`) for the batch scripts

## Quick start

1. **Clone** (or copy) this repo to a project location, e.g.:
   ```bash
   git clone <repo-url> /scratch/prj/my_prj/spack/control/create-spack-development
   ```

2. **Clone create-spack-packages** next to it and check out the branch you will build against (the default expected by setup is `develop`):
   ```bash
   git clone <create-spack-packages-url> /scratch/prj/my_prj/spack/control/create-spack-packages
   cd /scratch/prj/my_prj/spack/control/create-spack-packages && git checkout develop
   ```

3. **Run setup** (writes config to `${HOME}/.spack_er_kcl_v1_2_1` by default and creates a default environment `arc-ops-env`):
   ```bash
   cd /scratch/prj/my_prj/spack/control/create-spack-development
   ./setup.py
   ```
   If you do not pass `--envs-dir`, `setup.py` defaults to `<repo_parent>/environments/` (e.g. `/scratch/prj/my_prj/spack/control/environments`) and asks for confirmation.
   If you do not pass `--environment-name`, `setup.py` defaults to `arc-ops-env` and asks for confirmation.
   `setup.py` requests the branch name to be used for the `create-spack-packages` repo (default `develop`) and warns if your clone is checked out to a different branch (it does not check out for you).
   If you do not pass `--outputs-dir`, `setup.py` defaults to `<repo_parent>/../installs/` (e.g. `/scratch/prj/my_prj/spack/installs/`) and asks for confirmation.

4. **Add specs** to the environment: edit `<envs_dir>/arc-ops-env/spack.yaml` (see the minimal example below) or copy a manifest from `create-spack-environments`.

5. **Batch submit** (each step submits one Slurm job; defaults to `arc-ops-env`, add `-e <env-name>` for another):
   ```bash
   ./spack_concretize.py                  # spack -e arc-ops-env concretize -f
   ./spack_pkgs_install.py                # spack -e arc-ops-env install
   ./spack_mod_refresh.py                 # spack -e arc-ops-env module tcl refresh -y
   ```
   Chain the steps in order with `--wait`:
   ```bash
   ./spack_concretize.py --wait && ./spack_pkgs_install.py --wait && ./spack_mod_refresh.py
   ```

## Minimal environment example

`setup.py` creates the environment empty. Add root specs under `specs:` in `<envs_dir>/<env-name>/spack.yaml`:

```yaml
spack:
  specs:
  - zlib@1.3
  view: false
  concretizer:
    unify: false
    reuse: false
```

The rendered manifest already carries the per-env install tree (`<outputs_dir>/<env-name>/apps`) and module root (`<outputs_dir>/<env-name>/modules`); you normally only edit `specs:`.

For complete examples (per-arch targets, providers, CUDA), see the manifests in [create-spack-environments](https://github.com/kcl-eresearch/create-spack-environments) (`environments/bespoke/`, `environments/generated/`).

## Directory layout

| Purpose | Location |
|---------|----------|
| Spack config | `${HOME}/.spack_er_kcl_v1_2_1/` (written by setup) |
| Repo clone | Your choice (e.g. `/scratch/prj/my_prj/spack/control/create-spack-development`) |
| local_packages | `<repo_parent>/create-spack-packages/local_packages/spack_repo/kcl/packages/<pkg>/package.py` |
| Environment manifests | `<envs_dir>/<environment_name>/spack.yaml` |
| source_cache | `<envs_dir>/source_cache/` |
| build_results | `<envs_dir>/build_results/` |
| Setup state | `<envs_dir>/setup_state.yaml` |
| Install output | `<repo_parent>/../installs/<environment_name>/` (`apps/`, `modules/`) |

## Setup options

- `--outputs-dir PATH` (optional): Output root. Defaults to `<repo_parent>/../installs`.
- `--repo-dir PATH` (optional): create-spack-packages checkout (defaults to `<repo_parent>/create-spack-packages`).
- `--spack-version X.Y.Z`: Spack version tag used to derive config-home naming (default: `1.2.1`)
- `--sif-path PATH`: Override SIF location
- `--spack-config-home PATH` (optional): Defaults to `${HOME}/.spack_er_kcl_v<...>`.
- `--envs-dir PATH` (optional): Defaults to `<repo_parent>/environments/`.
- `--environment-name <environment_name>`: Defaults to `arc-ops-env`. `setup.py` writes the environment `spack.yaml` in `<envs_dir>/<environment_name>`; `apps/` and `modules/` are written under `<outputs_dir>/<environment_name>/`.
- `--packages-branch <branch>`: create-spack-packages branch to record (default: `develop`); setup warns if the clone is on a different branch.
- `--mode test|development`: Affects the message printed at end (default: development)
- `--reuse true|false`: Spack concretizer reuse (default: false)

`setup.py` writes `setup_state.yaml` in `<envs_dir>/`. `spack_concretize.py`, `spack_pkgs_install.py` and `spack_mod_refresh.py` use it to pick defaults for paths, `SPACK_USER_CONFIG_PATH`, and environment selection.

Running `setup.py` with a new environment name adds the new environment to the current setup (existing directories and config files are kept).

## Clone and rename

You can clone this repo, rename it, and push to your own GitHub/GitLab. `setup.py` infers the repo inputs from the directory containing this `setup.py`, so the name does not need to match.

## Using a different create-spack-packages branch for one environment

All environments use the one `create-spack-packages` checkout recorded at setup. To build one environment against a different branch, check that branch out in a second clone and override `repos:` in that environment's `spack.yaml` (the key must match the one in `<spack-config-home>/repos.yaml`, so it replaces rather than adds):

```yaml
spack:
  repos:
    local_packages: /scratch/prj/my_prj/spack/control/create-spack-packages-feature/local_packages/spack_repo/kcl
```

Per-env install trees (the default here) keep such experiments isolated: `rm -rf <outputs_dir>/<environment_name>` removes everything the environment ever wrote.

## Interactively submit

1. **Set environment**:
   ```bash
   export SPACK_USER_CONFIG_PATH=${HOME}/.spack_er_kcl_v1_2_1
   ```

2. **Interactive Spack shell** (use `srun` for an interactive session):
   ```bash
   srun -p interruptible_cpu --nodes=1 --ntasks=4 --cpus-per-task=1 --mem-per-cpu=4096 --constraint=zen3 --pty /bin/bash -l
   ```
   The recommended commands are also in `instructions.md` (generated by `setup.py`):
   ```bash
   export SPACK_USER_CONFIG_PATH=${HOME}/.spack_er_kcl_v1_2_1
   singularity shell \
      --env SPACK_USER_CONFIG_PATH="${SPACK_USER_CONFIG_PATH}" \
      --bind "/scratch/prj/my_prj/spack/control/create-spack-development:/scratch/prj/my_prj/spack/control/create-spack-development" \
      --bind "/scratch/prj/my_prj/spack/control/create-spack-packages:/scratch/prj/my_prj/spack/control/create-spack-packages" \
      --bind "/scratch/prj/my_prj/spack/control/environments:/scratch/prj/my_prj/spack/control/environments" \
      --bind "/scratch/prj/my_prj/spack/installs:/scratch/prj/my_prj/spack/installs" \
      --bind "${SPACK_USER_CONFIG_PATH}:${SPACK_USER_CONFIG_PATH}" \
      "/software/containers/singularity/spack/spack_v1_2_1.sif"
   ```

3. **Manage the environment inside the shell**:
   ```bash
   source /opt/spack/share/spack/setup-env.sh   # needed for env activate/deactivate
   spack env list
   spack -e arc-ops-env add 'zlib@1.3'
   spack -e arc-ops-env spec
   spack -e arc-ops-env concretize -f
   spack -e arc-ops-env install
   spack -e arc-ops-env module tcl refresh -y
   spack -e arc-ops-env find
   spack env activate arc-ops-env
   spack env deactivate
   spack repo list
   ```

## Modules

This setup installs tcl modules in `<outputs_dir>/<environment_name>/modules/`

To make the modules available to be loaded, set the environment variable `MODULEPATH`:

```bash
export MODULEPATH=/scratch/prj/my_prj/spack/installs/arc-ops-env/modules:$MODULEPATH
module avail
```
