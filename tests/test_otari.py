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


class AfterlifeTest(unittest.TestCase):
    TOOLS = [{"type": "web_search", "status": "completed", "query": "Pownce shut down",
              "sources": [{"url": "https://en.wikipedia.org/wiki/Pownce", "title": "Pownce - Wikipedia"},
                          {"url": "http://pownce.com/", "title": "Pownce"},
                          {"url": "https://web.archive.org/web/2008/http://pownce.com/", "title": "Pownce (archived)"}]}]

    def test_only_urls_the_search_returned_survive(self):
        from ofrenda.afterlife import verified_links
        answer = '{"links": ["https://en.wikipedia.org/wiki/Pownce/", "https://pownce-memorial.example/"]}'
        links = verified_links(answer, self.TOOLS, "http://www.pownce.com/")
        self.assertEqual([l["url"] for l in links], ["https://en.wikipedia.org/wiki/Pownce"])
        self.assertEqual(links[0]["title"], "Pownce - Wikipedia")  # the source's title, not the model's

    def test_the_dead_site_and_its_snapshots_are_not_an_afterlife(self):
        from ofrenda.afterlife import verified_links
        answer = '{"links": ["http://pownce.com/", "https://web.archive.org/web/2008/http://pownce.com/"]}'
        self.assertEqual(verified_links(answer, self.TOOLS, "http://www.pownce.com/"), [])


class ReckonerTest(unittest.TestCase):
    ENTRIES = [{"snapshot": {"first_seen": "20070628204041", "timestamp": "20081229052219"}},
               {"snapshot": {"first_seen": "20060101000000", "timestamp": "20060111000000"}},
               {"url": "unlit"}]

    def test_only_numbers_that_match_a_local_check_are_kept(self):
        from ofrenda.reckoner import local_days, reckon
        right = local_days("20070628", "20081229")
        fake = FakeClient({"r": '{"days": {"0": %d, "1": 11}, "total_days": %d}' % (right, right + 11)})
        out = reckon(fake, "r", self.ENTRIES)
        self.assertEqual(out["agreed"], {"0": right})
        self.assertEqual(out["disagreed"], ["1"])  # 10 days, not 11: dropped
        self.assertIsNone(out["total_days"])

    def test_span_words(self):
        from ofrenda.reckoner import span_words
        self.assertEqual(span_words(550), "1 year 6 months")
        self.assertEqual(span_words(12), "12 days")
