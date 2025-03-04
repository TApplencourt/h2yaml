import pathlib
import pytest
from h2yaml import h2yaml
import yaml

filenames = [str(p.with_suffix("")) for p in pathlib.Path("./tests/").glob("*.yml")]

@pytest.mark.parametrize("filename", filenames)
def test_cmp_to_ref(filename):
    new_yml =  yaml.safe_load(h2yaml(f"{filename}.h"))
 
    with open(f"{filename}.yml", 'r') as f:
        ref_yml = yaml.safe_load(f)

    assert new_yml == ref_yml


def test_dumb():
    with open(f"./log_cuda.yml", 'r') as f:
        new_yml = yaml.safe_load(f)

    with open(f"/home/applenco/THAPI/build/cuda/cuda_api.yaml", 'r') as f:
        ref_yml = yaml.safe_load(f)

    assert new_yml == ref_yml
