import sys
from functools import cache, wraps
import clang.cindex
import yaml
import type_enforced
import os
import subprocess
from _collections_abc import list_iterator


class classproperty(property):
    def __get__(self, owner_self, owner_cls):
        return self.fget(owner_cls)


def cache_first_arg(func):
    cache = func.cache = {}

    @wraps(func)
    def memoizer(arg1, *args):
        if arg1 not in cache:
            cache[arg1] = func(arg1, *args)
        return cache[arg1]

    return memoizer


class SystemIncludes:
    # Our libclang version may differ from the "normal" compiler used by the system.
    # This means we may lack the `isystem` headers that the user expects.
    # We use the `$CC` environment variable to detect these headers and add them to our include path.
    @classproperty
    def paths(cls):
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


@type_enforced.Enforcer
def check_diagnostic(t: clang.cindex.TranslationUnit):
    error = 0
    for diagnostic in t.diagnostics:
        print(f"clang diagnostic: {diagnostic}", file=sys.stderr)
        # diagnostic message can contain "error" or "warning"
        error += "error" in str(diagnostic)
    if error:  # pragma: no cover // No negatif test yet
        sys.exit(1)


#    _ ___                   _
#   /   |  ._   _|  _       |_   _|_  _  ._   _ o  _  ._
#   \_ _|_ | | (_| (/_ ><   |_ >< |_ (/_ | | _> | (_) | |
#
@property
def is_in_system_header2(self):
    if self.is_in_system_header:
        return True
    basename = os.path.basename(self.file.name)
    return any(basename.startswith(s) for s in ["std", "__std"])


def is_anonymous2(self):
    is_usr_contain = lambda targets: any(t in self.get_usr() for t in targets)

    match self.kind:
        case clang.cindex.CursorKind.PARM_DECL:
            # `is_anonymous` for `double a` in `void (*a5)(double a, int);` will return True.
            # We don't use `not spelling` anymore due to the "feature" of libclang,
            #   where in (*a6)(a6_t) the spelling of `a6_t` will be `a6_t` and not `None`
            return not (self.get_usr())
        case clang.cindex.CursorKind.FIELD_DECL:
            # - unnamed struct will have "anonymous ..."  in `spelling`, but `is_anonymous` will be true
            # - named struct in union will be considered anonymous
            # - unnamed bitfield will have `is_anonymous` be `false`, but spelling will be empty
            return not self.spelling or "(anonymous at" in self.spelling
        case clang.cindex.CursorKind.ENUM_DECL:
            # Black Magic: https://stackoverflow.com/a/35184821
            # Unclear what the case of `a` represent
            return is_usr_contain(["@EA@", "@Ea@"])
        case clang.cindex.CursorKind.STRUCT_DECL:
            # Fix typedef struct {int a } A9_t, where the `struct` is not anonynous
            return self.is_anonymous() or is_usr_contain(["@SA@", "@Sa@"])
        case _:
            return self.is_anonymous()


clang.cindex.SourceLocation.is_in_system_header2 = is_in_system_header2
clang.cindex.Cursor.is_anonymous2 = is_anonymous2

#    _                ___
#   |_) _. ._ _  _     |    ._   _
#   |  (_| | _> (/_    | \/ |_) (/_
#                        /  |
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
    clang.cindex.TypeKind.BOOL: "bool",
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


#    _                 _
#   |_) _. ._ _  _    | \  _   _ |
#   |  (_| | _> (/_   |_/ (/_ (_ |
#
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
    if not c.location.is_in_system_header2:
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
    if c.is_anonymous2():
        return d_type
    return {"name": c.spelling} | d_type


@type_enforced.Enforcer
def parse_function_decl(c: clang.cindex.Cursor, cursors: list_iterator | None = None):
    d = {"name": c.spelling, "type": parse_type(c.type.get_result(), cursors)}
    if params := [parse_argument(a) for a in c.get_arguments()]:
        d["params"] = params

    match t := c.type.kind:
        case clang.cindex.TypeKind.FUNCTIONNOPROTO:
            l = c.location
            prefix = f"clang diagnostic: {l.file}:{l.line}:{l.column} warning:"
            print(
                f"{prefix}: Did you forget `void` for your no-parameters function `{c.spelling}`?",
                file=sys.stderr,
            )
        case clang.cindex.TypeKind.FUNCTIONPROTO:
            if c.type.is_function_variadic():
                d["var_args"] = True
        case _:  # pragma: no cover
            raise NotImplementedError(f"parse_function_decl: {t}")

    DECLARATIONS["functions"].append(d)


@type_enforced.Enforcer
def parse_function_proto(t: clang.cindex.Type, cursors: list_iterator | None = None):
    d = {"type": parse_type(t.get_result(), cursors)}

    # https://stackoverflow.com/questions/79356416/how-can-i-get-the-argument-names-of-a-function-types-argument-list
    arg_types = t.argument_types()
    arg_cursors = [next(cursors) for _ in arg_types]

    if params := [parse_argument(*a) for a in zip(arg_cursors, arg_types)]:
        d["params"] = params

    if t.is_function_variadic():
        d["var_args"] = True
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
        assert c.kind == clang.cindex.CursorKind.FIELD_DECL
        d = {"type": parse_type(c.type, c.get_children())}
        if c.is_bitfield():
            d["num_bits"] = c.get_bitfield_width()
        if c.is_anonymous2():
            return d
        return {"name": c.spelling} | d

    # typedef struct A8 a8 is a valid c syntax;
    # But we should not append it to `structs` as it's undefined
    d_name = {"name": c.spelling}
    if not (members := [parse_field(f) for f in c.type.get_fields()]):
        return d_name
    d_members = {"members": members}
    # Hoisting
    if c.is_anonymous2():
        return d_members
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
        if "=" in (tokens := [t.spelling for t in c.get_tokens()]):
            d["val"] = "".join(tokens[2:])
        else:
            assert len(tokens) == 1
        return d

    # Hoisting
    d_members = {"members": [parse_enum_member(f) for f in c.get_children()]}
    if c.is_anonymous2():
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
    )


if __name__ == "__main__":  # pragma: no cover
    print(h2yaml(sys.argv[1], args=sys.argv[2:]))
