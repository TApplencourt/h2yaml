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


def next_non_attribute(cursors):
    c = next(cursors)
    if not c.kind.is_attribute():
        return c
    return next_non_attribute(cursors)


@type_enforced.Enforcer
def diagnostic_prefix(c: clang.cindex.Cursor):
    l = c.location
    return f"h2yaml diagnostic: {l.file}:{l.line}:{l.column}"


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
    def is_in_usr(targets):
        return any(t in self.get_usr() for t in targets)

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
            return self.is_anonymous() or is_in_usr(["@EA@", "@Ea@"])
        case clang.cindex.CursorKind.STRUCT_DECL:
            # Fix typedef struct {int a } A9_t, where the `struct` is not anonynous
            return self.is_anonymous() or is_in_usr(["@SA@", "@Sa@"])
        case _:
            return self.is_anonymous()


def is_inline_specifier(self):
    assert self.kind == clang.cindex.CursorKind.FUNCTION_DECL
    return any(token.spelling == "inline" for token in self.get_tokens())


clang.cindex.SourceLocation.is_in_system_header2 = is_in_system_header2
clang.cindex.Cursor.is_anonymous2 = is_anonymous2
clang.cindex.Cursor.is_inline_specifier = is_inline_specifier


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
def parse_function_proto_type(t: clang.cindex.Type, cursors: list_iterator):
    # https://stackoverflow.com/questions/79356416/how-can-i-get-the-argument-names-of-a-function-types-argument-list
    def parse_parm_type(t: clang.cindex.Type, cursors: list_iterator):
        c = next_non_attribute(cursors)
        d_type = {"type": parse_type(t, c.get_children())}
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
def parse_type(t: clang.cindex.Type, cursors: list_iterator):
    d_qualified = {}
    if t.is_const_qualified():
        d_qualified["const"] = True
    if t.is_volatile_qualified():
        d_qualified["volatile"] = True
    if t.is_restrict_qualified():
        d_qualified["restrict"] = True

    match k := t.kind:
        case _ if kind := THAPI_types.get(k):
            names = (s for s in t.spelling.split() if s not in d_qualified)
            return {"kind": kind, "name": " ".join(names)} | d_qualified
        case clang.cindex.TypeKind.POINTER:
            return {
                "kind": "pointer",
                "type": parse_type(t.get_pointee(), cursors),
            } | d_qualified
        case clang.cindex.TypeKind.ELABORATED:
            next_non_attribute(cursors)
            decl = t.get_declaration()
            return parse_decl(decl, decl.get_children()) | d_qualified
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
# `cursors` is an iterator, so impossible to cache
@cache_first_arg
@type_enforced.Enforcer
def parse_typedef_decl(c: clang.cindex.Cursor, cursors: list_iterator):
    d_name = {"name": c.spelling}
    # Stop recursing, and don't append if
    # the typedef is defined by system header
    if not c.location.is_in_system_header2:
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
    # This works because libclang treats `a[]` as:
    # `tentative array definition assumed to have one element`
    # As a result, it will be parsed as a `CONSTANTARRAY`
    if c.type.kind == clang.cindex.TypeKind.INCOMPLETEARRAY:
        return

    d = {
        "name": c.spelling,
        "type": parse_type(c.type, c.get_children()),
    } | parse_storage_class(c)

    DECLARATIONS["declarations"].append(d)


#    _                            _
#   |_    ._   _ _|_ o  _  ._    | \  _   _ |
#   | |_| | | (_  |_ | (_) | |   |_/ (/_ (_ |
#
@type_enforced.Enforcer
def parse_function_decl(c: clang.cindex.Cursor, cursors: list_iterator):
    if c.is_definition():
        print(
            f"{diagnostic_prefix(c)}: Warning: `{c.spelling}` is a function definition and will be ignored.",
            file=sys.stderr,
        )
        return {}

    d = {"name": c.spelling} | parse_storage_class(c)

    if c.is_inline_specifier():
        d["inline"] = True

    match t := c.type.kind:
        case clang.cindex.TypeKind.FUNCTIONNOPROTO:
            print(
                f"{diagnostic_prefix(c)}: Warning: Did you forget `void` for your no-parameters function `{c.spelling}`?",
                file=sys.stderr,
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
        d = {"type": parse_type(c.type, c.get_children())}
        if c.is_bitfield():
            d["num_bits"] = c.get_bitfield_width()
        if c.is_anonymous2():
            return d
        return {"name": c.spelling} | d

    # typedef struct A8 a8 is a valid c syntax;
    # But we should not append it to `structs` as it's undefined
    d_name = {"name": c.spelling}
    if not (members := [parse_field_decl(f) for f in c.type.get_fields()]):
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

    d_members = {"members": [parse_enum_constant_del(f) for f in c.get_children()]}
    d_name = {"name": c.spelling} if not c.is_anonymous2() else {}
    DECLARATIONS["enums"].append(d_name | d_members)
    return d_name


#   ___
#    | ._ _. ._   _ |  _. _|_ o  _  ._    | | ._  o _|_
#    | | (_| | | _> | (_|  |_ | (_) | |   |_| | | |  |_
#
def parse_translation_unit(t: clang.cindex.Cursor):
    assert t.kind == clang.cindex.CursorKind.TRANSLATION_UNIT
    global DECLARATIONS
    DECLARATIONS = {
        k: []
        for k in ("structs", "unions", "typedefs", "declarations", "functions", "enums")
    }

    user_children = (c for c in t.get_children() if not c.location.is_in_system_header2)
    for c in user_children:
        # Modify `DECLARATIONS`
        parse_decl(c, c.get_children())
    return {k: v for k, v in DECLARATIONS.items() if v}


#
#   |\/|  _. o ._
#   |  | (_| | | |
#
def h2yaml(path, args=[], unsaved_files=None):
    si_args = [f"-I{p}" for p in SystemIncludes.paths]
    translation_unit = clang.cindex.Index.create().parse(
        path, args=args + si_args, unsaved_files=unsaved_files
    )
    check_diagnostic(translation_unit)
    decls = parse_translation_unit(translation_unit.cursor)
    return yaml.dump(decls)


def main():  # pragma: no cover
    if len(sys.argv) == 1:
        print(f"USAGE: {sys.argv[0]} [options] file")
        sys.exit(1)

    *c_args, file = sys.argv[1:]
    args = ["tmp.h", c_args, [("tmp.h", sys.stdin)]] if file == "-" else [file, c_args]
    yml = h2yaml(*args)
    print(yml, end="")


if __name__ == "__main__":  # pragma: no cover
    main()
