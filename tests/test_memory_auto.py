import json

import pytest

from neuro_mvp.memory_auto import AutoMemoryConfig, MemoryAutoUpdater


class DummyMem:
    def __init__(self):
        self.writes = []
        self.autocaptured = []

    def write(self, label, value):
        self.writes.append((label, value))

    def try_autocapture(self, text):
        self.autocaptured.append(text)


class DummyLLM:
    enabled = True

    def __init__(self, response):
        self.response = response
        self.prompts = []

    def generate(self, *_args):
        # record prompt for assertion
        self.prompts.append(_args[-1])
        return self.response


def test_parse_json_array_handles_fenced_block():
    updater = MemoryAutoUpdater(DummyMem(), None)
    text = """```json\n[{\"type\": \"user\", \"text\": \"Loves coffee\", \"importance\": 8}]\n```"""
    items = updater._parse_json_array(text)
    assert isinstance(items, list)
    assert items[0]['text'] == 'Loves coffee'


def test_store_items_respects_threshold_and_mapping(capfd):
    cfg = AutoMemoryConfig(importance_threshold=5, max_items=2, allow_general_from_auto=True, verbose=False)
    mem = DummyMem()
    updater = MemoryAutoUpdater(mem, None, cfg)
    payload = [
        {'type': 'user', 'title': 'Profile', 'text': 'Enjoys hiking', 'importance': 7, 'tags': ['preferences']},
        {'type': 'general', 'title': 'Doc', 'text': 'General tip', 'importance': 6, 'tags': []},
        {'type': 'user', 'title': 'Too small', 'text': 'Low importance', 'importance': 2},
    ]

    stored = updater._store_items(payload)

    assert stored == 2
    assert mem.writes == [
        ('preferences', 'Profile: Enjoys hiking'),
        ('general', 'Doc: General tip'),
    ]


def test_process_turn_uses_llm_and_autocapture():
    cfg = AutoMemoryConfig(importance_threshold=5, verbose=False)
    mem = DummyMem()
    llm_response = json.dumps([
        {'type': 'user', 'title': 'Hobby', 'text': 'Likes chess', 'importance': 7, 'tags': ['preferences']}
    ])
    llm = DummyLLM(llm_response)
    updater = MemoryAutoUpdater(mem, llm, cfg)

    info = updater.process_turn('I love playing chess on weekends', 'That sounds fun!', 'Summary context')

    assert info['stored'] == 1
    assert mem.autocaptured == ['I love playing chess on weekends']
    assert mem.writes == [('preferences', 'Hobby: Likes chess')]
    assert llm.prompts  # ensure prompt was built


def test_process_turn_skips_when_disabled():
    cfg = AutoMemoryConfig(enable=False)
    mem = DummyMem()
    updater = MemoryAutoUpdater(mem, DummyLLM('[]'), cfg)

    info = updater.process_turn('text', 'reply')

    assert info == {'enabled': False, 'stored': 0}
    assert mem.writes == []
