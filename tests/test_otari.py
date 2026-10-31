"""Offline tests for the Otari integration: a fake client, no network, no key."""
import unittest

from ofrenda.otari import Call, FallbackModel, OtariError


class FakeClient:
    """Answers like Otari would, from a script keyed by model name."""

    def __init__(self, script):
        self.script = script
        self.calls = []

    def chat(self, role, model, messages, **params):
        self.calls.append(model)
        out = self.script[model]
        if isinstance(out, Exception):
            raise out
        call = Call(role=role, requested=model, served_model=model, provider="fake")
        return {"choices": [{"message": {"content": out}}]}, call


GOOD = '{"summary": "s", "epitaph": "e", "offering": "o"}'


class FallbackTest(unittest.TestCase):
    def test_unknown_policy_falls_through_to_next_model(self):
        fake = FakeClient({"epitaph-chain": OtariError(400, "Unknown or unsupported model"),
                           "google/gemma-3-27b-it": GOOD})
        m = FallbackModel(fake, ["epitaph-chain", "google/gemma-3-27b-it"])
        self.assertEqual(m.chat("x"), GOOD)
        self.assertEqual(m.last.requested, "google/gemma-3-27b-it")
        self.assertTrue(m.last.fallback)

    def test_junk_answer_moves_on(self):
        fake = FakeClient({"a": "I cannot do JSON today", "b": GOOD})
        m = FallbackModel(fake, ["a", "b"])
        self.assertEqual(m.chat("x"), GOOD)
        self.assertEqual(fake.calls, ["a", "b"])

    def test_spent_budget_stops_instead_of_falling_back(self):
        fake = FakeClient({"a": OtariError(402, "Budget exhausted for this workspace"), "b": GOOD})
        m = FallbackModel(fake, ["a", "b"])
        with self.assertRaises(OtariError):
            m.chat("x")
        self.assertEqual(fake.calls, ["a"])


if __name__ == "__main__":
    unittest.main()


class WitnessTest(unittest.TestCase):
    def _w(self, answer, summary="Grooveshark offered free music streaming."):
        from ofrenda.witness import cross_examine
        fake = FakeClient({"w": answer})
        return cross_examine(fake, "w", summary, "Grooveshark is free music streaming.")

    def test_objection_is_kept_when_it_quotes_the_summary(self):
        out = self._w('{"unsupported": ["free music streaming"], "verdict": "unsupported"}')
        self.assertEqual(out["verdict"], "unsupported")

    def test_witness_cannot_object_to_words_that_are_not_there(self):
        out = self._w('{"unsupported": ["founded in 2006"], "verdict": "unsupported"}')
        self.assertEqual(out["verdict"], "supported")
        self.assertEqual(out["unsupported"], [])

    def test_garbled_witness_is_reported_unavailable(self):
        self.assertEqual(self._w("hmm")["verdict"], "unavailable")
