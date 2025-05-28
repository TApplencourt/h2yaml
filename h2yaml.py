from functools import cache, cached_property, wraps
from typing import Callable
import sys
import clang.cindex
import yaml
import os
import subprocess
import re

try:
    import type_enforced
except ModuleNotFoundError:  # pragma: no cover
    # This branch is not always hit during tests coverage
    # since required dependencies are installed
    class type_enforced:
        def Enforcer(f: Callable):
            return f
#
#   | | _|_ o |  _
#   |_|  |_ | | _>
#


class classproperty(property):
    def __get__(self, owner_self, owner_cls):
        return self.fget(owner_cls)


def cache_using_first_arg(f: Callable):
    cache = f.cache = {}

    @wraps(f)
    def memoizer(arg1, *args):
        if arg1 not in cache:
            cache[arg1] = f(arg1, *args)
        return cache[arg1]

    return memoizer


def next_non_attribute(cursors):
    for c in cursors:
        if not c.kind.is_attribute():
            return c


@type_enforced.Enforcer
def h2yaml_warning(c: clang.cindex.Cursor, msg):
    l = c.location
    prefix = f"h2yaml diagnostic: {l.file}:{l.line}:{l.column}"
    print(
        f"{prefix}: Warning: {msg}",
        file=sys.stderr,
    )


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
    error = False
    for diagnostic in t.diagnostics:
        print(f"clang diagnostic: {diagnostic}", file=sys.stderr)
        # diagnostic message can contain "error" or "warning"
        error |= "error" in str(diagnostic)
    if error:  # pragma: no cover # No negatif tests yet
        sys.exit(1)


#    _ ___                   _
#   /   |  ._   _|  _       |_   _|_  _  ._   _ o  _  ._
#   \_ _|_ | | (_| (/_ ><   |_ >< |_ (/_ | | _> | (_) | |
#
@cached_property
def is_in_interesting_header(self):
    # Note: This function uses the global variable PATTERN_INTERESTING_HEADER.

    # Skip system headers
    if self.is_in_system_header:
        return False
    # Skip standard library headers
    basename = os.path.basename(self.file.name)
    if any(basename.startswith(s) for s in ["std", "__std"]):
        return False
    # Apply user-defined white-list pattern
    return re.search(PATTERN_INTERESTING_HEADER, basename)


ccs = clang.cindex.SourceLocation
ccs.is_in_interesting_header = is_in_interesting_header
# TypeError: Cannot use cached_property instance without calling __set_name__ on it.
ccs.is_in_interesting_header.__set_name__(ccs, "is_in_interesting_header")


def is_anonymous2(self):
    def is_in_usr(targets):
        return any(t in self.get_usr() for t in targets)

    match self.kind:
        case clang.cindex.CursorKind.PARM_DECL:
            # `is_anonymous()` returns True for `double a` in `void (*a5)(double a, int);`.
            # We no longer use `not spelling` trick to due to a libclang quirk:
            # In `(*a6)(a6_t)`, the spelling of `a6_t` will be `a6_t` instead of None.
            return not self.get_usr()
        case clang.cindex.CursorKind.FIELD_DECL:
            # - Unnamed structs have "anonymous ..." in `spelling`, and `is_anonymous()` returns True.
            # - Named structs within unions: `is_anonymous()` returns True.
            # - Unnamed bitfields: `is_anonymous()` returns False, but `spelling` is empty.
            return not self.spelling or "(anonymous at" in self.spelling
        case clang.cindex.CursorKind.ENUM_DECL:
            # Fix for `struct S2 { enum { H0 } a; }` where `is_anonymous()` returns False for the enum.
            # Fortunately, Clang uses `@EA@` and `@Ea@` in the USR for anonymous enums.
            # (Though I never saw `@Ea@`...)
            return self.is_anonymous() or is_in_usr(["@EA@", "@Ea@"])
        case clang.cindex.CursorKind.STRUCT_DECL:
            # Fix for `typedef struct { int a; } A9_t;`, where `is_anonymous()` returns False for the struct.
            # Fortunately, Clang uses `@SA@` and `@Sa@` in the USR for anonymous structs.
            return self.is_anonymous() or is_in_usr(["@SA@", "@Sa@"])
        case _:
            return self.is_anonymous()


clang.cindex.Cursor.is_anonymous2 = is_anonymous2


def is_inline_specifier(self):
    assert self.kind == clang.cindex.CursorKind.FUNCTION_DECL
    return any(token.spelling == "inline" for token in self.get_tokens())


def get_interesting_children(self):
    for c in self.get_children():
        if self.location.is_in_interesting_header:
            yield c


clang.cindex.Cursor.is_inline_specifier = is_inline_specifier
clang.cindex.Cursor.get_interesting_children = get_interesting_children


