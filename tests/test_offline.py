"""Offline tests: no network, no model. Run with `python -m unittest`."""
import tempfile
import unittest
from pathlib import Path

from ofrenda.cli import parse_input
from ofrenda.extract import extract
from ofrenda.model import grounding, parse_json
from ofrenda.render import render


class GroundingTest(unittest.TestCase):
    SRC = "Grooveshark is free music, online radio, and so much more. Enjoy unlimited free music streaming."

    def test_faithful_summary_scores_high(self):
        score, suspects = grounding("Grooveshark offered free music streaming and online radio.", self.SRC)
        self.assertGreaterEqual(score, 0.8)
        self.assertEqual(suspects, [])

    def test_invented_names_and_numbers_are_flagged(self):
        score, suspects = grounding("Founded by Sam Tarantino in 2006, it had 35 million users.", self.SRC)
        self.assertIn("Tarantino", suspects)
        self.assertIn("2006", suspects)
        self.assertLess(score, 0.45)


class ParseTest(unittest.TestCase):
    def test_input_line_with_name_and_year(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("# comment\nhttp://ffffound.com/ | FFFFOUND! | 2016\nhttp://example.invalid/\n")
        items = parse_input(f.name)
        self.assertEqual(items[0], {"url": "http://ffffound.com/", "label": "FFFFOUND!", "alive_until": "2016"})
        self.assertEqual(items[1]["label"], None)

    def test_json_from_chatty_model(self):
        out = parse_json('Sure! {"summary": "s", "epitaph": "e", "offering": "o"} hope that helps')
        self.assertEqual(out, {"summary": "s", "epitaph": "e", "offering": "o"})
        self.assertIsNone(parse_json('{"summary": "", "epitaph": "e", "offering": "o"}'))


class ExtractRenderTest(unittest.TestCase):
    def test_extract_skips_scripts(self):
        info = extract("<title>Pownce</title><script>var x=1</script><p>Pownce was closed down on December 15, 2008.</p>")
        self.assertEqual(info["title"], "Pownce")
        self.assertIn("closed down", info["text"])
        self.assertNotIn("var x", info["text"])

    def test_unarchived_page_gets_unlit_candle_and_no_text(self):
        html = render([{"url": "https://gone.invalid/", "label": "Gone", "cause": "never resolvable"}], "gemma")
        self.assertIn("we will not invent one", html)
        self.assertIn("unlit", html)


if __name__ == "__main__":
    unittest.main()
