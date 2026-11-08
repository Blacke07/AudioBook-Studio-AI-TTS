"""Moods of narration paragraphs: invented text and a fake Gemma; no model, no owner data."""
import json
import unittest
from unittest.mock import patch

import auto_speakers as gemma
import emotions
import narration_states as states
from dialogue import NARRATOR, PAUSE

ROWS = [
    [NARRATOR, "The garden slept under the first frost.", 0, 0],
    ["Ada", "— Did you hear that?", 0, 0],
    [NARRATOR, "Something moved behind the hedge, slow and heavy.", 0, 0],
    [PAUSE, "", 0, 0],
    [NARRATOR, "By morning the road was empty again.", 0, 0],
    [NARRATOR, "  ", 0, 0],
]


def answer(moods):
    return {"message": {"content": json.dumps({"moods": [{"id": i, "mood": m} for i, m in moods]})}, "done_reason": "stop"}


class NarrationStateTests(unittest.TestCase):
    def test_only_narration_with_text_is_requested_and_a_scene_break_ends_a_batch(self):
        self.assertEqual(states.narration_ids(ROWS), [0, 2, 4])
        self.assertEqual(states.batches(ROWS, [0, 2, 4]), [[0, 2], [4]])

    def test_batches_are_bounded_by_count_and_size(self):
        rows = [[NARRATOR, "x" * 20, 0, 0] for _ in range(25)]
        self.assertEqual([len(group) for group in states.batches(rows, states.narration_ids(rows))], [10, 10, 5])
        rows = [[NARRATOR, "x" * 2000, 0, 0] for _ in range(4)]
        self.assertEqual([len(group) for group in states.batches(rows, [0, 1, 2, 3])], [1, 1, 1, 1])

    def test_the_window_shows_context_around_the_batch_and_never_a_scene_break(self):
        records = states.window(ROWS, [4])
        self.assertEqual([record["id"] for record in records], [2, 4, 5])
        self.assertEqual(records[0]["kind"], "narration")
        self.assertEqual([record["kind"] for record in states.window(ROWS, [2])], ["narration", "dialogue", "narration"])

    def test_only_valid_non_neutral_moods_of_requested_rows_are_kept(self):
        items = [{"id": 0, "mood": "calm"}, {"id": 2, "mood": "neutral"}, {"id": 4, "mood": "furious"},
                 {"id": 9, "mood": "tense"}, "junk", {"id": 4, "mood": "ominous"}, {"id": 0, "mood": "tense"}]
        self.assertEqual(states.validate(items, {0, 2, 4}), {0: "calm", 4: "ominous"})
        self.assertEqual(states.validate(None, {0}), {})
        for mood in states.MOODS:
            self.assertIn(mood, emotions.EMOTIONS)

    def test_propose_asks_gemma_per_batch_and_returns_the_moods(self):
        sent = []

        def chat(path, data=None, timeout=30):
            sent.append(data)
            ids = json.loads(data["messages"][1]["content"])["requested_ids"]
            return answer([(i, "tense" if i == 2 else "neutral") for i in ids])

        with patch.object(gemma, "ensure_ollama"), patch.object(gemma, "request", side_effect=chat):
            self.assertEqual(states.propose(ROWS), {2: "tense"})
        self.assertEqual(len(sent), 2)
        schema = sent[0]["format"]["properties"]["moods"]
        self.assertEqual(schema["items"]["properties"]["id"]["enum"], [0, 2])
        self.assertEqual(sent[0]["options"]["temperature"], 0)

    def test_a_bad_answer_leaves_that_batch_neutral_and_does_not_stop_the_others(self):
        replies = iter([{"message": {"content": "not json"}, "done_reason": "stop"}, answer([(4, "wonder")])])
        with patch.object(gemma, "ensure_ollama"), patch.object(gemma, "request", side_effect=lambda *a, **k: next(replies)):
            self.assertEqual(states.propose(ROWS), {4: "wonder"})
        with patch.object(gemma, "ensure_ollama"), patch.object(gemma, "request", return_value={"done_reason": "length"}):
            self.assertEqual(states.propose(ROWS), {})

    def test_nothing_is_asked_when_there_is_no_narration(self):
        with patch.object(gemma, "ensure_ollama") as ensure, patch.object(gemma, "request") as request:
            self.assertEqual(states.propose([["Ada", "— Hi.", 0, 0]]), {})
        ensure.assert_not_called()
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
