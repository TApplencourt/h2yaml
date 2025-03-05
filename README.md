# h2yaml

Transform your C header file (`.h`) into YAML.
Based on `libclang` and their python binding (https://libclang.readthedocs.io/en/latest/index.html#).

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
```
git clone https://github.com/TApplencourt/h2yaml.git
cd h2yaml
pip install .
```

For developpent please use `pip install .[test]`.
Require python `>=3.10`; one cannot write a Parser without Pattern Matching.

## Usage
```
python h2yaml.py path/to/your/header.h
```
Can also read from `stdin`.

## Format

The YAML will consist of 6 declarations sections: `structs,` `unions,` `typedefs,` `declarations,` `functions,` and `enums.` 
Each declaration will contain a name, a type, and potentially a list of members.

## Example:
```
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
