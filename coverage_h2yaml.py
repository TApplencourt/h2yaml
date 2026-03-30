from contextlib import contextmanager
from functools import cached_property


@contextmanager
def temporary_import(mod_name):
    import sys
    import importlib

    try:
        yield importlib.import_module(mod_name)
    finally:
        del sys.modules[mod_name]


class DynamicExcludePlugin:
    @cached_property
    def clang_major_version(self):
        import re

        with temporary_import("h2yaml") as h2yaml:
            version_string = h2yaml.clang.cindex.Config.get_clang_version()
            h2yaml.clang.cindex.Config.loaded = False
            match = re.search(r"version\s+(\d+)", version_string)
            return int(match.group(1))

    def configure(self, config):
        existing = config.get_option("report:exclude_lines") or []
        if self.clang_major_version < 22:
            existing.append(r"pragma: if libclang<22: no cover")
        else:
            existing.append(r"pragma: if libclang>=22: no cover")

        config.set_option("report:exclude_lines", existing)


def coverage_init(reg, options):
    plugin = DynamicExcludePlugin()
    reg.add_configurer(plugin)
