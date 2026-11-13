"""Tests for the Pet Shelf picture robot (no internet, no key)."""
import base64
import unittest

import pet_shelf_pictures as pics


class Reply:
    def __init__(self, code, data): self.status_code, self._data = code, data
    def json(self): return self._data


class Pictures(unittest.TestCase):
    def test_prompts_have_the_shared_suffix(self):
        p = pics.load_prompts()
        self.assertGreaterEqual(len(p), 20)
        self.assertTrue(all(v.startswith("Create an image:") and "no logo" in v for v in p.values()))

    def test_only_picture_models_are_used_and_gemini_comes_first(self):
        listing = {"models": [
            {"name": "models/gemini-x-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-x-flash-image", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/imagen-x", "supportedGenerationMethods": ["predict"]},
            {"name": "models/text-embedding-image", "supportedGenerationMethods": ["generateContent"]}]}
        models = pics.image_models("k", get=lambda *a, **k: Reply(200, listing))
        self.assertEqual(models, [("generate", "gemini-x-flash-image"), ("predict", "imagen-x")])

    def test_a_busy_model_is_skipped_and_the_next_one_draws(self):
        png = base64.b64encode(b"\x89PNGfake").decode()
        def post(url, **k):
            if "first" in url: return Reply(429, {"error": {"message": "quota"}})
            return Reply(200, {"candidates": [{"content": {"parts": [{"text": "ok"}, {"inlineData": {"data": png}}]}}]})
        data, who = pics.draw("p", "k", [("generate", "first-image"), ("generate", "second-image")], post=post)
        self.assertEqual((data, who), (b"\x89PNGfake", "second-image"))
        data, why = pics.draw("p", "k", [("generate", "first-image")], post=post)
        self.assertIsNone(data); self.assertIn("429", why)


if __name__ == "__main__":
    unittest.main()
