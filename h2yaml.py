import sys
from functools import cache, wraps
import clang.cindex
import yaml
import type_enforced
import os
import subprocess
from _collections_abc import list_iterator


def cache_first_arg(func):
    cache = func.cache = {}

    @wraps(func)
    def memoizer(arg1, *args):
        if arg1 not in cache:
            cache[arg1] = func(arg1, *args)
        return cache[arg1]

    return memoizer


@property
def is_in_system_header2(self):
    if self.is_in_system_header:
        return True

    basename = os.path.basename(self.file.name)
    return any(basename.startswith(s) for s in ["std", "__std"])


clang.cindex.SourceLocation.is_in_system_header2 = is_in_system_header2

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
def parse_type(t: clang.cindex.Type, cursors: list_iterator | None = None):
    d_qualified = {}
    if t.is_const_qualified():
        d_qualified["const"] = True
    if t.is_volatile_qualified():
        d_qualified["volatile"] = True
    if t.is_restrict_qualified():
        d_qualified["restrict"] = True
    match k := t.kind:
        case _ if kind := THAPI_types.get(k):
            names = [s for s in t.spelling.split() if s not in d_qualified]
            return {"kind": kind, "name": " ".join(names)} | d_qualified
        case clang.cindex.TypeKind.POINTER:
            return (
                {"kind": "pointer"}
                | d_qualified
                | {"type": parse_type(t.get_pointee(), cursors)}
            )
        case clang.cindex.TypeKind.ELABORATED:
            next(cursors)
            decl = t.get_declaration()
            return parse_decl(decl, decl.get_children()) | d_qualified
        case clang.cindex.TypeKind.RECORD:
            return parse_decl(t.get_declaration())
        case clang.cindex.TypeKind.CONSTANTARRAY:
            return {
                "kind": "array",
                "type": parse_type(t.element_type, cursors),
                "length": t.element_count,
            }
        case clang.cindex.TypeKind.INCOMPLETEARRAY:
            return {"kind": "array", "type": parse_type(t.element_type)}
        case clang.cindex.TypeKind.FUNCTIONPROTO:
            return {"kind": "function"} | parse_function_proto(t, cursors)
        case _:  # pragma: no cover
            raise NotImplementedError(f"parse_type: {k}")


@type_enforced.Enforcer
def parse_decl(c: clang.cindex.Cursor, cursors: list_iterator | None = None):
    match k := c.kind:
        case clang.cindex.CursorKind.STRUCT_DECL:
            return {"kind": "struct"} | parse_struct_decl(c)
        case clang.cindex.CursorKind.UNION_DECL:
            return {"kind": "union"} | parse_union_decl(c)
        case clang.cindex.CursorKind.ENUM_DECL:
            return {"kind": "enum"} | parse_enum_decl(c)
        case clang.cindex.CursorKind.TYPEDEF_DECL:
            return {"kind": "custom_type"} | parse_typedef_decl(c, cursors)
        case clang.cindex.CursorKind.FUNCTION_DECL:
            return parse_function_decl(c, cursors)
        case clang.cindex.CursorKind.VAR_DECL:
            return parse_var_decl(c)
        case _:  # pragma: no cover
            raise NotImplementedError(f"parse_decl: {k}")


#   ___                    _    _
#    |    ._   _   _|  _ _|_   | \  _   _ |
#    | \/ |_) (/_ (_| (/_ |    |_/ (/_ (_ |
#      /  |
@cache_first_arg
@type_enforced.Enforcer
def parse_typedef_decl(c: clang.cindex.Cursor, cursors: list_iterator | None = None):
    name = {"name": c.spelling}
    # Stop recursing, and don't append if
    # the typedef is defined by system header
    if not (c.location.is_in_system_header2):
        type_ = parse_type(c.underlying_typedef_type, cursors)
        DECLARATIONS["typedefs"].append(name | {"type": type_})
    return name


#                 _
#   \  / _. ._   | \  _   _ |
#    \/ (_| |    |_/ (/_ (_ |
#
@type_enforced.Enforcer
def parse_var_decl(c: clang.cindex.Cursor):
    # Assume all INCOMPLETEARRAY types will eventually be completed.
    # This works because libclang treats `a[]` as:
    # `tentative array definition assumed to have one element`
    # As a result, it will be parsed as a `CONSTANTARRAY`
    if c.type.kind == clang.cindex.TypeKind.INCOMPLETEARRAY:
        return

    d = {
        "name": c.spelling,
        "type": parse_type(c.type, c.get_children()),
    }

    match t := c.storage_class:
        case clang.cindex.StorageClass.EXTERN:
            d["storage"] = "extern"
        case clang.cindex.StorageClass.NONE:
            pass
        case _:  # pragma: no cover
            raise NotImplementedError(f"parse_var_decl_storage_class: {t}")

    DECLARATIONS["declarations"].append(d)


#    _                            _
#   |_    ._   _ _|_ o  _  ._    | \  _   _ |
#   | |_| | | (_  |_ | (_) | |   |_/ (/_ (_ |
#
@type_enforced.Enforcer
def parse_argument(c: clang.cindex.Cursor, t: clang.cindex.Type | None = None):
    if t is None:
        t = c.type
    d_type = {"type": parse_type(t, c.get_children())}
    # We don't use `s.is_anonymous`, as for `void (*a5)(double a, int);`
    # The double `double a` will be named as anonymous
    # We don't use `not s.spelling` due to the "feature" of libclang,
    # where in (*a6)(a6_t) the spelling of `a6_t` will be a6_t
    if not c.get_usr():
        return d_type
    return {"name": c.spelling} | d_type


