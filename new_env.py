#!/usr/bin/env python3
"""
Create a Spack environment under environments/<name>/.

Without --from, writes a blank manifest. With --from <dir>, copies spack.yaml
(and meta.yaml) from another environment, e.g. a bespoke environment in
create-spack-environments, removes its install tree and module roots and adds
'include: [paths.yaml]', so this checkout's generated paths.yaml applies. The
edit is line-based so comments are kept.
"""

import argparse
import os
import re
import sys

try:
    from er_spack_common import (
        ENV_NAME_RE,
        ENVS_DIR,
        PATHS_FILE,
        check_manifest,
        includes_paths_yaml,
        load_setup_state,
        logical_path,
        template_env,
        write_paths_yaml,
    )
except ModuleNotFoundError as e:
    if e.name != "er_spack_common":
        raise
    sys.exit("Cannot import er_spack_common. Run ./new_env.py from the create-spack-development checkout.")

import yaml  # noqa: E402 (availability checked by er_spack_common)

# A mapping key line: "<indent><key>:" followed by a space or end of line.
KEY_RE = re.compile(r"^(?P<indent>[ ]*)(?P<key>[^\s#\-][^#]*?):(?:[ \t]+|$)")


def _parse(lines):
    """For each line: (indent, key path, inline value) for mapping keys, else None."""
    stack = []
    info = []
    for line in lines:
        m = KEY_RE.match(line)
        if not m:
            info.append(None)
            continue
        indent = len(m.group("indent"))
        key = m.group("key").strip().strip("'\"")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, key))
        value = line[m.end():].strip()
        if value.startswith("#"):
            value = ""
        info.append((indent, tuple(k for _, k in stack), value))
    return info


def _block_end(lines, start, indent):
    """Index just past the key at lines[start] and everything nested under it."""
    last = start
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue
        line_indent = len(lines[i]) - len(lines[i].lstrip())
        # "key:\n- item" lists may sit at the key's own indent
        if line_indent > indent or (line_indent == indent and stripped.startswith("-")):
            last = i
            continue
        break
    return last + 1


def _is_path_setting(path):
    return path == ("spack", "config", "install_tree") or (
        len(path) == 4 and path[:2] == ("spack", "modules") and path[3] == "roots"
    )


def strip_path_settings(text):
    """Remove spack:config:install_tree and spack:modules:<set>:roots, and any parent left empty."""
    lines = text.splitlines(keepends=True)
    parents = set()
    out = []
    info = _parse(lines)
    skip_to = 0
    for i, line in enumerate(lines):
        if i < skip_to:
            continue
        entry = info[i]
        if entry and _is_path_setting(entry[1]):
            skip_to = _block_end(lines, i, entry[0])
            path = entry[1]
            parents.update(path[:n] for n in range(2, len(path)))
            continue
        out.append(line)

    changed = True
    while changed:
        changed = False
        info = _parse(out)
        for i, entry in enumerate(info):
            if entry and entry[1] in parents and not entry[2] and _block_end(out, i, entry[0]) == i + 1:
                del out[i]
                changed = True
                break
    return "".join(out)


