"""Check render.yaml before Render reads it (run by .github/workflows/service-container.yml).

1. The structure this project relies on: one Docker web service with a health check that deploys after
   the GitHub checks pass, a generated access key, and no settings that free web services refuse.
2. The build filter: merges that change only files outside the container image (docs, tests, CI, the
   Claude Code hook) must not redeploy, because on the free plan every deploy wipes the queue. Every
   file the image is built from must still trigger a deploy.
3. Render's published schema, when it can be fetched, including that it still knows the build-filter
   fields used here.

Needs PyYAML and jsonschema (CI installs them; the app itself does not use them).
Usage: python .github/scripts/check_render_blueprint.py [--schema FILE]
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.request

import jsonschema
import yaml

SCHEMA_URL = "https://render.com/schema/render.yaml.json"

# Files that must NOT redeploy when they are the only change (examples of each ignored area).
MUST_BE_IGNORED = (
    "README.md", "CLAUDE.md", "docs/ROADMAP.md", "docs/funding/README.md",
    "tests/test_core.py", "examples/case_triage_demo.py",
    ".github/workflows/core-tests.yml", ".github/scripts/check_render_blueprint.py",
    ".claude/settings.json", ".claude/hooks/session-start.sh",
)
# Tracked files under these paths are what the Dockerfile copies into the image, plus the files that
# decide how the image is built. A change to any of them must redeploy.
IMAGE_INPUTS = ("Dockerfile", ".dockerignore", "LICENSE", "app", "neuron_flow")


def glob_to_regex(pattern):
    """Render's build-filter globs: '*' stays inside one folder, '**' crosses folders, '**/' may be empty."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def ignored(path, patterns):
    return any(glob_to_regex(p).match(path) for p in patterns)


def check_structure(service):
    assert (service["type"], service["runtime"], service["healthCheckPath"]) == ("web", "docker", "/healthz"), service
    assert service["autoDeployTrigger"] == "checksPass", service
    assert {"key": "NEURON_FLOW_ACCESS_KEY", "generateValue": True} in service["envVars"], service["envVars"]
    if service["plan"] == "free":
        # Render's schema allows these, but Render refuses them on free web services when it reads the
        # Blueprint ("max shutdown delay is not supported for free tier services").
        for field in ("disk", "maxShutdownDelaySeconds"):
            assert field not in service, f"free web services cannot use {field}"
    if "disk" in service:
        assert {"key": "NEURON_FLOW_DATA_DIR", "value": service["disk"]["mountPath"]} in service["envVars"]


def check_build_filter(service, tracked_files):
    build_filter = service.get("buildFilter")
    assert isinstance(build_filter, dict), "render.yaml needs a buildFilter, or every docs merge wipes the free queue"
    # Only ignoredPaths: with an include list, a new top-level folder copied into the image would silently
    # stop deploying until someone remembered to add it.
    assert set(build_filter) == {"ignoredPaths"}, f"use ignoredPaths only, found {sorted(build_filter)}"
    patterns = build_filter["ignoredPaths"]
    assert patterns and all(isinstance(p, str) and p for p in patterns), patterns

    problems = [f"{path} is ignored, so changing it would not redeploy" for path in tracked_files
                if path.split("/", 1)[0] in IMAGE_INPUTS and not path.endswith(".md") and ignored(path, patterns)]
    problems += [f"{path} is not ignored, so changing only it would redeploy and wipe the free queue"
                 for path in MUST_BE_IGNORED if not ignored(path, patterns)]
    image_files = [p for p in tracked_files if p.split("/", 1)[0] in IMAGE_INPUTS]
    assert len(image_files) > 10, f"expected the app's files in git ls-files, found {image_files}"
    return problems


def find_build_filter_schema(schema):
    """Return the schema of a service's buildFilter, following local $refs, or None."""
    def resolve(node):
        seen = set()
        while isinstance(node, dict) and "$ref" in node and node["$ref"].startswith("#/") and node["$ref"] not in seen:
            seen.add(node["$ref"])
            target = schema
            for part in node["$ref"][2:].split("/"):
                target = target[part]
            node = target
        return node

    stack = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict) and "buildFilter" in props:
                return resolve(props["buildFilter"]), resolve
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None, resolve


def schema_knows_ignored_paths(schema):
    found, resolve = find_build_filter_schema(schema)
    stack = [found]
    while stack:
        node = resolve(stack.pop())
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict) and "ignoredPaths" in node["properties"]:
                return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def load_schema(path):
    if path:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    try:
        with urllib.request.urlopen(SCHEMA_URL, timeout=20) as response:
            return json.load(response)
    except Exception as exc:
        print(f"::warning::Render's schema could not be fetched ({type(exc).__name__}); checked the structure only")
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--schema", help="read Render's schema from this file instead of fetching it")
    args = parser.parse_args()

    with open("render.yaml", encoding="utf-8") as handle:
        blueprint = yaml.safe_load(handle)
    (service,) = blueprint["services"]
    check_structure(service)
    tracked = subprocess.run(["git", "ls-files"], check=True, capture_output=True, text=True).stdout.split()
    problems = check_build_filter(service, tracked)
    if problems:
        for problem in problems:
            print(f"::error file=render.yaml::buildFilter: {problem}")
        return 1
    print(f"buildFilter: {len(MUST_BE_IGNORED)} docs/test/CI examples are skipped; "
          f"every file the image is built from still deploys")

    schema = load_schema(args.schema)
    if schema is None:
        return 0
    if not schema_knows_ignored_paths(schema):
        print("::error file=render.yaml::Render's schema has no buildFilter.ignoredPaths; check Render's docs")
        return 1
    try:
        jsonschema.validate(blueprint, schema)
    except jsonschema.ValidationError as exc:
        print(f"::error::render.yaml does not match Render's schema: {exc.message} (at {list(exc.absolute_path)})")
        return 1
    except Exception as exc:
        print(f"::warning::Render's schema could not be applied ({type(exc).__name__}); checked the structure only")
        return 0
    print("render.yaml matches Render's published schema (buildFilter.ignoredPaths included)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
