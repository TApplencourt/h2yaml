# /// script
# requires-python = ">= 3.10"
# dependencies = [
#  "pyyaml",
#  "libclang",
# ]
# ///

__version__ = "0.3.0"

from functools import cache, cached_property
from collections import deque
from typing import Callable
import bisect
import sys
import clang.cindex
import yaml
import os
import subprocess
import re
import argparse

try:
    import type_enforced
except ModuleNotFoundError:  # pragma: no cover

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


class PreloadableCache:
    def __init__(self, func):
        self._cached_func = cache(func)
        self._manual_cache = {}

    def preload(self, key, value):
        self._manual_cache[key] = value

    def __call__(self, *args, **kwargs):
        if args in self._manual_cache:
            return self._manual_cache[args]
        return self._cached_func(*args, **kwargs)


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
def check_diagnostic(tu: clang.cindex.TranslationUnit):
    error = False
    for diagnostic in tu.diagnostics:
        print(f"clang diagnostic: {diagnostic}", file=sys.stderr)
        # diagnostic message can contain "error" or "warning"
        error |= "error" in str(diagnostic)
    if error:
        sys.exit(1)


#    _ ___                   _
#   /   |  ._   _|  _       |_   _|_  _  ._   _ o  _  ._
#   \_ _|_ | | (_| (/_ ><   |_ >< |_ (/_ | | _> | (_) | |
#
def attach_to(target):
    """
    Decorator that attaches a function or descriptor (e.g. property, cached_property)
    to a target class.
    Bind `_FOO` to `target.FOO`

    Example:
        @attach_to(clang.cindex.Cursor)
        @cached_property
        def _my_method(self): ...
    """

    def decorator(obj):
        # Get the name for function(__name__), cached property(func), and property(fget)
        try:
            attr_name = obj.__name__
        except AttributeError:
            source = next(o for c in ("func", "fget") if (o := getattr(obj, c, None)))
            attr_name = source.__name__
        finally:
            attr_name = re.sub(r"^_", "", attr_name)
            setattr(target, attr_name, obj)

        # TypeError: Cannot use cached_property instance without calling __set_name__ on it.
        if hasattr(obj, "__set_name__"):
            obj.__set_name__(target, attr_name)

        return obj

    return decorator


# Monkey-patch for missing __hash__ in clang.cindex.Cursor
# See upstream: https://github.com/llvm/llvm-project/pull/132377
# For an unknown reason, `hasattr(clang.cindex.Cursor, "__hash__")` returns True
# so we fall back to using try/except.
try:
    hash(clang.cindex.Cursor())
except TypeError:  # pragma: no cover
    clang.cindex.Cursor.__hash__ = lambda self: self.hash

# Expose libclang `clang_Cursor_isFunctionInlined` C API
try:
    clang.cindex.Cursor().is_function_inlined
except AttributeError:  # pragma: no cover
    clang.cindex.conf.lib.clang_Cursor_isFunctionInlined.restype = bool
    clang.cindex.conf.lib.clang_Cursor_isFunctionInlined.argtypes = [
        clang.cindex.Cursor
    ]

    @attach_to(clang.cindex.Cursor)
    def _is_function_inlined(self):
        return clang.cindex.conf.lib.clang_Cursor_isFunctionInlined(self)


def find_cursors(cursor, kind, depth=-1, include_root=False):
    if include_root and (kind == "*" or cursor.kind == kind):
        yield cursor

    if depth == 0:
        return

    for child in cursor.get_interesting_children():
        yield from find_cursors(child, kind, depth - 1, include_root=True)


@attach_to(clang.cindex.SourceLocation)
@property
def _is_in_interesting_header(self):
    # Note: This function uses the global variable PATTERN_INTERESTING_HEADER.

    # Skip system headers
    if self.is_in_system_header:
        return False

    # Skip Macro
    if not self.file:
        return False

    # Skip standard library headers
    basename = os.path.basename(self.file.name)
    if any(basename.startswith(s) for s in ["std", "__std"]):
        return False
    # Apply user-defined white-list pattern
    return re.search(PATTERN_INTERESTING_HEADER, basename)


