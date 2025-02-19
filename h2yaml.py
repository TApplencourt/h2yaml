import sys
from functools import cache
import clang.cindex
import yaml

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


def parse_type(t):
    match k := t.kind:
        # node.type.spelling ??
        case _ if kind := THAPI_types.get(k):
            return {"kind": kind, "name": t.spelling}
        case clang.cindex.CursorKind.STRUCT_DECL:
            return {"kind": "struct"} | parse_union_struct_decl(t)
        case clang.cindex.CursorKind.UNION_DECL:
            return {"kind": "union"} | parse_union_struct_decl(t)
        case clang.cindex.TypeKind.POINTER:
            return {"kind": "pointer", "type": parse_type(t.get_pointee())}
        case clang.cindex.TypeKind.ELABORATED | clang.cindex.TypeKind.RECORD:
            return parse_type(t.get_declaration())
        case clang.cindex.TypeKind.FUNCTIONPROTO:
            return {"kind": "function"} | parse_function_proto(t)
        case _:  # pragma: no cover
            raise NotImplementedError(f"parse_type: {k}")


#   ___                    _    _
#    |    ._   _   _|  _ _|_   | \  _   _ |
#    | \/ |_) (/_ (_| (/_ |    |_/ (/_ (_ |
#      /  |
def parse_typedef_decl(t):
    DECLARATIONS["typedefs"].append(
        {
            "name": t.spelling,
            "type": parse_type(t.underlying_typedef_type),
        }
    )


#                 _
#   \  / _. ._   | \  _   _ |
#    \/ (_| |    |_/ (/_ (_ |
#
def parse_var_decl(t):
    DECLARATIONS["declarations"].append(
        {
            "name": t.spelling,
            "type": parse_type(t.type),
        }
    )


#    _                            _
#   |_    ._   _ _|_ o  _  ._    | \  _   _ |
#   | |_| | | (_  |_ | (_) | |   |_/ (/_ (_ |
#
def parse_function_decl(t):
    def parse_argument(t):
        if not t.spelling:
            return {
                "type": parse_type(t.type),
            }
        return {
            "name": t.spelling,
            "type": parse_type(t.type),
        }

    d = {"name": t.spelling, "type": parse_type(t.type.get_result())}
    if params := [parse_argument(a) for a in t.get_arguments()]:
        d["params"] = params

    DECLARATIONS["functions"].append(d)


def parse_function_proto(t):
    def parse_argument_type(t):
        return {"type": parse_type(t)}

    d = {"type": parse_type(t.get_result())}
    if params := [parse_argument_type(a) for a in t.argument_types()]:
        d["params"] = params

    return d


#                          __                    _
#   | | ._  o  _  ._      (_ _|_ ._     _ _|_   | \  _   _ |
#   |_| | | | (_) | | o   __) |_ | |_| (_  |_   |_/ (/_ (_ |
#                     /
# `typedef struct` will recurse twice into this function:
# - One for typedef `TYPEDEF_DECL.underlying_typedef_type`
# - and one for `STRUCT_DECL`
# so we cache to avoid appending twice to DECLARATIONS
@cache
def parse_union_struct_decl(t):
    def parse_field(t):
        match k := t.kind:
            case clang.cindex.CursorKind.FIELD_DECL:
                # If case of record, the field have no name
                if t.is_anonymous():
                    return {"type": parse_type(t.type)}
                return {"name": t.spelling, "type": parse_type(t.type)}
            case _:  # pragma: no cover
                raise NotImplementedError(f"parse_field: {k}")

    # Hoisting
    members = [parse_field(f) for f in t.type.get_fields()]

    # Anonymous so need to get members, we cannot hoist
    if t.is_anonymous():
        return {"members": members}
    # They have a name, they should:
    # - be part of the `structs`
    # - and when parents ask for it, just returning the `name`
    DECLARATIONS["structs"].append({"name": t.spelling, "members": members})
    return {"name": t.spelling}


#   ___
#    | ._ _. ._   _ |  _. _|_ o  _  ._    | | ._  o _|_
#    | | (_| | | _> | (_|  |_ | (_) | |   |_| | | |  |_
#
def parse_translation_unit(t):
    user_children = [c for c in t.get_children() if not c.location.is_in_system_header]
    for c in user_children:
        match k := c.kind:
            case clang.cindex.CursorKind.STRUCT_DECL:
                parse_union_struct_decl(c)
            case clang.cindex.CursorKind.TYPEDEF_DECL:
                parse_typedef_decl(c)
            case clang.cindex.CursorKind.VAR_DECL:
                parse_var_decl(c)
            case clang.cindex.CursorKind.FUNCTION_DECL:
                parse_function_decl(c)
            case _:  # pragma: no cover
                raise NotImplementedError(f"parse_translation_unit: {k}")


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
