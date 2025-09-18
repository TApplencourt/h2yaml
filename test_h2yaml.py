import pathlib
import pytest
from h2yaml import h2yaml
import yaml

filenames = [str(p.with_suffix("")) for p in pathlib.Path("./tests/").glob("*.h")]


@pytest.mark.parametrize("filename", filenames)
def test_cmp_to_ref(filename):
    new_yml = yaml.safe_load(h2yaml(f"{filename}.h"))

    with open(f"{filename}.yml", "r") as f:
        ref_yml = yaml.safe_load(f)

    assert new_yml == ref_yml


def test_filter_include():
    filename = "./tests/header_filter/foo"
    new_yml = yaml.safe_load(h2yaml(f"{filename}.h", pattern="foo.h"))

    with open(f"{filename}.yml", "r") as f:
        ref_yml = yaml.safe_load(f)

    assert new_yml == ref_yml


def test_canonicalization():
    filename = "./tests/function"
    new_yml = yaml.safe_load(h2yaml(f"{filename}.h", canonicalization=True))

    with open(f"{filename}_canonical.yml", "r") as f:
        ref_yml = yaml.safe_load(f)

    assert new_yml == ref_yml