@cache
@type_enforced.Enforcer
def _get_macro_instantiation_interval(tu: clang.cindex.TranslationUnit):
    l = []
    for c in find_cursors(tu.cursor, clang.cindex.CursorKind.MACRO_INSTANTIATION, 1):
        ext_s, ext_e = c.extent.start, c.extent.end
        assert ext_s.file.name == ext_e.file.name
        bisect.insort(
            l,
            (ext_s.offset, ext_e.offset),
        )
    return l


@attach_to(clang.cindex.Cursor)
@cached_property
def _is_macro_expansion(self):
    """Return True if this Cursor was produced by macro expansion."""
    l = _get_macro_instantiation_interval(self.translation_unit)
    if not l:
        return False

    idx = bisect.bisect(l, (self.extent.start.offset, 0))
    if idx == len(l):
        # My begin is greater than the end of the last macro.
        # All good, no overlap
        return not (self.extent.start.offset > l[-1][1])

    # My end is lower than the next macro start
    # All good, no overlap
    return not (self.extent.end.offset < l[idx][0])


@attach_to(clang.cindex.Cursor)
def _is_anonymous2(self):
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


@attach_to(clang.cindex.Cursor)
def _is_forward_declaration(self):
    # Workaround for a libclang quirk:
    # Typedefs referring to forward-declared structs may appear as if they point to the final definition.
    # As a fallback, we check if this typedef was already seen earlier in the parsing phase.
    if self.kind == clang.cindex.CursorKind.TYPEDEF_DECL:
        return any(self.spelling == d["name"] for d in DECLARATIONS["typedefs"])

    # https://joshpeterson.github.io/blog/2017/identifying-a-forward-declaration-with-libclang/
    # Need two tests, as cursors cannot be compared to None
    return self.get_definition() is None or self.get_definition() != self


@cache
@type_enforced.Enforcer
def _all_enums_in_param(c: clang.cindex.Cursor):
    assert c.kind == clang.cindex.CursorKind.TRANSLATION_UNIT

    return {
        enum
        for param in find_cursors(c, clang.cindex.CursorKind.PARM_DECL)
        for enum in find_cursors(param, clang.cindex.CursorKind.ENUM_DECL)
    }


@attach_to(clang.cindex.Cursor)
def _is_in_function_decl(self, origin=None):
    if origin is None:
        origin = self

    match self.kind:
        case clang.cindex.CursorKind.FUNCTION_DECL:
            return True
        # One more libclang quirk,
        # In case of `void (*foo)( enum { H0 } );`,
        # the parent of `enum` is directly the `TRANSLATION_UNIT`...
        #   So we need parse all the ENUM_DECL in PARAM_DECL and try to find ourself.
        case clang.cindex.CursorKind.TRANSLATION_UNIT:
            return origin in _all_enums_in_param(self)
        case _:
            return self.lexical_parent.is_in_function_decl(origin)


@PreloadableCache
def _file_bytes(filename):
    with open(filename, "rb") as f:
        return f.read()


@attach_to(clang.cindex.Cursor)
@property
def extent_text(self):
    def string_to_cast_format(str_):
        # Remove all space
        str_ = str_.replace(" ", "")
        # Add space after comma
        str_ = re.sub(r",\s*", ", ", str_)
        # Sanitize hex
        str_ = re.sub(
            r"0[xX]0*([0-9A-Fa-f]+)", lambda m: "0x" + m.group(1).lower(), str_
        )
        # Add spaces between <<, +, -. Negative look behind to avoid `-1` to match
        str_ = re.sub(r"(?<!^)\s*(<<|\+|-)\s*", r" \1 ", str_)
        # Delete useless enclosing parenthesis
        str_ = re.sub(r"^\((.*)\)$", r"\1", str_)
        return str_

    ext_s, ext_e = self.extent.start, self.extent.end
    assert ext_s.file.name == ext_e.file.name

    bytes_ = _file_bytes(self.location.file.name)

    str_ = bytes_[ext_s.offset : ext_e.offset].decode("utf-8")
    if COMPAT_CAST_TO_YAML:
        str_ = string_to_cast_format(str_)
    return str_


