"""Public request-validation errors never serialize input or exception text."""
from json import JSONDecodeError
from typing import get_args

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic_core import SchemaError, SchemaValidator
from pydantic_core.core_schema import ErrorType


# Built-in identifiers/messages are constants, not formatted exception context.
_SAFE_TYPES = frozenset(get_args(ErrorType))
_SAFE_MESSAGES = {
    "missing": "Field required",
    "string_type": "Input should be a valid string",
    "int_type": "Input should be a valid integer",
    "json_invalid": "JSON decode error",
    "float_type": "Input should be a valid number",
    "float_parsing": "Input should be a valid number",
    "extra_forbidden": "Extra inputs are not permitted",
    "string_too_long": "String is too long",
    "string_too_short": "String is too short",
    "greater_than": "Input must be greater than the allowed minimum",
    "bool_parsing": "Input should be a valid boolean",
    "literal_error": "Input should be one of the allowed values",
    "int_parsing": "Input should be a valid integer, unable to parse string as an integer",
}
_SOURCES = ("body", "query", "path", "header", "cookie")


def _prefix_matches(loc, prefix):
    # bool == int is not evidence of an index or a declared alias component.
    return len(loc) >= len(prefix) and all(
        type(a) is type(b) and a == b for a, b in zip(loc, prefix)
    )


def _common_mask(masks, size):
    # Shared aliases can describe multiple fields. A dynamic slot in *any*
    # matching schema must not be authorized by another field's static label.
    return [all(parts) for parts in zip(*masks)] if masks else [False] * size


class _LocationSchema:
    """Walk the validator's schema at the error position, never the input.

    Core schema already resolves Annotated, aliases, discriminators and recursive
    definitions. Match branch labels using pydantic-core's own validator title;
    labels remain redacted, but their branch's real field path is retained.
    """

    def __init__(self, schema):
        self.schema = schema
        self.definitions = {}
        self.titles = {}
        seen = set()

        def collect(node):
            if not isinstance(node, (dict, list, tuple)) or id(node) in seen:
                return
            seen.add(id(node))
            if isinstance(node, dict):
                if "ref" in node and "type" in node:
                    self.definitions[node["ref"]] = node
                for key, value in node.items():
                    if key not in {"metadata", "serialization", "config", "function"}:
                        collect(value)
            else:
                for value in node:
                    collect(value)

        collect(schema)

    def _title(self, schema):
        key = id(schema)
        if key not in self.titles:
            try:
                # Compilation only: no user validator is executed. Supplying
                # definitions is necessary for recursive/hoisted union choices.
                self.titles[key] = SchemaValidator({
                    "type": "definitions", "schema": schema,
                    "definitions": list(self.definitions.values()),
                }).title
            except SchemaError:
                self.titles[key] = None  # Unsupported schema: fail closed.
        return self.titles[key]

    def mask(self, loc):
        # An iterative worklist also handles valid deep recursive input; a Python
        # recursive walker can overflow before Pydantic reaches its own limit.
        pending = [(self.schema, [], frozenset())]
        masks = []
        while pending:
            schema, prefix, seen = pending.pop()
            offset = len(prefix)
            state = (id(schema), offset)
            if offset == len(loc):
                masks.append(prefix)
                continue
            if not isinstance(schema, dict) or state in seen:
                masks.append(prefix + [False] * (len(loc) - offset))
                continue
            steps = self._steps(schema, loc[offset:])
            if not steps:
                masks.append(prefix + [False] * (len(loc) - offset))
            for child, consumed in steps:
                pending.append((child, prefix + consumed, seen | {state}))
        return _common_mask(masks, len(loc))

    def _steps(self, schema, loc):
        """Return (child schema, mask for consumed location components)."""
        kind = schema.get("type")
        if kind == "definition-ref":
            return [(self.definitions.get(schema["schema_ref"]), [])]
        if kind in {"definitions", "model", "default", "nullable", "function-before",
                    "function-after", "function-wrap", "custom-error", "json"}:
            return [(schema.get("schema"), [])]
        if kind in {"model-fields", "typed-dict"}:
            steps = []
            for name, field in schema["fields"].items():
                alias = field.get("validation_alias")
                paths = [[name]]
                if isinstance(alias, str):
                    paths.append([alias])
                elif isinstance(alias, list):
                    paths.extend(alias if alias and isinstance(alias[0], list) else [alias])
                for path in dict.fromkeys(tuple(path) for path in paths):
                    if path and _prefix_matches(loc, path):
                        steps.append((field["schema"], [True] * len(path)))
            return steps
        if kind == "dict":
            # Every key is request data, including integers and names that also
            # happen to be fields elsewhere. Continue into the value schema.
            # A following '[key]' can also be a real value-field alias. Do not
            # skip it by spelling; the value schema decides its provenance.
            return [(schema.get("values_schema"), [False])]
        if kind in {"list", "set", "frozenset", "generator", "tuple"}:
            if type(loc[0]) is not int or loc[0] < 0:
                return []
            items = schema.get("items_schema")
            if kind == "tuple":
                items = items or []
                index = loc[0]
                variadic = schema.get("variadic_item_index")
                if variadic is not None and index >= variadic:
                    # Fixed trailing items cannot be selected without input
                    # length. Intersect possible schemas rather than guess.
                    return [(item, [True]) for item in items[variadic:]]
                items = items[index] if index < len(items) else None
            return [(items, [True])]
        if kind == "tagged-union":
            return [(choice, [False]) for tag, choice in schema["choices"].items()
                    if _prefix_matches(loc, [tag])]
        if kind == "union":
            steps = []
            for choice in schema["choices"]:
                child, label = choice if isinstance(choice, tuple) else (choice, self._title(choice))
                if _prefix_matches(loc, [label]):
                    steps.append((child, [False]))
            return steps
        return []