@type_enforced.Enforcer
def parse_function_decl(c: clang.cindex.Cursor, cursors: list_iterator | None = None):
    d = {"name": c.spelling, "type": parse_type(c.type.get_result(), cursors)}
    if params := [parse_argument(a) for a in c.get_arguments()]:
        d["params"] = params
    if c.type.is_function_variadic():
        d["var_args"] = True

    DECLARATIONS["functions"].append(d)


@type_enforced.Enforcer
def parse_function_proto(t: clang.cindex.Type, cursors: list_iterator | None = None):
    d = {"type": parse_type(t.get_result(), cursors)}
    # https://stackoverflow.com/questions/79356416/how-can-i-get-the-argument-names-of-a-function-types-argument-list

    # In the case where one params is of type ELABORATED, `c` will have "too much" children
    # (eg `CursorKind.TYPE_REF` and the `CursorKind.PARM_DECL`
    arg_types = t.argument_types()
    arg_cursors = [next(cursors) for _ in arg_types]

    if params := [parse_argument(*a) for a in zip(arg_cursors, arg_types)]:
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
                d = {"type": parse_type(c.type, c.get_children())}
                if c.is_bitfield():
                    d |= {"num_bits": c.get_bitfield_width()}
                # Some case can be `anonymous`:
                # - unnamed struct will have "anonymous ..."  in `spelling`, but `is_anonymous()` will be true
                # - unnamed bitfield will have `is_anonymous()` will be `false`, but spelling will be empty
                if c.is_anonymous() or not c.spelling:
                    return d
                return {"name": c.spelling} | d
            case _:  # pragma: no cover
                raise NotImplementedError(f"parse_field: {k}")

    # typedef struct A8 a8 is a valid c syntax;
    d_members = {}
    if members := [parse_field(f) for f in c.type.get_fields()]:
        d_members["members"] = members

    # Hoisting
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
        d = {"name": c.spelling}
        tokens = [t.spelling for t in c.get_tokens()]
        if "=" in tokens:
            d["val"] = "".join(tokens[2:])
        else:
            assert len(tokens) == 1 and c.enum_value == 0
        return d

    # Hoisting
    d_members = {"members": [parse_enum_member(f) for f in c.get_children()]}
    # Check of anonymous `enum`
    # Black Magic: https://stackoverflow.com/a/35184821
    # Unclear what the case of `a` mean
    if any(anonymous in c.get_usr() for anonymous in ["@EA@", "@Ea@"]):
        return d_members
    d_name = {"name": c.spelling}
    DECLARATIONS["enums"].append(d_name | d_members)
    return d_name


#   ___
#    | ._ _. ._   _ |  _. _|_ o  _  ._    | | ._  o _|_
#    | | (_| | | _> | (_|  |_ | (_) | |   |_| | | |  |_
#
def parse_translation_unit(t):
    user_children = [c for c in t.get_children() if not c.location.is_in_system_header2]
    for c in user_children:
        parse_decl(c, c.get_children())


#
#   |\/|  _. o ._
#   |  | (_| | | |
#
def check_diagnostic(t):
    error = 0
    for diagnostic in t.diagnostics:
        print(f"clang diagnostic: {diagnostic}", file=sys.stderr)
        # diagnostic message can contain "error" or "warning"
        error += "error" in str(diagnostic)
    if error:  # pragma: no cover // No negatif test yet
        sys.exit(1)


class SystemIncludes:
    # Our libclang version may differ from the "normal" compiler used by the system.
    # This means we may lack the `isystem` headers that the user expects.
    # We use the `$CC` environment variable to detect these headers and add them to our include path.
    @staticmethod
    @cache
    def get_paths():
        if not (cc := os.getenv("CC")):  # pragma: no cover
            return []

        text = subprocess.check_output(
            f"{cc} -E -Wp,-v -xc /dev/null",
            shell=True,
            text=True,
            stderr=subprocess.STDOUT,
        )
        start_string = "#include <...> search starts here:"
        start_index = text.find(start_string) + len(start_string)
        end_index = text.find("End of search list.", start_index)
        return text[start_index:end_index].split()

    @classmethod
    @property
    def paths(cls):
        return cls.get_paths()


def h2yaml(path, args=[]):
    global DECLARATIONS
    DECLARATIONS = {
        "structs": [],
        "unions": [],
        "typedefs": [],
        "declarations": [],
        "functions": [],
        "enums": [],
    }
    args += [f"-I{p}" for p in SystemIncludes.paths]

    translation_unit = clang.cindex.Index.create().parse(path, args=args)
    check_diagnostic(translation_unit)
    parse_translation_unit(translation_unit.cursor)

    d = {k: v for k, v in DECLARATIONS.items() if v}
    return yaml.dump(
        d,
        sort_keys=False,
        explicit_start=True,
    ).strip()


if __name__ == "__main__":  # pragma: no cover
    print(h2yaml(sys.argv[1], args=sys.argv[2:]))
