# h2yaml

Transform your C header file (`.h`) into YAML.
Based on `libclang` and their [python binding](https://libclang.readthedocs.io/en/latest/index.html#).

```
     ___      I will parse
    /___\     your .h
   (|0 0|)
 __/{\U/}\_ ___/vvv
/ \  {~}   / _|_P|
| /\  ~   /_/   ||
|_| (____)      ||
\_]/______\  /\_||_/\
   _\_||_/_ |] _||_ [|
  (_,_||_,_) \/ [] \/

```

## Installation

For system wide install do:
```bash
pip install https://github.com/TApplencourt/h2yaml.git
```
Then just use `h2yaml` binary.  

We also support [PEP723](https://peps.python.org/pep-0723/) inline dependency: 
```bash
git clone https://github.com/TApplencourt/h2yaml.git
cd h2yaml
uv run h2yaml.py
```

For developpent please use `pip install --group test` and to run tests
```
uv run coverage run --module pytest -vv --full-trace
uv run coverage report --show-missing --fail-under=100
```

Require python `>=3.11`; one cannot write a Parser without Pattern Matching.

## Usage

```bash
h2yaml path/to/your/header.h
```
You can also read from `stdin` by passing `-` as the file argument:
```bash
cat header.h | h2yaml -Wc,-xc -
```

### Passing arguments to clang

If you need to forward options directly to clang (for example, include paths or warning flags),
we follow the same convention used by GCC when passing options to the linker using [`-Wl`](https://sourceware.org/binutils/docs/ld/Options.html).

In `h2yaml`, we use the `-Wc` prefix to forward option to clang (we also support `-Wc,--startgroup` and `-Wc,--endgroup` to pass multiples options).

```bash
h2yaml -Wc,-I./include/ path/to/your/header.h
```

### Filtering

It's possible to filter headers relevant to your use case using `--filter-header` options with a regex:

```bash
h2yaml --filter-header "my_app*.h"
```

By default, all system headers are ignored. To include them, use:

```bash
h2yaml --filter-header None
```

## Format

The YAML will consist of 6 declarations sections: `structs,` `unions,` `typedefs,` `declarations,` `functions,` and `enums.` 
Each declaration will contain a name, a type, and potentially a list of members.

## Example:
```bash
echo "struct a {
  int i;
  union {
    struct B6 {
      int x;
    } b;
  } a6;
};
typedef int c_t;
typedef c_t (*d_t)(struct a);" | python h2yaml.py -
structs:
- members:
  - name: x
    type:
      kind: int
      name: int
  name: B6
- members:
  - name: i
    type:
      kind: int
      name: int
  - name: a6
    type:
      kind: union
      members:
      - name: b
        type:
          kind: struct
          name: B6
  name: a
typedefs:
- name: c_t
  type:
    kind: int
    name: int
- name: d_t
  type:
    kind: pointer
    type:
      kind: function
      params:
      - type:
          kind: struct
          name: a
      type:
        kind: custom_type
        name: c_t
```
