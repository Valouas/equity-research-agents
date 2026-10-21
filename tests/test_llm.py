"""Synthetic Ollama transport and schema tests. No real inference or network."""

import copy
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from stockbot.llm import (
    LLMError, LLMBudgetExceeded, LLMInvalidResponse, LLMTimeout, LLMUnavailable,
    OllamaClient, validate_json_schema,
)


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string", "enum": ["watch", "abstain"]},
        "summary": {"type": "string", "minLength": 3, "maxLength": 100},
        "evidence_ids": {"type": "array", "minItems": 1, "maxItems": 3,
                         "items": {"type": "string", "enum": ["revenue", "debt"]}},
        "score": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
        "confirmed": {"type": "boolean"},
    },
    "required": ["verdict", "summary", "evidence_ids", "score", "confirmed"],
}
VALID = {"verdict": "watch", "summary": "Exemple synthétique.",
         "evidence_ids": ["revenue"], "score": 50, "confirmed": False}
EVIDENCE = {"symbol": "SYNTH.SW", "facts": [{"id": "revenue", "value": 100, "currency": "CHF"}]}


def envelope(content=None, **updates):
    result = {
        "model": "fixture:local", "created_at": "2026-10-06T18:00:00Z",
        "message": {"role": "assistant", "content": json.dumps(VALID) if content is None else content},
        "done": True, "done_reason": "stop", "prompt_eval_count": 200,
        "eval_count": 80, "total_duration": 123456789,
    }
    result.update(updates)
    return result


