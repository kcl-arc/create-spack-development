# er-spack-development

User-cloneable Spack 1.1.1 environment for creating personal builds. Uses the Singularity container at `/software/containers/singularity/spack/spack_v1_1_1.sif`.

- **Personal builds**: Maintain your own Spack package recipes and builds on the HPC

## Prerequisites

- Python 3 with jinja2 (`pip install jinja2`)
- pyyaml (`pip install pyyaml`) for `submit_example.py`
- Singularity/Apptainer client on your machine/host where you run the commands

## Quick start

1. **Clone** (or copy) this repo to your project location, e.g.:
   ```bash
   git clone <repo-url> /scratch/prj/my_prj/spackaging/er-spack-development
   ```

2. **Create outputs dir** (separate from the repo inputs):
   ```bash
   mkdir -p /scratch/prj/my_prj/spackaging/my_outputs
   ```

3. **Run setup** (writes config to `$HOME/.spack_er_kcl_v1_1_1` by default):
   ```bash
   cd /scratch/prj/my_prj/spackaging/er-spack-development
   ./setup.py --outputs-dir /scratch/prj/my_prj/spackaging/my_outputs
   ```

4. **Batch submit** (example):
   ```bash
   ./submit_example.py --outputs-dir /scratch/prj/my_prj/spackaging/my_outputs \
     --package zlib
   ```

## `package_installs/<package>.yaml` format

`submit_example.py` reads `package_installs/<package>.yaml` and submits one Slurm job for each entry in `versions[<selected_version>]`.

Supported keys:

- `versions` (required): mapping of version string to a list of *flag entries*.
  - Example: `versions: { "1.3": ["", "^mpi@4.1.5", "+feature=on"] }`
  - The empty string `""` means “no extra flags”.
- `archs` (optional): list of allowed architectures (e.g. `["zen2", "zen4"]`).
  - If `--arch` is omitted, it is inferred from the host CPU; this is then validated against `archs` when present.
- `gpus` (optional): integer number of GPUs for the job.
  - If set, `submit_example.py` uses `--partition interruptible_gpu` and appends `#SBATCH --gres gpu:<gpus>` to `slurm_args`.

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

## Setup options

- `--outputs-dir PATH` (required): Output root (install/, source_cache/, build_results/)
- `--repo-dir PATH` (optional): Input repo root
- `--spack-config-dir PATH` (optional): Defaults to `$HOME/.spack_er_kcl_v1_1_1`. If you place it under `--outputs-dir`, include `$USER` in the path.
- `--mode test|development`: Affects the message printed at end (default: development)
- `--sif-path PATH`: Override SIF location
- `--reuse true|false`: Spack concretizer reuse (default: false)

## Clone and rename

You can clone this repo, rename it, and push to your own GitHub/GitLab. `setup.py` infers the repo inputs from the directory containing this `setup.py`, so the name does not need to match.

## Branch mapping for repo inputs

When `--repo-dir` points to an `er-spack-packages` checkout:

- `staging` branch maps to `v1_1_test`
- `production` branch maps to `v1_1_prod`

Use `git checkout staging` or `git checkout production` in your `--repo-dir` clone before running `submit_example.py`.

`git checkout -b new_branch` to develop a new package before making an MR to staging.

See https://github.com/kcl-eresearch/er-spack-packages for example formats and layout of the `--repo-dir`

## Interactively submit

1. **Set environment**:
   ```bash
   export SPACK_USER_CONFIG_PATH=$HOME/.spack_er_kcl_v1_1_1
   ```

2. **Interactive install** (use `srun` for interactive session):
   ```bash
   singularity exec --bind /scratch/prj/my_prj/spackaging/er-spack-development:/scratch/prj/my_prj/spackaging/er-spack-development \
     --bind /scratch/prj/my_prj/spackaging/my_outputs:/scratch/prj/my_prj/spackaging/my_outputs \
     --bind $HOME:$HOME \
     /software/containers/singularity/spack/spack_v1_1_1.sif \
     /opt/spack/bin/spack install zlib@1.3
   ```
