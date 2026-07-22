import unittest
from datetime import timedelta

from utils.natural_participation import (
    ConversationAnalyzer,
    ConversationRevival,
    CooldownManager,
    ProbabilityEngine,
    ReplyGenerator,
    TopicDetector,
)


class NaturalParticipationTests(unittest.TestCase):
    def test_topic_detector_finds_dominant_topic_from_recent_chat(self) -> None:
        messages = [
            {"content": "Johnny is actually broken in Steel Ball Run"},
            {"content": "bro that fight was so unfair"},
            {"content": "Funny Valentine is a menace"},
            {"content": "jojo really woke up and chose violence"},
        ]

        topic = TopicDetector().detect_topic(messages)

        self.assertEqual(topic, "jojo")

    def test_cooldown_manager_blocks_repeated_actions(self) -> None:
        manager = CooldownManager()

        self.assertTrue(manager.allow("general", "reply"))
        self.assertFalse(manager.allow("general", "reply"))
        self.assertTrue(manager.allow("general", "meme"))

    def test_probability_engine_and_revival_logic(self) -> None:
        engine = ProbabilityEngine()
        self.assertTrue(engine.should_act(0.8, rng=lambda: 0.05))
        self.assertFalse(engine.should_act(0.1, rng=lambda: 0.5))

        revival = ConversationRevival()
        self.assertTrue(revival.should_revive(last_user_message_age=timedelta(minutes=4), rng=lambda: 0.05))
        self.assertFalse(revival.should_revive(last_user_message_age=timedelta(seconds=30), rng=lambda: 0.05))

    def test_reply_generator_returns_short_in_character_reply(self) -> None:
        reply = ReplyGenerator().build_reply("jojo")

        self.assertTrue(reply)
        self.assertLessEqual(len(reply), 140)
