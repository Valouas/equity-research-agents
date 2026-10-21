"""Integration with the real OllamaClient and a synthetic HTTP transport.

These tests exercise real request construction, schema validation, budgets and
orchestration, not a language model. Every answer and financial input is fake.
No service is contacted and no capability of a real model is established.
"""

import copy
import csv
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from stockbot import llm
from stockbot.inputs import sample_companies
from stockbot.multiagent import ROLES, analyse_research
from stockbot.reporting import write_reports


AS_OF = date(2026, 10, 6)
MODEL = "synthetic-transport-fixture:local"


def request_parts(payload):
    """Read the actual wire payload, including the embedded evidence JSON."""
    assert payload["stream"] is False
    assert [message["role"] for message in payload["messages"]] == ["system", "user"]
    prefix, separator, evidence_text = payload["messages"][1]["content"].partition("\n")
    assert separator and prefix == "Dossier de preuves JSON :"
    dossier = json.loads(evidence_text)
    role = "decision" if "action" in payload["format"]["properties"] else dossier["baseline"]["agent_id"]
    assert "Rôle : " + role + "." in payload["messages"][0]["content"]
    return role, dossier


class SyntheticResponse(io.BytesIO):
    def getcode(self):
        return 200


class SyntheticOllamaTransport:
    """Respond from received EIDs without inference or external information."""

    def __init__(self):
        self.requests = []

    def open(self, req, timeout):
        assert req.full_url == "http://127.0.0.1:11434/api/chat"
        assert req.get_method() == "POST" and timeout == 60
        payload = json.loads(req.data)
        role, dossier = request_parts(payload)
        selected = dossier["evidence"]
        ids = [eid for eid in dossier["baseline"]["evidence_ids"] if eid in selected][:8]
        assert ids, "The complete synthetic sample must provide evidence for every role"
        assert all(eid.startswith("ev_") for eid in ids)
        answer = {"evidence_ids": ids,
                  "reasons": ["Transport simulé : réponse synthétique fondée sur les identifiants reçus."]}
        if role == "decision":
            answer.update(action=dossier["baseline"]["action"], conditions_to_reconsider=[])
        else:
            answer.update(status=dossier["baseline"]["status"], hypotheses=[], missing_data=[])
        # The server fixture follows the wire schema; the real client validates it
        # again, and analyse_research also checks the references it actually sent.
        llm.validate_json_schema(answer, payload["format"])
        envelope = {
            "model": MODEL, "created_at": "2026-10-06T18:00:00Z",
            "message": {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
            "done": True, "done_reason": "stop",
        }
        response_bytes = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        self.requests.append({"role": role, "input_bytes": len(req.data),
                              "response_bytes": len(response_bytes), "dossier": dossier,
                              "schema": copy.deepcopy(payload["format"]), "answer": answer})
        return SyntheticResponse(response_bytes)


def run_simulated_pipeline(*, max_calls=48, backend="ollama", company=None):
    """Return result, real client, transport and measured wire attempts.

    The serialization spy only records byte sizes; it does not alter data or the
    client's rejection rules. Thus even rejected over-limit inputs are measurable.
    Budget-rejected logical calls may construct a payload but do not reach open().
    """
    company = copy.deepcopy(company if company is not None else sample_companies(AS_OF)[0])
    config = {"agents": {"backend": backend, "model": MODEL, "max_calls_per_run": max(1, max_calls)}}
    client = llm.OllamaClient(MODEL, max_calls=max_calls)
    transport = SyntheticOllamaTransport()
    attempts = []
    original_dumps = llm._dumps

    def measured_dumps(value):
        serialized = original_dumps(value)
        if type(value) is dict and "messages" in value and "format" in value:
            payload = json.loads(serialized)
            role, dossier = request_parts(payload)
            attempts.append({"role": role, "input_bytes": len(serialized.encode("utf-8")),
                             "evidence_count": len(dossier["evidence"]),
                             "prior_reports": len(dossier["prior_reports"])})
        return serialized

    with patch("stockbot.llm.request.build_opener", return_value=transport), \
            patch("stockbot.llm._dumps", side_effect=measured_dumps):
        result = analyse_research(company, config, AS_OF, llm_client=client)
    return result, client, transport, attempts


class OllamaPipelineTests(unittest.TestCase):
    def test_seven_roles_then_decision_use_real_client_and_wire_schemas(self):
        result, client, transport, attempts = run_simulated_pipeline()
        expected = list(ROLES) + ["decision"]
        self.assertEqual([req["role"] for req in transport.requests], expected)
        self.assertEqual([req["role"] for req in attempts], expected)
        self.assertEqual(client.calls_used, 8)
        self.assertEqual(len(transport.requests), 8)
        for measured, sent in zip(attempts, transport.requests):
            self.assertEqual(measured["input_bytes"], sent["input_bytes"])
            self.assertLessEqual(sent["input_bytes"], client.max_input_bytes)
            self.assertLessEqual(sent["response_bytes"], client.max_response_bytes)
            self.assertGreater(sent["input_bytes"], 1000)
            self.assertTrue(set(sent["answer"]["evidence_ids"]) <= set(sent["dossier"]["evidence"]))
        self.assertEqual(attempts[-2]["prior_reports"], 6)
        self.assertEqual(attempts[-1]["prior_reports"], 7)
        self.assertEqual(client.last_usage["input_bytes"], attempts[-1]["input_bytes"])
        self.assertEqual(client.last_usage["status"], "ok")
        research = result["research"]
        self.assertEqual(research["data_kind"], "synthetic")
        self.assertEqual(research["backend_requested"], "ollama")
        self.assertEqual(research["execution_mode"], "ollama")
        self.assertEqual(research["llm"]["calls"], 8)
        self.assertEqual(research["llm"]["successes"], 8)
        self.assertEqual(research["llm"]["failures"], 0)
        self.assertEqual(len(research["agents"]), 7)
        self.assertTrue(all(agent["method"] == "ollama" and agent["execution_status"] == "completed"
                            for agent in research["agents"]))
        self.assertEqual(research["decision"]["scope"], "research_only")
        self.assertEqual(research["decision"]["method"], "ollama_constrained")
        self.assertEqual(research["decision"]["llm_status"], "completed")
        # The labels describe the successfully simulated protocol, not a real
        # model execution. Keep that distinction in exported validation notes.
        with tempfile.TemporaryDirectory() as folder:
            paths = write_reports([result], {"validation": "transport simulé, aucune inférence"}, folder)
            exported = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            self.assertEqual(exported["summary"]["validation"], "transport simulé, aucune inférence")
            self.assertEqual(exported["results"][0]["research"]["execution_mode"], "ollama")
            with Path(paths["csv"]).open(encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["data_kind"], "synthetic")
            self.assertEqual(row["analyst_ollama_completed"], "7")
            self.assertEqual(row["analyst_rules_completed"], "0")
            self.assertEqual(row["llm_successes"], "8")

    def test_budget_limits_http_attempts_and_forces_visible_failure(self):
        result, client, transport, attempts = run_simulated_pipeline(max_calls=3)
        self.assertEqual(client.calls_used, 3)
        self.assertEqual(len(transport.requests), 3)
        self.assertNotIn("decision", [item["role"] for item in attempts])
        research = result["research"]
        self.assertEqual(research["execution_mode"], "ollama_failed")
        self.assertEqual(research["llm"]["successes"], 3)
        self.assertGreater(research["llm"]["failures"], 0)
        self.assertEqual(research["decision"]["action"], "abstain")
        self.assertEqual(research["decision"]["method"], "rules_after_ai_failure")
        self.assertEqual(sum(agent["execution_status"] == "failed" for agent in research["agents"]), 4)

    def test_rules_mode_never_uses_client_even_when_one_is_supplied(self):
        result, client, transport, attempts = run_simulated_pipeline(backend="rules")
        self.assertEqual(client.calls_used, 0)
        self.assertEqual(transport.requests, [])
        self.assertEqual(attempts, [])
        research = result["research"]
        self.assertEqual(research["execution_mode"], "rules")
        self.assertFalse(research["llm"]["requested"])
        self.assertEqual(research["llm"]["calls"], 0)
        self.assertTrue(all(agent["method"] == "rules" for agent in research["agents"]))

    def test_large_admissible_documents_never_bypass_request_byte_cap(self):
        company = sample_companies(AS_OF)[0]
        original = company["documents"][0]
        company["documents"] = []
        for index in range(10):
            document = dict(original)
            document["title"] = "Extrait synthétique " + str(index)
            document["source_url"] = "https://example.invalid/synthetic/" + str(index)
            document["text"] = "DOCUMENT SYNTHÉTIQUE. " + "é" * (6000 - len("DOCUMENT SYNTHÉTIQUE. "))
            company["documents"].append(document)
        result, client, transport, attempts = run_simulated_pipeline(company=company)
        self.assertTrue(all(item["input_bytes"] <= client.max_input_bytes for item in transport.requests))
        self.assertEqual(client.calls_used, len(transport.requests))
        oversized = [item for item in attempts if item["input_bytes"] > client.max_input_bytes]
        # Current full dossiers can exceed the cap. The failure must remain
        # explicit; this test does not silently discard documents to force success.
        if oversized:
            self.assertEqual(result["research"]["decision"]["action"], "abstain")
            self.assertGreater(result["research"]["llm"]["failures"], 0)
            self.assertNotIn("decision", [item["role"] for item in transport.requests])


if __name__ == "__main__":
    unittest.main()