@attach_to(clang.cindex.Cursor)
def _get_interesting_children(self):
    for c in self.get_children():
        if c.location.is_in_interesting_header:
            yield c


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
    def parse_parm_type(i, t: clang.cindex.Type, cursors: Callable):
        c = next_non_attribute(cursors)
        d_type = {"type": parse_type(t, c.get_interesting_children())}

        match (c.is_anonymous2(), CANONICALIZATION):
            case (True, False):
                return d_type
            case (True, True):
                return {"name": f"_arg{i}"} | d_type
            case (False, _):
                return {"name": c.spelling} | d_type
            case _:  # pragma: no cover
                raise NotImplementedError(f"parse_parm_type: {t}")

    d = {
        "type": parse_type(t.get_result(), cursors),
        "params": [
            parse_parm_type(i, _t, cursors) for i, _t in enumerate(t.argument_types())
        ],
    }

    if t.is_function_variadic():
        d["var_args"] = True
    return d


@type_enforced.Enforcer
def parse_function_noproto_type(t: clang.cindex.Type, cursors: Callable):
    return {
        "type": parse_type(t.get_result(), cursors),
    }


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
            if COMPAT_CAST_TO_YAML and kind == "int" and "int" not in names:
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
            return parse_decl(decl) | d_qualified
        case clang.cindex.TypeKind.RECORD:
            return parse_decl(t.get_declaration())
        case clang.cindex.TypeKind.CONSTANTARRAY:
            d = {"kind": "array", "type": parse_type(t.element_type, cursors)}

            if COMPAT_CAST_TO_YAML and (c := next(cursors, None)):
                assert c.kind != clang.cindex.CursorKind.PARM_DECL
                d["length"] = c.extent_text
            else:
                d["length"] = t.element_count

            return d | d_qualified

        case clang.cindex.TypeKind.INCOMPLETEARRAY:
            return {
                "kind": "array",
                "type": parse_type(t.element_type, cursors),
            } | d_qualified
        case clang.cindex.TypeKind.FUNCTIONPROTO:
            return {"kind": "function"} | parse_function_proto_type(t, cursors)
        case clang.cindex.TypeKind.FUNCTIONNOPROTO:
            return {"kind": "function"} | parse_function_noproto_type(t, cursors)
        case _:  # pragma: no cover
            raise NotImplementedError(f"parse_type: {k}")


#    _                 _
#   |_) _. ._ _  _    | \  _   _ |
#   |  (_| | _> (/_   |_/ (/_ (_ |
#
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
            return {"kind": "custom_type"} | parse_typedef_decl(c)
        case clang.cindex.CursorKind.FUNCTION_DECL:
            return parse_function_decl(c)
        case clang.cindex.CursorKind.VAR_DECL:
            return parse_var_decl(c)
        case (
            clang.cindex.CursorKind.MACRO_INSTANTIATION
            | clang.cindex.CursorKind.MACRO_DEFINITION
            | clang.cindex.CursorKind.INCLUSION_DIRECTIVE
        ):
            return
        case _:  # pragma: no cover
            raise NotImplementedError(f"parse_decl: {k}")


#   ___                    _    _
#    |    ._   _   _|  _ _|_   | \  _   _ |
#    | \/ |_) (/_ (_| (/_ |    |_/ (/_ (_ |
#      /  |
# `cursors` is an iterator, so impossible to cache
@cache
@type_enforced.Enforcer
def parse_typedef_decl(c: clang.cindex.Cursor):
    d_name = {"name": c.spelling}
    # Only call `underlying_typedef_type` if we are interested by the header
    if not (c.is_forward_declaration()) and c.location.is_in_interesting_header:
        d_type = {
            "type": parse_type(c.underlying_typedef_type, c.get_interesting_children())
        }
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

    match c.type.kind:
        case _ if THAPI_types.get(c.type.kind):
            kind_target = "*"
        case clang.cindex.TypeKind.CONSTANTARRAY:
            kind_target = clang.cindex.CursorKind.INIT_LIST_EXPR
        case clang.cindex.TypeKind.ELABORATED | clang.cindex.TypeKind.POINTER:
            kind_target = clang.cindex.CursorKind.UNEXPOSED_EXPR
        case _:  # pragma: no cover
            raise NotImplementedError(f"parse_decl: {c.type.kind}")

    if c2 := next(find_cursors(c, kind_target), None):
        d["init"] = c2.extent_text

    DECLARATIONS["declarations"].append(d)