#    _                 __                         _
#   |_) _. ._ _  _    (_ _|_  _  ._ _.  _   _    /  |  _.  _  _
#   |  (_| | _> (/_   __) |_ (_) | (_| (_| (/_   \_ | (_| _> _>
#                                       _|
@type_enforced.Enforcer
def parse_storage_class(c: clang.cindex.Cursor):
    match sc := c.storage_class:
        case clang.cindex.StorageClass.EXTERN:
            return {"storage": "extern"}
        case clang.cindex.StorageClass.STATIC:
            return {"storage": "static"}
        case clang.cindex.StorageClass.NONE:
            return {}
        case _:  # pragma: no cover
            raise NotImplementedError(f"parse_storage_class: {sc}")


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
def parse_function_proto_type(t: clang.cindex.Type, cursors: Callable):
    # https://stackoverflow.com/questions/79356416/how-can-i-get-the-argument-names-of-a-function-types-argument-list
    def parse_parm_type(t: clang.cindex.Type, cursors: Callable):
        c = next_non_attribute(cursors)
        d_type = {"type": parse_type(t, c.get_interesting_children())}
        if c.is_anonymous2():
            return d_type
        return {"name": c.spelling} | d_type

    d = {
        "type": parse_type(t.get_result(), cursors),
        "params": [parse_parm_type(t_, cursors) for t_ in t.argument_types()],
    }

    if t.is_function_variadic():
        d["var_args"] = True
    return d


@type_enforced.Enforcer
def parse_type(t: clang.cindex.Type, cursors: Callable):
    d_qualified = {}
    if t.is_const_qualified():
        d_qualified["const"] = True
    if t.is_volatile_qualified():
        d_qualified["volatile"] = True
    if t.is_restrict_qualified():
        d_qualified["restrict"] = True

    match k := t.kind:
        case _ if kind := THAPI_types.get(k):
            names = list(s for s in t.spelling.split() if s not in d_qualified)
            # Hack to mimic old ruby parser, remove when not needed anymore
            if kind == "int" and "int" not in names:
                names.append("int")
            return {"kind": kind, "name": " ".join(names)} | d_qualified
        case clang.cindex.TypeKind.POINTER:
            return {
                "kind": "pointer",
                "type": parse_type(t.get_pointee(), cursors),
            } | d_qualified
        case clang.cindex.TypeKind.ELABORATED:
            # Move the cursors to keep it in sync which children
            next_non_attribute(cursors)
            decl = t.get_declaration()
            return parse_decl(decl, decl.get_interesting_children()) | d_qualified
        case clang.cindex.TypeKind.RECORD:
            return parse_decl(t.get_declaration())
        case clang.cindex.TypeKind.CONSTANTARRAY:
            return {
                "kind": "array",
                "type": parse_type(t.element_type, cursors),
                "length": t.element_count,
            } | d_qualified
        case clang.cindex.TypeKind.INCOMPLETEARRAY:
            return {
                "kind": "array",
                "type": parse_type(t.element_type, cursors),
            } | d_qualified
        case clang.cindex.TypeKind.FUNCTIONPROTO:
            return {"kind": "function"} | parse_function_proto_type(t, cursors)
        case _:  # pragma: no cover
            raise NotImplementedError(f"parse_type: {k}")


#    _                 _
#   |_) _. ._ _  _    | \  _   _ |
#   |  (_| | _> (/_   |_/ (/_ (_ |
#
@type_enforced.Enforcer
def parse_decl(c: clang.cindex.Cursor, cursors: Callable | None = None):
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
# `cursors` is an iterator, so impossible to cache
@cache_using_first_arg
@type_enforced.Enforcer
def parse_typedef_decl(c: clang.cindex.Cursor, cursors: Callable):
    d_name = {"name": c.spelling}
    # Only call `underlying_typedef_type` if we are interested by the header
    if c.location.is_in_interesting_header:
        d_type = {"type": parse_type(c.underlying_typedef_type, cursors)}
        DECLARATIONS["typedefs"].append(d_name | d_type)
    return d_name


#                 _
#   \  / _. ._   | \  _   _ |
#    \/ (_| |    |_/ (/_ (_ |
#
@type_enforced.Enforcer
def parse_var_decl(c: clang.cindex.Cursor):
    # Assume all INCOMPLETEARRAY types will eventually be completed.
    # This is safe because libclang treats `a[]` as a
    # "tentative array definition assumed to have one element".
    # As a result, such arrays will be also parsed as `CONSTANTARRAY`.
    if c.type.kind == clang.cindex.TypeKind.INCOMPLETEARRAY:
        return

    d = {
        "name": c.spelling,
        "type": parse_type(c.type, c.get_interesting_children()),
    } | parse_storage_class(c)

    DECLARATIONS["declarations"].append(d)


#    _                            _
#   |_    ._   _ _|_ o  _  ._    | \  _   _ |
#   | |_| | | (_  |_ | (_) | |   |_/ (/_ (_ |
#
@type_enforced.Enforcer
def parse_function_decl(c: clang.cindex.Cursor, cursors: Callable):
    if c.is_definition():
        h2yaml_warning(
            c, f"`{c.spelling}` is a function definition and will be ignored."
        )
        return {}

    d = {"name": c.spelling} | parse_storage_class(c)

    if c.is_inline_specifier():
        d["inline"] = True

    match t := c.type.kind:
        case clang.cindex.TypeKind.FUNCTIONNOPROTO:
            h2yaml_warning(
                c,
                f"`{c.spelling}` defines a function with no parameters, consider specifying `void`.",
            )
            d["type"] = parse_type(c.type.get_result(), cursors)
        case clang.cindex.TypeKind.FUNCTIONPROTO:
            d |= parse_function_proto_type(c.type, cursors)
        case _:  # pragma: no cover
            raise NotImplementedError(f"parse_function_decl: {t}")

    DECLARATIONS["functions"].append(d)


