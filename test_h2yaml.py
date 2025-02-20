import pathlib
import pytest
from h2yaml import h2yaml_main
import yaml

filenames = [str(p.with_suffix("")) for p in pathlib.Path("./tests/").glob("*.h")]

@pytest.mark.parametrize("filename", filenames)
def test_cmp_to_ref(filename):
    new_yml =  yaml.safe_load(h2yaml_main(f"{filename}.h"))
 
    with open(f"{filename}.yml", 'r') as f:
        ref_yaml = yaml.safe_load(f)

    assert new_yml == ref_yaml


