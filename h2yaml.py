import sys
from functools import cache
import clang.cindex
import yaml
import type_enforced

#   ___
#    |    ._   _
#    | \/ |_) (/_
#      /  |
THAPI_types = {
    clang.cindex.TypeKind.VOID: "void",
    clang.cindex.TypeKind.FLOAT: "float",
    clang.cindex.TypeKind.DOUBLE: "float",
    clang.cindex.TypeKind.LONGDOUBLE: "float",
    clang.cindex.TypeKind.INT: "int",
    clang.cindex.TypeKind.UINT: "int",
    clang.cindex.TypeKind.SHORT: "int",
    clang.cindex.TypeKind.USHORT: "int",
    clang.cindex.TypeKind.LONG: "int",
    clang.cindex.TypeKind.ULONG: "int",
    clang.cindex.TypeKind.LONGLONG: "int",
    clang.cindex.TypeKind.ULONGLONG: "int",
    clang.cindex.TypeKind.CHAR_U: "char",
    clang.cindex.TypeKind.UCHAR: "char",
    clang.cindex.TypeKind.CHAR_S: "char",
    clang.cindex.TypeKind.SCHAR: "char",
}


@type_enforced.Enforcer
def parse_type(t: clang.cindex.Type, c: clang.cindex.Cursor | None = None):
    match k := t.kind:
        case _ if kind := THAPI_types.get(k):
            return {"kind": kind, "name": t.spelling}
        case clang.cindex.TypeKind.POINTER:
            return {"kind": "pointer", "type": parse_type(t.get_pointee(), c)}
        case clang.cindex.TypeKind.ELABORATED | clang.cindex.TypeKind.RECORD:
            return parse_decl(t.get_declaration())
        case clang.cindex.TypeKind.CONSTANTARRAY:
            return {
                "kind": "array",
                "type": parse_type(t.element_type),
                "length": t.element_count,
            }
        case clang.cindex.TypeKind.INCOMPLETEARRAY:
            return {"kind": "array", "type": parse_type(t.element_type)}
        case clang.cindex.TypeKind.FUNCTIONPROTO:
            return {"kind": "function"} | parse_function_proto(t, c)
        case _:  # pragma: no cover
            raise NotImplementedError(f"parse_type: {k}")


@type_enforced.Enforcer
def parse_decl(c: clang.cindex.Cursor):
    match k := c.kind:
        case clang.cindex.CursorKind.STRUCT_DECL:
            return {"kind": "struct"} | parse_struct_decl(c)
        case clang.cindex.CursorKind.UNION_DECL:
            return {"kind": "union"} | parse_union_decl(c)
        case clang.cindex.CursorKind.ENUM_DECL:
            return {"kind": "enum"} | parse_enum_decl(c)
        case clang.cindex.CursorKind.TYPEDEF_DECL:
            return parse_typedef_decl(c)
        case clang.cindex.CursorKind.FUNCTION_DECL:
            return parse_function_decl(c)
        case clang.cindex.CursorKind.VAR_DECL:
            return parse_var_decl(c)
        case _:  # pragma: no cover
            raise NotImplementedError(f"parse_decl: {k}")


#   ___                    _    _
#    |    ._   _   _|  _ _|_   | \  _   _ |
#    | \/ |_) (/_ (_| (/_ |    |_/ (/_ (_ |
#      /  |
@type_enforced.Enforcer
def parse_typedef_decl(c: clang.cindex.Cursor):

    type_ = parse_type(c.underlying_typedef_type, c)
    DECLARATIONS["typedefs"].append(
        {
            "name": c.spelling,
            "type": type_,
        }
    )


#                 _
#   \  / _. ._   | \  _   _ |
#    \/ (_| |    |_/ (/_ (_ |
#
@type_enforced.Enforcer
def parse_var_decl(c: clang.cindex.Cursor):

    type_ = parse_type(c.type, c)

    # Assume all INCOMPLETEARRAY types will eventually be completed.
    # This works because libclang treats `a[]` as:
    # `tentative array definition assumed to have one element`
    # As a result, it will be parsed as a `CONSTANTARRAY`
    if c.type.kind == clang.cindex.TypeKind.INCOMPLETEARRAY:
        return
    DECLARATIONS["declarations"].append(
        {
            "name": c.spelling,
            "type": type_,
        }
    )


#    _                            _
#   |_    ._   _ _|_ o  _  ._    | \  _   _ |
#   | |_| | | (_  |_ | (_) | |   |_/ (/_ (_ |
#
@type_enforced.Enforcer
def parse_argument(c: clang.cindex.Cursor, t: clang.cindex.Type | None = None):
    if t is None:
        t = c.type
    d_type = {"type": parse_type(t)}
    if not c.spelling:
        return d_type
    return {"name": c.spelling} | d_type


