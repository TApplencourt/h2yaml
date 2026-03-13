import pytest
import re
import h2yaml  # Importing this to ensure your patch/setup is loaded
import clang.cindex


def pytest_configure(config):
    """Dynamically add coverage exclusions based on libclang version."""
    version_string = clang.cindex.Config.get_cindex_library_version()
    match = re.search(r"version\s+(\d+)", version_string)
    major_version = int(match.group(1))

    # Determine which pragma to tell Coverage to IGNORE.
    # We exclude the pragma for the code that WILL NOT RUN.
    if major_version < 23:
        # We are on an OLD version. The NEW code won't run, so ignore it.
        pragma_to_exclude = r"pragma: no cover:libclang>=22"
    else:
        # We are on a NEW version. The OLD code won't run, so ignore it.
        pragma_to_exclude = r"pragma: no cover:libclang<22"

    # Inject the rule directly into pytest-cov
    cov_plugin = config.pluginmanager.get_plugin("_cov")
    cov_plugin.cov_controller.cov.exclude(pragma_to_exclude)
