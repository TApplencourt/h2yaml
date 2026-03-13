def clean_imports(*mod_names):
    import sys

    for mod_name in mod_names:
        sys.modules.pop(mod_name, None)
        for key in list(sys.modules.keys()):
            if key.startswith(mod_name + "."):
                del sys.modules[key]


class DynamicExcludePlugin:
    @property
    def clang_major_version(self):
        import h2yaml
        import re

        version_string = h2yaml.clang.cindex.Config.get_cindex_library_version()
        h2yaml.clang.cindex.Config.loaded = False

        clean_imports("h2yaml")
        del h2yaml
        match = re.search(r"version\s+(\d+)", version_string)
        return int(match.group(1))

    def configure(self, config):
        # get_option / set_option work on BOTH Coverage and CoverageConfig
        existing = config.get_option("report:exclude_lines") or []
        if self.clang_major_version < 22:
            existing.append(r"pragma: if libclang<22: no cover")
        else:
            existing.append(r"pragma: if libclang>=22: no cover")

        config.set_option("report:exclude_lines", existing)


def coverage_init(reg, options):
    plugin = DynamicExcludePlugin()
    reg.add_configurer(plugin)
