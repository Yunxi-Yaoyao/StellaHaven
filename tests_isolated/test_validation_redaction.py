"""Real FastAPI validation, in-process HTTP only; no production bootstrap/DB.

Run alone with PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest --noconftest.
All credential markers below are synthetic fixtures, never real credentials.
"""
import ast
import importlib.abc
import importlib.util
from typing import Annotated, Literal
from pathlib import Path
import sys

from fastapi import Body, Cookie, Depends, FastAPI, Form, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError
import pytest

ROOT = Path(__file__).resolve().parents[1]
MARKER = "synthetic-credential-DO-NOT-ECHO-93ab"


@pytest.fixture
def client():
    class BlockBootstrap(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname in {"main", "app.main", "app.config", "app.database"}:
                raise AssertionError(f"Forbidden production import: {fullname}")

    guard = BlockBootstrap()
    sys.meta_path.insert(0, guard)
    try:
        app = FastAPI(debug=False)
        path = ROOT / "app/validation_errors.py"
        spec = importlib.util.spec_from_file_location("validation_under_test", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app.add_exception_handler(RequestValidationError, module.validation_exception_handler)

        class Credentials(BaseModel):
            password: str = Field(max_length=8)
            token: int

        @app.post("/credentials")
        def credentials(body: Credentials):
            return {"ok": True}

        class Nested(BaseModel):
            items: list[Credentials]

        @app.post("/nested")
        def nested(body: Nested):
            return {"ok": True}

        @app.get("/sources/{account}")
        def sources(account: int, token: Annotated[int, Query()], authorization: Annotated[int, Header()]):
            return {"ok": True}

        @app.post("/form")
        def form(password: Annotated[int, Form()], secret: Annotated[int, Form()]):
            return {"ok": True}

        class RejectingValue(BaseModel):
            opaque: str

            @field_validator("opaque")
            @classmethod
            def reject(cls, value):
                raise ValueError(f"Rejected submitted value {value}")

        @app.post("/validator")
        def validator(body: RejectingValue):
            return {"ok": True}

        @app.post("/raw-pydantic")
        def raw_pydantic(body: dict):
            try:
                RejectingValue.model_validate(body)
            except ValidationError as exc:
                errors = exc.errors(include_url=True)
                assert {"url", "input", "ctx"} <= errors[0].keys()
                raise RequestValidationError(errors, body=body) from exc
            return {"ok": True}

        class RejectingModel(BaseModel):
            password: str

            @model_validator(mode="after")
            def reject(self):
                raise ValueError(f"Rejected credential {self.password}")

        @app.post("/model-validator")
        def model_validator_route(body: RejectingModel):
            return {"ok": True}

        class OpaqueContext(BaseModel):
            secret: str

            @field_validator("secret")
            @classmethod
            def reject(cls, value):
                # Custom errors may supply both a known code and an unsafe msg.
                raise PydanticCustomError("int_parsing", "Rejected {secret}: {opaque}",
                                          {"secret": value, "opaque": object()})

        @app.post("/opaque-context")
        def opaque_context(body: OpaqueContext):
            return {"ok": True}

        class CustomType(BaseModel):
            opaque: str

            @field_validator("opaque")
            @classmethod
            def reject(cls, value):
                raise PydanticCustomError(value, "Rejected {secret}", {"secret": value})

        @app.post("/custom-type")
        def custom_type(body: CustomType):
            return {"ok": True}

        class Rules(BaseModel):
            name: str = Field(min_length=40)
            count: int = Field(gt=0)
            enabled: bool
            mode: Literal["one", "two"]

        @app.post("/rules")
        def rules(body: Rules):
            return {"ok": True}

        class MappingBody(BaseModel):
            model_config = ConfigDict(extra="forbid")
            entries: dict[str, int]

        @app.post("/mapping")
        def mapping(body: MappingBody):
            return {"ok": True}

        class AliasBody(BaseModel):
            api_token: int = Field(alias="apiToken")
            credential: int = Field(validation_alias=AliasChoices("first", AliasPath("credentials", 0)))

        @app.post("/aliases")
        def aliases(body: AliasBody):
            return {"ok": True}

        class RecursiveBody(BaseModel):
            secret: int
            child: "RecursiveBody | None" = None

        RecursiveBody.model_rebuild()

        @app.post("/recursive")
        def recursive(body: RecursiveBody):
            return {"ok": True}

        def dependency(session: Annotated[int, Cookie()], api_token: Annotated[int, Header(alias="X-Api-Token")]):
            return session

        @app.get("/dependency")
        def dependency_route(value: Annotated[int, Depends(dependency)]):
            return {"ok": True}

        @app.post("/primitive")
        def primitive(body: Annotated[float, Body()]):
            return {"ok": True}

        @app.get("/conflict")
        def conflict():
            raise HTTPException(409, {"code": "revision_conflict", "message": "请重新加载"},
                                headers={"X-Conflict": "fixture"})

        @app.get("/explicit-422")
        def explicit_422():
            raise HTTPException(422, "显式业务校验提示")

        @app.get("/crash")
        def crash():
            raise RuntimeError(f"internal stack credential {MARKER}")

        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        sys.meta_path.remove(guard)


def safe_detail(response):
    assert response.status_code == 422, response.text
    assert MARKER not in response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    for item in detail:
        assert set(item) == {"loc", "type", "msg"}
        assert isinstance(item["loc"], list)
        assert all(type(part) in (str, int) for part in item["loc"])
        assert isinstance(item["type"], str) and item["type"]
        assert isinstance(item["msg"], str) and item["msg"]
    return detail


def test_missing_fields_keep_standard_types_and_messages(client):
    detail = safe_detail(client.post("/credentials", json={}))
    assert detail == [
        {"loc": ["body", name], "type": "missing", "msg": "Field required"}
        for name in ("password", "token")
    ]


def test_credentials_are_not_reflected_in_encoded_http(client):
    detail = safe_detail(client.post("/credentials", json={"password": MARKER, "token": MARKER}))
    assert [item["loc"] for item in detail] == [["body", "password"], ["body", "token"]]
    assert [item["type"] for item in detail] == ["string_too_long", "int_parsing"]


def test_nested_array_locations_are_preserved(client):
    detail = safe_detail(client.post("/nested", json={"items": [{"password": MARKER, "token": MARKER}]}))
    assert [item["loc"] for item in detail] == [
        ["body", "items", 0, "password"], ["body", "items", 0, "token"],
    ]


def test_path_query_and_header_values_are_not_reflected(client):
    detail = safe_detail(client.get(f"/sources/{MARKER}", params={"token": MARKER},
                                    headers={"Authorization": MARKER}))
    assert {tuple(item["loc"]) for item in detail} == {
        ("path", "account"), ("query", "token"), ("header", "authorization"),
    }


@pytest.mark.parametrize("multipart", [False, True])
def test_form_credentials_are_not_reflected(client, multipart):
    values = {"password": MARKER, "secret": MARKER}
    kwargs = {"files": {key: (None, value) for key, value in values.items()}} if multipart else {"data": values}
    detail = safe_detail(client.post("/form", **kwargs))
    assert [item["loc"] for item in detail] == [["body", "password"], ["body", "secret"]]


@pytest.mark.parametrize("route,field,loc", [
    ("validator", "opaque", ["body", "opaque"]),
    ("model-validator", "password", ["body"]),
    ("opaque-context", "secret", ["body", "secret"]),
    ("custom-type", "opaque", ["body", "opaque"]),
])
def test_exception_messages_and_unserializable_context_are_not_used(client, route, field, loc):
    detail = safe_detail(client.post(f"/{route}", json={field: MARKER}))
    assert detail[0]["loc"] == loc
    assert detail[0]["type"] == ("int_parsing" if route == "opaque-context" else "value_error")


def test_raw_pydantic_url_input_and_exception_context_are_not_serialized(client):
    detail = safe_detail(client.post("/raw-pydantic", json={"opaque": MARKER}))
    assert detail == [{"loc": ["[redacted]"], "type": "value_error", "msg": "Invalid value"}]


def test_normal_rules_keep_useful_safe_error_types_and_messages(client):
    detail = safe_detail(client.post("/rules", json={"name": MARKER, "count": -1, "enabled": MARKER, "mode": MARKER}))
    assert [(item["loc"][-1], item["type"], item["msg"]) for item in detail] == [
        ("name", "string_too_short", "String is too short"),
        ("count", "greater_than", "Input must be greater than the allowed minimum"),
        ("enabled", "bool_parsing", "Input should be a valid boolean"),
        ("mode", "literal_error", "Input should be one of the allowed values"),
    ]


def test_legacy_typed_error_and_field_message_display_contract(client):
    response = client.post("/credentials", json={})
    detail = safe_detail(response)
    # api/client.ts: ApiError(status: number, detail: unknown).
    error = {"status": response.status_code, "detail": detail}
    assert error["status"] == 422
    # MetricAlertsPanel.vue: d.map(item => String(item.msg || '字段无效')).join('；').
    displayed = "；".join(item["msg"] or "字段无效" for item in error["detail"])
    assert displayed == "Field required；Field required"
    assert [item["loc"][-1] for item in error["detail"]] == ["password", "token"]


def test_user_controlled_mapping_and_extra_keys_cannot_leak_through_loc(client):
    detail = safe_detail(client.post("/mapping", json={"entries": {MARKER: MARKER}, MARKER: MARKER}))
    assert [item["loc"] for item in detail] == [
        ["body", "entries", "[redacted]"], ["body", "[redacted]"],
    ]
    assert [item["type"] for item in detail] == ["int_parsing", "extra_forbidden"]


@pytest.mark.parametrize("payload,expected_type", [
    (MARKER, "float_parsing"), ({"opaque": MARKER}, "float_type"),
])
def test_other_builtin_types_are_preserved_without_raw_messages(client, payload, expected_type):
    detail = safe_detail(client.post("/primitive", json=payload))
    assert detail[0]["type"] == expected_type
    assert detail[0]["msg"] == "Input should be a valid number"
    assert detail[0]["loc"] == ["body"]


def test_builtin_type_codes_and_standard_messages_are_preserved(client):
    detail = safe_detail(client.post("/credentials", json={"password": 123, "token": []}))
    assert [item["type"] for item in detail] == ["string_type", "int_type"]
    assert [item["msg"] for item in detail] == ["Input should be a valid string", "Input should be a valid integer"]


def test_malformed_json_does_not_echo_body_or_parser_context(client):
    detail = safe_detail(client.post("/credentials", content='{"password":"' + MARKER + '",bad}',
                                    headers={"Content-Type": "application/json"}))
    assert detail[0]["type"] == "json_invalid"
    assert detail[0]["msg"] == "JSON decode error"
    assert detail[0]["loc"][0] == "body"
    assert type(detail[0]["loc"][1]) is int


def test_alias_locations_are_preserved(client):
    detail = safe_detail(client.post("/aliases", json={"apiToken": MARKER, "credentials": [MARKER]}))
    assert [item["loc"] for item in detail] == [["body", "apiToken"], ["body", "credentials", 0]]
    detail = safe_detail(client.post("/aliases", json={"apiToken": 1, "first": MARKER}))
    assert detail[0]["loc"] == ["body", "first"]


def test_recursive_schema_and_dependency_alias_locations_are_preserved(client):
    detail = safe_detail(client.post("/recursive", json={"secret": 1, "child": {"secret": MARKER}}))
    assert detail[0]["loc"] == ["body", "child", "secret"]
    client.cookies.set("session", MARKER)
    detail = safe_detail(client.get("/dependency", headers={"X-Api-Token": MARKER}))
    assert {tuple(item["loc"]) for item in detail} == {("cookie", "session"), ("header", "X-Api-Token")}


def test_non_validation_http_exceptions_are_unchanged(client):
    response = client.get("/conflict")
    assert response.status_code == 409
    assert response.headers["X-Conflict"] == "fixture"
    assert response.json() == {"detail": {"code": "revision_conflict", "message": "请重新加载"}}
    response = client.get("/explicit-422")
    assert response.status_code == 422
    assert response.json() == {"detail": "显式业务校验提示"}


def test_unknown_server_error_is_not_misclassified_or_exposed(client):
    response = client.get("/crash")
    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert MARKER not in response.text
    assert "Traceback" not in response.text


def test_successful_validation_is_unchanged(client):
    response = client.post("/credentials", json={"password": "fixture", "token": 7})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_main_registers_only_request_validation_handler_without_importing_bootstrap():
    tree = ast.parse((ROOT / "main.py").read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "add_exception_handler"]
    assert any([ast.unparse(arg) for arg in call.args] ==
               ["RequestValidationError", "validation_exception_handler"] for call in calls)
    assert all(ast.unparse(call.args[0]) == "RequestValidationError" for call in calls)
