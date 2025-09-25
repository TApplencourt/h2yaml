import pathlib
import pytest
import h2yaml
import yaml

filenames = [str(p.with_suffix("")) for p in pathlib.Path("./tests/").glob("*.h")]


@pytest.mark.parametrize("filename", filenames)
def test_cmp_to_ref(filename):
    new_yml = yaml.safe_load(h2yaml.h2yaml(f"{filename}.h"))

    with open(f"{filename}.yml", "r") as f:
        ref_yml = yaml.safe_load(f)

    assert new_yml == ref_yml


def test_filter_include():
    filename = "./tests/header_filter/foo"
    new_yml = yaml.safe_load(h2yaml.h2yaml(f"{filename}.h", pattern="foo.h"))

    with open(f"{filename}.yml", "r") as f:
        ref_yml = yaml.safe_load(f)

    assert new_yml == ref_yml


def test_canonicalization():
    filename = "./tests/function"
    new_yml = yaml.safe_load(h2yaml.h2yaml(f"{filename}.h", canonicalization=True))

    with open(f"{filename}_canonical.yml", "r") as f:
        ref_yml = yaml.safe_load(f)

    assert new_yml == ref_yml


def test_main_version():
    with pytest.raises(SystemExit) as e:
        h2yaml.main(["--version"])
    assert e.value.code == 0


def test_main_arguments():
    str_ = "{} --filter-header foo.h -- ./tests/header_filter/foo.h"
    str0 = h2yaml.main(str_.format("-Wc,-I./tests/header_filter/").split())
    str1 = h2yaml.main(
        str_.format("-Wc,--startgroup -I./tests/header_filter/ -Wc,--endgroup").split()
    )
    assert str0 == str1