#    _                            _
#   |_    ._   _ _|_ o  _  ._    | \  _   _ |
#   | |_| | | (_  |_ | (_) | |   |_/ (/_ (_ |
#
@type_enforced.Enforcer
def parse_function_decl(c: clang.cindex.Cursor):
    if c.is_definition():
        h2yaml_warning(
            c, f"`{c.spelling}` is a function definition and will be ignored."
        )
        return {}

    d = {"name": c.spelling} | parse_storage_class(c)

    if c.is_function_inlined():
        d["inline"] = True

    match t := c.type.kind:
        case clang.cindex.TypeKind.FUNCTIONNOPROTO:
            h2yaml_warning(
                c,
                f"`{c.spelling}` defines a function with no parameters, consider specifying `void`.",
            )
            d |= parse_function_noproto_type(c.type, c.get_interesting_children())
        case clang.cindex.TypeKind.FUNCTIONPROTO:
            d |= parse_function_proto_type(c.type, c.get_interesting_children())
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
# We also take special care of self referential data-structure


@type_enforced.Enforcer
def _parse_struct_union_decl(name_decl: str, c: clang.cindex.Cursor):
    # Note: This function uses the global variable CACHE_STRUCT_UNION_DECL_REC.

    def parse_field_decl(c: clang.cindex.Cursor):
        assert c.kind == clang.cindex.CursorKind.FIELD_DECL
        d = {"type": parse_type(c.type, c.get_interesting_children())}
        if c.is_bitfield():
            d["num_bits"] = c.get_bitfield_width()
        if c.is_anonymous2():
            return d
        return {"name": c.spelling} | d

    d_name = {"name": c.spelling}
    # Self referential data-type
    if c in CACHE_STRUCT_UNION_DECL_REC:
        return d_name

    if c.is_forward_declaration():
        return d_name

    fields = (f for f in c.type.get_fields() if f.location.is_in_interesting_header)

    # Handle possible self-referential data-structure
    CACHE_STRUCT_UNION_DECL_REC.append(c)

    members = [parse_field_decl(f) for f in fields]

    CACHE_STRUCT_UNION_DECL_REC.pop()

    if not members:
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

        d_name = {"name": c.spelling}

        # If inside a macro, fall back to enum value
        if not COMPAT_CAST_TO_YAML and c.is_macro_expansion:
            return d_name | {"val": c.enum_value}

        child = next(c.get_children(), None)
        # Nothing right to `=` sign
        if not child:
            return d_name
        # All good, print the text
        return d_name | {"val": child.extent_text}

    d_members = {
        "members": [parse_enum_constant_del(f) for f in c.get_interesting_children()]
    }
    d_name = {"name": c.spelling} if not c.is_anonymous2() else {}

    # Hoisting Rule:
    # - Always inline enums declared in function parameters
    # - Always hoist named enums
    # - Hoist anonymous enums that are at the top level
    # - Finally, inline the rest (of anonymous enums)
    if c.is_in_function_decl():
        return d_name | d_members

    if not (c.is_anonymous2()):
        DECLARATIONS["enums"].append(d_name | d_members)
        return d_name

    # Anonymous enums at the top level should be hoisted.
    # Some false positives may occur: for example, the enum in `typedef enum { } _t`
    # will have its parent as the TRANSLATION_UNIT.
    # Fortunately (?), the `is_anonymous` function will return False in that case.
    if (
        c.lexical_parent.kind == clang.cindex.CursorKind.TRANSLATION_UNIT
        and c.is_anonymous()
    ):
        DECLARATIONS["enums"].append(d_members)

    return d_members


