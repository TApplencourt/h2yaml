import pathlib
import pytest
import unittest.mock
import h2yaml
import yaml
from io import StringIO

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


def run_main_and_get_yaml(argv):
    fake_stdout = StringIO()

    with unittest.mock.patch("sys.stdout", fake_stdout):
        h2yaml.main(argv)

    return yaml.safe_load(fake_stdout.getvalue())


def test_main_arguments_and_grouping():
    filename = "./tests/struct_forward"

    with open(f"{filename}_define.yml", "r") as f:
        ref_yml = yaml.safe_load(f)

    yml0 = run_main_and_get_yaml(["-Wc,-DTEST_DEFINE", f"{filename}.h"])
    yml1 = run_main_and_get_yaml(
        ["-Wc,--startgroup", "-DTEST_DEFINE", "-Wc,--endgroup", f"{filename}.h"]
    )

    assert ref_yml == yml0 == yml1