class FakeResponse(io.BytesIO):
    def __init__(self, payload, status=200):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        super().__init__(body)
        self.status = status
        self.read_sizes = []

    def getcode(self):
        return self.status

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class SchemaTests(unittest.TestCase):
    def test_valid_value_and_nullable_union(self):
        self.assertIs(validate_json_schema(VALID, SCHEMA), VALID)
        result = dict(VALID, score=None)
        self.assertEqual(validate_json_schema(result, SCHEMA), result)

    def test_required_additional_and_enum_constraints(self):
        missing = dict(VALID)
        del missing["summary"]
        for value in (missing, dict(VALID, secret="unexpected"),
                      dict(VALID, verdict="BUY"), dict(VALID, evidence_ids=["invented"])):
            with self.subTest(value=value), self.assertRaises(LLMInvalidResponse):
                validate_json_schema(value, SCHEMA)

    def test_arrays_and_unicode_string_length(self):
        for value in (dict(VALID, evidence_ids=[]), dict(VALID, evidence_ids=["debt"] * 4),
                      dict(VALID, summary="é"), dict(VALID, summary="x" * 101)):
            with self.subTest(value=value), self.assertRaises(LLMInvalidResponse):
                validate_json_schema(value, SCHEMA)
        validate_json_schema("éé", {"type": "string", "minLength": 2, "maxLength": 2})

    def test_strict_types_finite_numbers_and_bounds(self):
        for value in (dict(VALID, score=True), dict(VALID, confirmed=1),
                      dict(VALID, score=-1), dict(VALID, score=101),
                      dict(VALID, score=float("nan")), dict(VALID, score=float("inf"))):
            with self.subTest(value=value), self.assertRaises(LLMInvalidResponse):
                validate_json_schema(value, SCHEMA)
        for invalid in (True, 1.0, "1"):
            with self.subTest(invalid=invalid), self.assertRaises(LLMInvalidResponse):
                validate_json_schema(invalid, {"type": "integer"})
        validate_json_schema(10**400, {"type": "integer", "minimum": 0})

    def test_enum_and_const_do_not_conflate_boolean_and_number(self):
        with self.assertRaises(LLMInvalidResponse):
            validate_json_schema(True, {"enum": [1]})
        with self.assertRaises(LLMInvalidResponse):
            validate_json_schema({"x": True}, {"const": {"x": 1}})
        validate_json_schema(1.0, {"type": "number", "enum": [1]})
        validate_json_schema(False, {"type": "boolean", "const": False})

    def test_exclusive_numeric_bounds(self):
        schema = {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1}
        validate_json_schema(0.5, schema)
        for number in (0, 1):
            with self.assertRaises(LLMInvalidResponse):
                validate_json_schema(number, schema)

    def test_unknown_keyword_rejected_in_unused_schema_branch(self):
        schema = {"type": "object", "properties": {
            "optional_absent": {"type": "string", "pattern": ".*"}}}
        with self.assertRaises(LLMInvalidResponse):
            validate_json_schema({}, schema)
        for keyword in ("$ref", "oneOf", "format", "uniqueItems"):
            with self.subTest(keyword=keyword), self.assertRaises(LLMInvalidResponse):
                validate_json_schema({}, {keyword: "unsupported"})

    def test_invalid_schema_shapes_rejected(self):
        for schema in (True, {"type": []}, {"type": ["object", "object"]},
                       {"type": "wrong"}, {"enum": []}, {"enum": [1, 1.0]},
                       {"required": ["a", "a"]}, {"minItems": True},
                       {"items": []}, {"additionalProperties": {"type": "string"}}):
            with self.subTest(schema=schema), self.assertRaises(LLMInvalidResponse):
                validate_json_schema({}, schema)

    def test_non_json_and_cyclic_values_rejected(self):
        cycle = []
        cycle.append(cycle)
        for value in ({1: "non-string key"}, (1, 2), {"a", "b"}, cycle, "\ud800"):
            with self.assertRaises(LLMInvalidResponse):
                validate_json_schema(value, {})


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.factory_patch = patch("stockbot.llm.request.build_opener")
        self.factory = self.factory_patch.start()
        self.addCleanup(self.factory_patch.stop)
        self.opener = Mock()
        self.factory.return_value = self.opener
        self.opener.open.side_effect = AssertionError("Aucun vrai accès réseau autorisé par ces tests")

    def call(self, client=None, **updates):
        args = {"role": "quality", "prompt": "Analyse les preuves synthétiques.",
                "evidence_bundle": EVIDENCE, "schema": SCHEMA}
        args.update(updates)
        return (client or OllamaClient("fixture:local")).chat(**args)

    def serve(self, value):
        self.opener.open.side_effect = None
        self.opener.open.return_value = FakeResponse(value)

    def test_constructor_and_import_surface_are_network_free(self):
        client = OllamaClient("fixture:local")
        self.factory.assert_not_called()
        self.assertEqual(client.calls_used, 0)
        self.assertEqual(client.last_usage, {})

    def test_request_schema_limits_and_usage_are_preserved(self):
        self.serve(envelope())
        client = OllamaClient("fixture:local")
        before = copy.deepcopy(EVIDENCE)
        result = self.call(client)
        self.assertEqual(result, VALID)
        self.assertEqual(EVIDENCE, before)
        req = self.opener.open.call_args.args[0]
        self.assertEqual(req.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(self.opener.open.call_args.kwargs["timeout"], 60)
        payload = json.loads(req.data)
        self.assertEqual(payload["format"], SCHEMA)
        self.assertIs(payload["stream"], False)
        self.assertEqual(payload["options"], {"temperature": 0, "num_predict": 1200, "num_ctx": 8192})
        self.assertEqual([m["role"] for m in payload["messages"]], ["system", "user"])
        self.assertNotIn("tools", payload)
        self.assertIn("StockResearchBot", req.get_header("User-agent"))
        proxy_handler, redirect_handler = self.factory.call_args.args
        self.assertEqual(proxy_handler.proxies, {})
        self.assertIsNone(redirect_handler.redirect_request(req, None, 302, "", {}, "https://example.org"))
        self.assertEqual(client.calls_used, 1)
        self.assertEqual(client.last_usage["status"], "ok")
        self.assertEqual(client.last_usage["eval_count"], 80)
        self.assertEqual(client.last_usage["prompt_eval_count"], 200)
        self.assertEqual(client.last_usage["input_bytes"], len(req.data))
        self.assertEqual(len(client.last_usage["request_sha256"]), 64)
        self.assertTrue(client.last_usage["requested_at"].endswith("Z"))
        self.assertTrue(client.last_usage["completed_at"].endswith("Z"))

    def test_only_loopback_urls_and_local_models_are_accepted(self):
        for endpoint in ("https://ollama.com", "http://192.168.1.2:11434",
                         "http://localhost.example.org", "http://127.0.0.1:11434/?key=secret",
                         "http://user:secret@127.0.0.1:11434", "http://127.0.0.1:11434/api",
                         "http://[2001:db8::1]:11434", "file:///tmp/ollama", "http://127.1:11434"):
            with self.subTest(endpoint=endpoint), self.assertRaises(LLMError):
                OllamaClient("fixture:local", base_url=endpoint)
        for name in ("", "model:cloud", "gpt-oss:120b-cloud", "https://example.org/model"):
            with self.subTest(name=name), self.assertRaises(LLMError):
                OllamaClient(name)
        self.assertEqual(OllamaClient("fixture:local", base_url="http://localhost:11434/").base_url,
                         "http://127.0.0.1:11434")
        self.assertEqual(OllamaClient("fixture:local", base_url="http://[::1]:11434").base_url,
                         "http://[::1]:11434")
        self.factory.assert_not_called()

    def test_bad_configuration_is_rejected_without_io(self):
        for options in ({"timeout": 0}, {"timeout": float("inf")}, {"timeout": True},
                        {"max_calls": True}, {"max_output_tokens": 0}, {"num_ctx": 256},
                        {"max_input_bytes": 0}, {"max_response_bytes": 0}):
            with self.subTest(options=options), self.assertRaises(LLMError):
                OllamaClient("fixture:local", **options)
        self.factory.assert_not_called()

    def test_schema_input_and_byte_size_fail_before_budget_or_io(self):
        client = OllamaClient("fixture:local", max_input_bytes=100)
        with self.assertRaises(LLMError):
            self.call(client, evidence_bundle={"text": "é" * 100})
        self.assertEqual(client.calls_used, 0)
        client = OllamaClient("fixture:local")
        for updates in ({"schema": {"type": "object", "$ref": "remote"}},
                        {"evidence_bundle": {"bad": float("nan")}},
                        {"schema": {"type": "array"}}, {"role": ""}):
            with self.subTest(updates=updates), self.assertRaises(LLMError):
                self.call(client, **updates)
        self.assertEqual(client.calls_used, 0)
        self.factory.assert_not_called()

    def test_budget_is_checked_without_an_extra_request(self):
        self.serve(envelope())
        client = OllamaClient("fixture:local", max_calls=1)
        self.call(client)
        with self.assertRaises(LLMBudgetExceeded):
            self.call(client)
        self.assertEqual(client.calls_used, 1)
        self.assertEqual(self.opener.open.call_count, 1)
        with self.assertRaises(LLMBudgetExceeded):
            self.call(OllamaClient("fixture:local", max_calls=0))
        self.assertEqual(self.opener.open.call_count, 1)

    def test_http_errors_are_sanitized_not_retried_and_consume_budget(self):
        secret = "SERVER_PRIVATE_RESPONSE"
        for status in (302, 400, 401, 403, 404, 429, 500, 503):
            self.opener.open.side_effect = HTTPError(
                "http://127.0.0.1:11434/secret", status, secret, {}, io.BytesIO(secret.encode()))
            client = OllamaClient("fixture:local", max_calls=1)
            calls_before = self.opener.open.call_count
            with self.subTest(status=status), self.assertRaises(LLMError) as caught:
                self.call(client)
            self.assertNotIn(secret, str(caught.exception))
            self.assertNotIn("/secret", str(caught.exception))
            self.assertEqual(self.opener.open.call_count, calls_before + 1)
            self.assertEqual(client.calls_used, 1)
            self.assertEqual(client.last_usage["status"], "error")
            with self.assertRaises(LLMBudgetExceeded):
                self.call(client)

    def test_network_timeout_and_unavailable_are_distinct(self):
        for failure, expected in ((TimeoutError("secret"), LLMTimeout),
                                  (URLError(TimeoutError("secret")), LLMTimeout),
                                  (URLError("secret"), LLMUnavailable),
                                  (ConnectionRefusedError("secret"), LLMUnavailable)):
            self.opener.open.side_effect = failure
            with self.subTest(expected=expected), self.assertRaises(expected) as caught:
                self.call()
            self.assertNotIn("secret", str(caught.exception))

    def test_envelope_errors_and_partial_generations_rejected(self):
        for value in (envelope(done=False), envelope(done_reason="length"),
                      envelope(error="private body"), envelope(message={}),
                      envelope(message={"role": "assistant", "content": "", "thinking": "private"}),
                      envelope(message={"role": "assistant", "content": json.dumps(VALID),
                                        "tool_calls": [{"function": {"name": "execute"}}]}),
                      envelope(model="fixture:cloud"), {"message": {"content": "{}"}}):
            self.serve(value)
            with self.subTest(value=value), self.assertRaises(LLMInvalidResponse) as caught:
                self.call()
            self.assertNotIn("private", str(caught.exception))

    def test_json_malformed_duplicate_nonfinite_and_schema_mismatch(self):
        duplicate = json.dumps(VALID)[:-1] + ', "verdict": "abstain"}'
        for content in ('```json\n{}\n```', '{"truncated":', duplicate,
                        json.dumps(dict(VALID, score=float("nan"))),
                        json.dumps(dict(VALID, evidence_ids=["fabricated"])),
                        json.dumps(dict(VALID, confirmed=1)), "[]"):
            self.serve(envelope(content=content))
            with self.subTest(content=content), self.assertRaises(LLMInvalidResponse):
                self.call()

    def test_response_size_is_bounded_and_invalid_utf8_rejected(self):
        self.serve(b"x" * 200)
        response = self.opener.open.return_value
        client = OllamaClient("fixture:local", max_response_bytes=100)
        with self.assertRaises(LLMInvalidResponse):
            self.call(client)
        self.assertEqual(response.read_sizes, [101])
        self.serve(b"\xff\xfe")
        with self.assertRaises(LLMInvalidResponse):
            self.call()


if __name__ == "__main__":
    unittest.main()