def _route_schemas(request):
    """Use the matched APIRoute (including dependencies), not a global registry.

    FastAPI's body embedding and flattened query/header models affect where a
    parameter starts. These private metadata contracts are pinned by HTTP tests.
    """
    route = request.scope.get("route")
    roots = []
    seen = set()

    def visit(dependency):
        if dependency is None or id(dependency) in seen:
            return
        seen.add(id(dependency))
        for source in _SOURCES:
            fields = getattr(dependency, source + "_params", ())
            for field in fields:
                adapter = getattr(field, "_type_adapter", None)
                if adapter is None:
                    continue
                annotation = field.field_info.annotation
                model = isinstance(annotation, type) and issubclass(annotation, BaseModel)
                unwrapped = (source == "body" and not getattr(route, "_embed_body_fields", False)) or (
                    source != "body" and len(fields) == 1 and model
                )
                prefix = [source] if unwrapped else [source, field.alias]
                roots.append((prefix, _LocationSchema(adapter.core_schema)))
        for child in getattr(dependency, "dependencies", ()):
            visit(child)

    visit(getattr(route, "dependant", None))
    return roots


def _safe_location(loc, error_type, schemas, json_position):
    masks = [([True] * len(prefix) + schema.mask(loc[len(prefix):]))
             for prefix, schema in schemas if _prefix_matches(loc, prefix)]
    mask = _common_mask(masks, len(loc))
    if loc and type(loc[0]) is str and loc[0] in _SOURCES:
        mask[0] = True
    if error_type == "extra_forbidden" and len(loc) > 1:
        mask[-1] = False
    # Only a real parser cause proves an offset. A custom validator can forge
    # the built-in json_invalid code at an integer dictionary-key location.
    if (error_type == "json_invalid" and len(loc) == 2 and loc[0] == "body"
            and type(loc[1]) is int and loc[1] == json_position):
        mask[1] = True
    return [part if allowed and type(part) in (str, int) else "[redacted]"
            for part, allowed in zip(loc, mask)]


def validation_error_response(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Shared safe response for global and route-local validation handlers."""
    detail = []
    schemas = _route_schemas(request)
    json_position = exc.__cause__.pos if isinstance(exc.__cause__, JSONDecodeError) else None
    for error in exc.errors():
        error_type = error.get("type", "value_error")
        detail.append({
            "loc": _safe_location(error.get("loc", ()), error_type, schemas, json_position),
            "type": error_type if error_type in _SAFE_TYPES else "value_error",
            "msg": _SAFE_MESSAGES.get(error_type, "Invalid value"),
        })
    return JSONResponse(status_code=422, content={"detail": detail})


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Starlette's interface is broad; registration is only request validation."""
    assert isinstance(exc, RequestValidationError)
    return validation_error_response(request, exc)
