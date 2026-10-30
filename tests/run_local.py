"""Run wallet tests locally without starting AstrBot or making model calls.

Only the external AstrBot API boundary is replaced. Wallet policy, KV logic,
notices and lifecycle methods run from the unmodified/patched plugin itself.
"""
import enum
import logging
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def install_api_boundary():
    for name in ("astrbot", "astrbot.api", "astrbot.api.event",
                 "astrbot.api.star", "astrbot.api.message_components"):
        module = types.ModuleType(name)
        module.__path__ = []
        sys.modules[name] = module
    api = sys.modules["astrbot.api"]
    api.AstrBotConfig = dict
    api.logger = logging.getLogger("wallet-test")

    class Star:
        def __init__(self, context):
            self.context = context

    class MessageChain:
        def __init__(self, chain):
            self.chain = chain

    class Plain:
        def __init__(self, text):
            self.text = text

    class Image:
        @staticmethod
        def fromFileSystem(path):
            return path

    class EventMessageType(enum.IntFlag):
        GROUP_MESSAGE = 1
        PRIVATE_MESSAGE = 2

    def decorator(kind):
        def register(*args, **kwargs):
            def apply(fn):
                fn._test_hook_kind = kind
                fn._test_hook_priority = kwargs.get("priority", 0)
                return fn
            return apply
        return register

    filters = types.SimpleNamespace(
        EventMessageType=EventMessageType,
        event_message_type=decorator("message"),
        command=decorator("command"),
        on_waiting_llm_request=decorator("waiting"),
        on_llm_request=decorator("request"),
    )
    events = sys.modules["astrbot.api.event"]
    events.AstrMessageEvent = object
    events.MessageChain = MessageChain
    events.filter = filters
    stars = sys.modules["astrbot.api.star"]
    stars.Context = object
    stars.Star = Star
    components = sys.modules["astrbot.api.message_components"]
    components.Plain = Plain
    components.Image = Image


if __name__ == "__main__":
    print("Isolated unit tests: AstrBot API boundary uses test doubles.", flush=True)
    install_api_boundary()
    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "tests")
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