@type_enforced.Enforcer
def parse_function_decl(c: clang.cindex.Cursor):
    d = {"name": c.spelling, "type": parse_type(c.type.get_result())}
    if params := [parse_argument(a) for a in c.get_arguments()]:
        d["params"] = params

    DECLARATIONS["functions"].append(d)


@type_enforced.Enforcer
def parse_function_proto(t: clang.cindex.Type, c: clang.cindex.Cursor):
    d = {"type": parse_type(t.get_result())}

    # https://stackoverflow.com/questions/79356416/how-can-i-get-the-argument-names-of-a-function-types-argument-list
    childrens = list(c.get_children())
    assert len(childrens) == len(t.argument_types())
    if params := [parse_argument(*a) for a in zip(childrens, t.argument_types())]:
        d["params"] = params
    return d


#                          __                    _
#   | | ._  o  _  ._      (_ _|_ ._     _ _|_   | \  _   _ |
#   |_| | | | (_) | | o   __) |_ | |_| (_  |_   |_/ (/_ (_ |
#                     /
# `typedef struct` will recurse twice into this function:
# - One for typedef `TYPEDEF_DECL.underlying_typedef_type`
# - and one for `STRUCT_DECL`
# so we cache to avoid appending twice to DECLARATIONS['structs']
@type_enforced.Enforcer
def parse_struct_union_decl(c: clang.cindex.Cursor, name_decl: str):
    def parse_field(c):
        match k := c.kind:
            case clang.cindex.CursorKind.FIELD_DECL:
                # If case of record, the field have no name
                d_type = {"type": parse_type(c.type)}
                if c.is_anonymous():
                    return d_type
                return {"name": c.spelling} | d_type
            case _:  # pragma: no cover
                raise NotImplementedError(f"parse_field: {k}")

    # Hoisting
    d_members = {"members": [parse_field(f) for f in c.type.get_fields()]}
    if c.is_anonymous():
        return d_members
    d_name = {"name": c.spelling}
    DECLARATIONS[name_decl].append(d_name | d_members)
    return d_name


@cache
@type_enforced.Enforcer
def parse_struct_decl(c: clang.cindex.Cursor):
    return parse_struct_union_decl(c, "structs")


@cache
@type_enforced.Enforcer
def parse_union_decl(c: clang.cindex.Cursor):
    return parse_struct_union_decl(c, "unions")


#    _                  _
#   |_ ._      ._ _    | \  _   _ |
#   |_ | | |_| | | |   |_/ (/_ (_ |
#


@cache
@type_enforced.Enforcer
def parse_enum_decl(c: clang.cindex.Cursor):
    # Enum cannot be nested

    def parse_enum_member(c):
        return {"name": c.spelling, "val": c.enum_value}

    # Hoisting
    d_members = {"members": [parse_enum_member(f) for f in c.get_children()]}
    # Check of anonymous `enum`
    # Black Magic: https://stackoverflow.com/a/35184821
    if "@EA@" in c.get_usr():
        return d_members
    d_name = {"name": c.spelling}
    DECLARATIONS["enums"].append(d_name | d_members)
    return d_name


#   ___
#    | ._ _. ._   _ |  _. _|_ o  _  ._    | | ._  o _|_
#    | | (_| | | _> | (_|  |_ | (_) | |   |_| | | |  |_
#
def parse_translation_unit(t):
    user_children = [c for c in t.get_children() if not c.location.is_in_system_header]
    for c in user_children:
        parse_decl(c)


#
#   |\/|  _. o ._
#   |  | (_| | | |
#
def h2yaml_main(path, *args, **kwargs):
    # clang.cindex.Config.set_library_file(
    #    "/opt/aurora/24.180.3/frameworks/aurora_nre_models_frameworks-2024.2.1_u1/lib/python3.10/site-packages/clang/native/libclang.so"
    # )
    global DECLARATIONS
    DECLARATIONS = {
        "structs": [],
        "unions": [],
        "typedefs": [],
        "declarations": [],
        "functions": [],
        "enums": [],
    }

    t = clang.cindex.Index.create().parse(path, *args, **kwargs).cursor
    parse_translation_unit(t)

    d = {k: v for k, v in DECLARATIONS.items() if v}
    return yaml.dump(
        d,
        sort_keys=False,
        explicit_start=True,
    ).strip()


if __name__ == "__main__":  # pragma: no cover
    print(h2yaml_main(sys.argv[1], args=sys.argv[2:]))
