"""Test selection rules shared by the whole suite.

- local_pg tests use the container opsmem-pg as it is; skipped when OPSMEM_LOCAL_PG is unset.
- docker_script tests remove and recreate that same container, so they run only when selected
  with -m docker_script, and never in the same session as local_pg tests.
- aurora tests need a deployed cluster; skipped when CLUSTER_ARN is unset.
"""
import os

import pytest

pytest_plugins = ["pytester"]

MARKERS = {
    "local_pg": "uses the shared container opsmem-pg (needs OPSMEM_LOCAL_PG)",
    "docker_script": "starts and stops opsmem-pg; run only with -m docker_script, never together with local_pg",
    "aurora": "needs a deployed Aurora cluster (CLUSTER_ARN)",
}


def pytest_configure(config):
    for name, text in MARKERS.items():
        config.addinivalue_line("markers", f"{name}: {text}")


def _has(item, name):
    return item.get_closest_marker(name) is not None


@pytest.hookimpl(trylast=True)  # runs after the -m filter has deselected items
def pytest_collection_modifyitems(config, items):
    explicit = "docker_script" in (config.getoption("markexpr") or "")
    if explicit:
        if any(_has(i, "docker_script") for i in items) and any(_has(i, "local_pg") for i in items):
            raise pytest.UsageError(
                "markers docker_script and local_pg both use the container opsmem-pg "
                "and cannot run together; select one of them")
    else:
        skip = pytest.mark.skip(reason="docker_script tests run only with -m docker_script")
        for item in items:
            if _has(item, "docker_script"):
                item.add_marker(skip)
    if not os.environ.get("OPSMEM_LOCAL_PG"):
        skip = pytest.mark.skip(reason="local_pg tests need OPSMEM_LOCAL_PG")
        for item in items:
            if _has(item, "local_pg"):
                item.add_marker(skip)
    if not os.environ.get("CLUSTER_ARN"):
        skip = pytest.mark.skip(reason="aurora tests need CLUSTER_ARN")
        for item in items:
            if _has(item, "aurora"):
                item.add_marker(skip)