#                          __                    _
#   | | ._  o  _  ._      (_ _|_ ._     _ _|_   | \  _   _ |
#   |_| | | | (_) | | o   __) |_ | |_| (_  |_   |_/ (/_ (_ |
#                     /
# `typedef struct|union|enum` will recurse twice into this function:
# - One for typedef `TYPEDEF_DECL.underlying_typedef_type`
# - and one for `STRUCT_DECL`
# so we cache to avoid appending twice to DECLARATIONS['structs']
@type_enforced.Enforcer
def _parse_struct_union_decl(name_decl: str, c: clang.cindex.Cursor):
    def parse_field_decl(c: clang.cindex.Cursor):
        assert c.kind == clang.cindex.CursorKind.FIELD_DECL
        d = {"type": parse_type(c.type, c.get_interesting_children())}
        if c.is_bitfield():
            d["num_bits"] = c.get_bitfield_width()
        if c.is_anonymous2():
            return d
        return {"name": c.spelling} | d

    # typedef struct A8 a8 is a valid c syntax;
    # But we should not append it to `structs` as it's undefined
    d_name = {"name": c.spelling}
    fields = (f for f in c.type.get_fields() if f.location.is_in_interesting_header)
    if not (members := [parse_field_decl(f) for f in fields]):
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
    return _parse_struct_union_decl("structs", c)


@cache
@type_enforced.Enforcer
def parse_union_decl(c: clang.cindex.Cursor):
    return _parse_struct_union_decl("unions", c)


#    _                  _
#   |_ ._      ._ _    | \  _   _ |
#   |_ | | |_| | | |   |_/ (/_ (_ |
#
@cache
@type_enforced.Enforcer
def parse_enum_decl(c: clang.cindex.Cursor):
    def parse_enum_constant_del(c: clang.cindex.Cursor):
        assert c.kind == clang.cindex.CursorKind.ENUM_CONSTANT_DECL
        return {"name": c.spelling, "val": c.enum_value}

    d_members = {
        "members": [parse_enum_constant_del(f) for f in c.get_interesting_children()]
    }
    d_name = {"name": c.spelling} if not c.is_anonymous2() else {}
    DECLARATIONS["enums"].append(d_name | d_members)
    return d_name


#   ___
#    | ._ _. ._   _ |  _. _|_ o  _  ._    | | ._  o _|_
#    | | (_| | | _> | (_|  |_ | (_) | |   |_| | | |  |_
#
def parse_translation_unit(t: clang.cindex.Cursor, pattern):
    assert t.kind == clang.cindex.CursorKind.TRANSLATION_UNIT

    # We need to set some global variable
    global DECLARATIONS
    DECLARATIONS = {
        k: []
        for k in ("structs", "unions", "typedefs", "declarations", "functions", "enums")
    }
    # PATTERN_INTERESTING_HEADER is used in `is_in_interesting_header`
    # to filter out list of header to parse
    global PATTERN_INTERESTING_HEADER
    PATTERN_INTERESTING_HEADER = pattern

    user_children = (c for c in t.get_children() if c.location.is_in_interesting_header)
    for c in user_children:
        # Warning: will modify `DECLARATIONS` global variable
        parse_decl(c, c.get_interesting_children())
    return {k: v for k, v in DECLARATIONS.items() if v}


#
#   |\/|  _. o ._
#   |  | (_| | | |
#
def h2yaml(path, *, clang_args=[], unsaved_files=None, pattern=".*"):
    system_args = [f"-I{p}" for p in SystemIncludes.paths]
    translation_unit = clang.cindex.Index.create().parse(
        path, args=clang_args + system_args, unsaved_files=unsaved_files
    )
    check_diagnostic(translation_unit)
    decls = parse_translation_unit(translation_unit.cursor, pattern)
    return yaml.dump(decls)


def main():  # pragma: no cover
    if (error := len(sys.argv) == 1) or sys.argv[1] == "--help":
        # TODO: `--filter-header` default value should be `file`
        print(
            f"USAGE: {sys.argv[0]} [clang_option...] [--filter-header REGEX] [ file | - ]"
        )
        if error:
            sys.exit(1)
        return

    d_args = {}
    try:
        i = sys.argv.index("--filter-header")
    except ValueError:
        pass
    else:
        del sys.argv[i]
        d_args["pattern"] = sys.argv.pop(i)

    *c_args, file = sys.argv[1:]
    if file != "-":
        d_args["path"] = file
        d_args["clang_args"] = c_args
    else:
        d_args["path"] = "tmp.h"
        d_args["unsaved_files"] = [("tmp.h", sys.stdin)]

    yml = h2yaml(**d_args)
    print(yml, end="")


if __name__ == "__main__":  # pragma: no cover
    main()