#   ___
#    | ._ _. ._   _ |  _. _|_ o  _  ._    | | ._  o _|_
#    | | (_| | | _> | (_|  |_ | (_) | |   |_| | | |  |_
#
def parse_translation_unit(
    t: clang.cindex.Cursor, pattern, canonicalization, compat_cast_to_yaml
):
    assert t.kind == clang.cindex.CursorKind.TRANSLATION_UNIT

    # We need to set some global variable
    global DECLARATIONS
    DECLARATIONS = {
        k: []
        for k in ("structs", "unions", "typedefs", "declarations", "functions", "enums")
    }

    # Struct and Union can be self-referential,
    # so we need to track them to avoid recursion problem
    global CACHE_STRUCT_UNION_DECL_REC
    CACHE_STRUCT_UNION_DECL_REC = deque()

    # PATTERN_INTERESTING_HEADER is used in `is_in_interesting_header`
    # to filter out list of header to parse
    global PATTERN_INTERESTING_HEADER
    PATTERN_INTERESTING_HEADER = pattern

    # CANONICALIZATION is checked to set name if anonnymous
    global CANONICALIZATION
    CANONICALIZATION = canonicalization

    global COMPAT_CAST_TO_YAML
    COMPAT_CAST_TO_YAML = compat_cast_to_yaml

    for c in t.get_interesting_children():
        # Warning: will modify `DECLARATIONS` global variable
        parse_decl(c)

    assert len(CACHE_STRUCT_UNION_DECL_REC) == 0
    return {k: v for k, v in DECLARATIONS.items() if v}


#
#   |\/|  _. o ._
#   |  | (_| | | |
#
def h2yaml(
    file,
    *,
    clang_args=[],
    unsaved_files=None,
    pattern=".*",
    canonicalization=False,
    compat_cast_to_yaml=False,
):
    if file == "-":
        data = sys.stdin.buffer.read()
        _file_bytes.preload(("<stdin>",), data)
        unsaved_files = [("<stdin>", data)]

    system_args = [f"-I{p}" for p in SystemIncludes.paths]
    tu = clang.cindex.Index.create().parse(
        file,
        args=clang_args + system_args,
        unsaved_files=unsaved_files,
        options=clang.cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
    )
    check_diagnostic(tu)
    decls = parse_translation_unit(
        tu.cursor, pattern, canonicalization, compat_cast_to_yaml
    )
    return yaml.dump(decls, Dumper=yaml.CDumper)


def split_clang_args(argv):
    """
    Extracts -Wc,foo style options into clang_args,
    handling -Wc,--startgroup ... -Wc,--endgroup as well.
    Returns: (filtered_argv, clang_args)
    """
    d = {"filtered_argv": [], "clang_argv": []}
    inside_group = False
    token = "-Wc,"
    for arg in argv:
        match arg.split(token):
            case [n]:  # nothing after -Wc,
                d["clang_argv" if inside_group else "filtered_argv"].append(n)
            case [n, "--startgroup"]:
                inside_group = True
            case [n, "--endgroup"]:
                inside_group = False
            case [n, *rest]:
                d["clang_argv"].extend(rest)
    return d


def parse_args(argv):
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    parser.add_argument(
        "--filter-header",
        dest="pattern",
        default=".*",
        metavar="REGEX",
        help="Only process headers matching the regex (default: .*).",
    )
    parser.add_argument(
        "-c",
        "--canonicalization",
        action="store_true",
        help="Assign names to anonymous arguments.",
    )
    parser.add_argument(
        "--compat-cast-to-yaml",
        action="store_true",
        help="Mimic cast-to-yaml output",
    )

    parser.add_argument("file", help="File to process or '-' for stdin")

    d = split_clang_args(argv)

    args = parser.parse_args(d["filtered_argv"])
    args.clang_args = d["clang_argv"]
    return args


# Main function used by `h2yaml` binary generated by pyproject.toml
def main(args=sys.argv[1:]):
    parsed_args = parse_args(args)
    yml = h2yaml(**vars(parsed_args))
    print(yml, end="")


if __name__ == "__main__":  # pragma: no cover
    main()
