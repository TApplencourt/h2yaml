import pathlib
import pytest
import h2yaml
import yaml
import os
import sys

filenames = [str(p.with_suffix("")) for p in pathlib.Path("./tests/").glob("*.h")]

# Utils


@pytest.fixture
def mock_stdin_fd(monkeypatch):
    r, w = os.pipe()

    saved_stdin_fd = os.dup(sys.__stdin__.fileno())
    os.dup2(r, sys.__stdin__.fileno())
    os.close(r)

    try:
        yield w
    finally:
        # Restore original stdin
        os.dup2(saved_stdin_fd, sys.__stdin__.fileno())
        os.close(saved_stdin_fd)


def run_main_and_get_yaml(capsys, argv):
    h2yaml.main(argv)
    data = capsys.readouterr()
    return yaml.safe_load(data.out)


# Tests


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


def test_no_macro_in_enum():
    filename = "./tests/enum"
    assert "MAX_SIZE" in h2yaml.h2yaml(f"{filename}.h", assume_no_macro_in_enum=True)


def test_main_version():
    with pytest.raises(SystemExit) as e:
        h2yaml.main(["-Wc,-DTEST_DEFINE=12", "./tests/struct_forward.h"])
    assert e.value.code == 1


def test_main_versiom():
    with pytest.raises(SystemExit) as e:
        h2yaml.main(["--version"])
    assert e.value.code == 0


def test_main_arguments_and_grouping(capsys):
    filename = "./tests/struct_forward"

    with open(f"{filename}_define.yml", "r") as f:
        ref_yml = yaml.safe_load(f)

    yml0 = yaml.safe_load(
        h2yaml.h2yaml(f"{filename}.h", clang_args=["-DTEST_DEFINE=A13d"])
    )
    yml1 = run_main_and_get_yaml(capsys, ["-Wc,-DTEST_DEFINE=A13d", f"{filename}.h"])
    yml2 = run_main_and_get_yaml(
        capsys,
        ["-Wc,--startgroup", "-DTEST_DEFINE=A13d", "-Wc,--endgroup", f"{filename}.h"],
    )

    assert ref_yml == yml0 == yml1 == yml2


def test_main_arguments_stdin(capsys, mock_stdin_fd):
    file = "./tests/header_filter/foo.h"

    yml0 = run_main_and_get_yaml(capsys, [file, "--filter-header", "foo.h"])

    with open(file, "rb") as f:
        mock_stdin_data = f.read()

    os.write(mock_stdin_fd, mock_stdin_data)
    os.close(mock_stdin_fd)

    yml1 = run_main_and_get_yaml(
        capsys,
        ["-Wc,-xc", "-Wc,-I./tests/header_filter/", "--filter-header", "<stdin>", "-"],
    )
    assert yml0 == yml1