def add_include(text):
    """Add paths.yaml to spack:include (creating it if needed); None if it can't be done safely."""
    lines = text.splitlines(keepends=True)
    info = _parse(lines)
    spack_idx = next((i for i, e in enumerate(info) if e and e[1] == ("spack",)), None)
    if spack_idx is None:
        return None
    include_idx = next((i for i, e in enumerate(info) if e and e[1] == ("spack", "include")), None)

    if include_idx is None:
        child = next((e for e in info[spack_idx + 1:] if e and len(e[1]) == 2), None)
        pad = " " * (child[0] if child else info[spack_idx][0] + 2)
        lines.insert(spack_idx + 1, f"{pad}include:\n{pad}- {PATHS_FILE}\n")
        return "".join(lines)

    indent, _, value = info[include_idx]
    if value:
        # flow style, e.g. "include: [a.yaml]"
        line = lines[include_idx]
        new_line, n = re.subn(
            r"\[\s*(\]?)",
            lambda m: f"[{PATHS_FILE}]" if m.group(1) else f"[{PATHS_FILE}, ",
            line,
            count=1,
        )
        if not n:
            return None
        lines[include_idx] = new_line
        return "".join(lines)

    item_indent = indent + 2
    for line in lines[include_idx + 1:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            if stripped.startswith("-"):
                item_indent = len(line) - len(line.lstrip())
            break
    lines.insert(include_idx + 1, f"{' ' * item_indent}- {PATHS_FILE}\n")
    return "".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Create a Spack environment under environments/<name>/",
        epilog="e.g. ./new_env.py my-env --from ../create-spack-environments/environments/bespoke/arc-zen3-cpu",
    )
    parser.add_argument("name", help="Environment name (letters, digits, '_', '.', '-')")
    parser.add_argument(
        "--from",
        dest="source",
        metavar="DIR",
        help="Copy spack.yaml (and meta.yaml) from DIR: another environment here or a bespoke environment",
    )
    parser.add_argument(
        "--constraint",
        default=None,
        help="Slurm feature the environment's jobs need (e.g. zen3), written to meta.yaml; '' removes it",
    )
    args = parser.parse_args()

    name = args.name
    if not ENV_NAME_RE.fullmatch(name):
        sys.exit(f"Invalid name {name!r}: use letters, digits, '_', '.', '-' (starting with a letter or digit).")
    dest = os.path.join(ENVS_DIR, name)
    if os.path.exists(dest):
        sys.exit(f"environments/{name} already exists.")

    meta = None
    meta_text = None
    if args.source:
        src_dir = logical_path(args.source)
        if os.path.basename(src_dir) == "spack.yaml" and os.path.isfile(src_dir):
            src_dir = os.path.dirname(src_dir)
        src_manifest = os.path.join(src_dir, "spack.yaml")
        if not os.path.isfile(src_manifest):
            sys.exit(f"No spack.yaml in {src_dir}")
        with open(src_manifest) as fh:
            text = strip_path_settings(fh.read())
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            sys.exit(f"{src_manifest}: not valid YAML after removing install/module paths ({e})")
        spack = data.get("spack") if isinstance(data, dict) else None
        if not isinstance(spack, dict):
            sys.exit(f"{src_manifest}: no top-level 'spack:' mapping")
        if not includes_paths_yaml(spack):
            text = add_include(text)
            if text is None:
                sys.exit(f"Couldn't add 'include: [{PATHS_FILE}]' to a copy of {src_manifest}; add it by hand.")
        src_meta = os.path.join(src_dir, "meta.yaml")
        if os.path.isfile(src_meta):
            with open(src_meta) as fh:
                meta_text = fh.read()
            meta = yaml.safe_load(meta_text) or {}
    else:
        text = template_env().get_template("new_env.yaml.j2").render(environment_name=name)

    if args.constraint is not None:
        meta = dict(meta or {})
        if args.constraint:
            meta["constraint"] = args.constraint
        else:
            meta.pop("constraint", None)
        meta_text = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False) if meta else None

    os.makedirs(dest)
    with open(os.path.join(dest, "spack.yaml"), "w") as fh:
        fh.write(text)
    written = ["spack.yaml"]
    if meta_text:
        with open(os.path.join(dest, "meta.yaml"), "w") as fh:
            fh.write(meta_text)
        written.append("meta.yaml")
    print(f"Created environments/{name}/ ({', '.join(written)})")

    problems = check_manifest(name)
    for problem in problems:
        print(f"Error: {problem}", file=sys.stderr)
    if problems:
        sys.exit("Fix the manifest above before building.")

    state = load_setup_state(required=False)
    if state:
        write_paths_yaml(name, state)
    else:
        print(f"Note: run ./setup.py to finish (it writes environments/{name}/{PATHS_FILE}).")

    print()
    print("Next:")
    print(f"  edit environments/{name}/spack.yaml (specs:)")
    print(f"  ./spack_build.py -e {name}")
    print(f"  git add environments/{name} && git commit")


if __name__ == "__main__":
    main()
