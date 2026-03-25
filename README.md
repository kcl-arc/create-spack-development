# er-spack-development

User-cloneable Spack environment for creating personal builds or developing environments. Uses the Singularity container at `/software/containers/singularity/spack/spack_v1_1_1.sif` as default, others can be specified.

- **Personal builds**: Maintain your own Spack package recipes and builds on the HPC

## Prerequisites

- Python 3 with jinja2 (`pip install jinja2`)
- pyyaml (`pip install pyyaml`) for `spack_install.py`

## Quick start

1. **Clone** (or copy) this repo to a project location, e.g.:
   ```bash
   git clone <repo-url> /scratch/prj/my_prj/spackaging/er-spack-development
   ```

2. **Create outputs dir** (separate from the repo inputs):
   ```bash
   mkdir -p /scratch/prj/my_prj/spackaging/spackages
   ```
   If you do not pass `--outputs-dir`, `setup.py` defaults to `<repo_parent>/spackages` and asks for confirmation.

3. **Run setup** (writes config to `$HOME/.spack_er_kcl_v1_1_1` by default):
   ```bash
   cd /scratch/prj/my_prj/spackaging/er-spack-development
   ./setup.py
   ```

4. **Batch submit** (example):
   ```bash
   ./spack_install.py --package zlib
   ```

## `package_installs/<package>.yaml` format

`spack_install.py` reads `package_installs/<package>.yaml` and submits one Slurm job for each entry in `versions[<selected_version>]`.

Supported keys:

- `versions` (required): mapping of version string to a list of *flag entries*.
  - Example: `versions: { "1.3": ["", "^mpi@4.1.5", "+feature=on"] }`
  - The empty string `""` means “no extra flags”.
- `archs` (optional): list of allowed architectures (e.g. `["zen2", "zen4"]`).
  - If `--arch` is omitted, it is inferred from the host CPU; this is then validated against `archs` when present.
- `gpus` (optional): integer number of GPUs for the job.
  - If set, `spack_install.py` uses `--partition interruptible_gpu` and appends `#SBATCH --gres gpu:<gpus>` to `slurm_args`.

The following keys are expected but not interpreted specially by this repo:
- the flag strings are appended directly after `target=<arch>` in the rendered `spack install` command.

## Directory layout

| Purpose | Location |
|---------|----------|
| Spack config | `$HOME/.spack_er_kcl_v1_1_1/` (written by setup) |
| Repo clone | Your choice (e.g. `/scratch/prj/my_prj/spackaging/er-spack-development`) |
| local_packages | `<setup.py_dir>/../er-spack-packages/local_packages/packages/<pkg>/package.py` |
| package_installs | `<setup.py_dir>/../er-spack-packages/package_installs/*.yaml` |
| Install output | `<outputs_dir>/install/` |
| source_cache | `<outputs_dir>/source_cache/` |
| build_results | `<outputs_dir>/build_results/` |
| Spack environments | `<outputs_dir>/environments/` |
| Setup state | `<repo_parent>/setup_state.yaml` |

## Setup options

- `--outputs-dir PATH` (optional): Output root (install/, source_cache/, build_results/). Defaults to `<repo_parent>/spackages`.
- `--repo-dir PATH` (optional): Input repo root
- `--spack-version X.Y.Z`: Spack version tag used to derive config-home naming (default: `1.1.1`)
- `--sif-path PATH`: Override SIF location
- `--spack-config-home PATH` (optional): Defaults to `$HOME/.spack_er_kcl_v<...>`. (Alias: `--spack-config-dir`.)
- `--environment-name NAME` (optional): If set (non-blank), `setup.py` creates and uses a Spack environment under `<outputs_dir>/environments/`.
- `--mode test|development`: Affects the message printed at end (default: development)
- `--reuse true|false`: Spack concretizer reuse (default: false)

When `--environment-name` is set and the environment does not yet exist, `setup.py` submits a **Slurm** job (default `sbatch --wait`) using `slurm_env_create.j2`, because Singularity is not available on login nodes. Defaults should be sufficient, options are: `--env-create-partition`, `--env-create-slurm-args`, `--env-create-constraint`, `--env-create-no-submit`, `--env-create-no-wait`.

`setup.py` writes `setup_state.yaml` in the parent directory of this repo. `spack_install.py` uses it to pick defaults for outputs path, `SPACK_USER_CONFIG_PATH`, and environment selection.

## Clone and rename

You can clone this repo, rename it, and push to your own GitHub/GitLab. `setup.py` infers the repo inputs from the directory containing this `setup.py`, so the name does not need to match.

## Branch mapping for repo inputs

In the future is is expected that when `--repo-dir` points to an `er-spack-packages` checkout:

- `staging` branch maps to `v1_1_test`
- `production` branch maps to `v1_1_prod`

Use `git checkout staging` or `git checkout production` in your `--repo-dir` clone before running `spack_install.py`.

`git checkout -b new_branch` to develop a new package before making an MR to staging.

See https://github.com/kcl-eresearch/er-spack-packages for example formats and layout of the `--repo-dir`

## Interactively submit

1. **Set environment**:
   ```bash
   export SPACK_USER_CONFIG_PATH=$HOME/.spack_er_kcl_v1_1_1
   ```

2. **Interactive install** (use `srun` for interactive session). The recommended commands are also in `instructions.md` (generated by `setup.py`):
   ```bash
   singularity exec --bind /scratch/prj/my_prj/spackaging/er-spack-development:/scratch/prj/my_prj/spackaging/er-spack-development \
     --bind /scratch/prj/my_prj/spackaging/spackages:/scratch/prj/my_prj/spackaging/spackages \
     --bind $HOME:$HOME \
     /software/containers/singularity/spack/spack_v1_1_1.sif \
     /opt/spack/bin/spack -e <environment_name> install zlib@1.3
   ```
