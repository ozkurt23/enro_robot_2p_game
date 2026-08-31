"""Opt-in semantic smoke test for an already running local llama-server.

The module performs no network access unless ENRO_RUN_LIVE_MODEL_TESTS=1.
It never downloads or starts a model.
"""

from __future__ import annotations

import os

import pytest

from enro_terminal.eval_nlu import evaluate_case, load_corpus
from enro_terminal.llm_client import LlamaCppClient, LlamaCppConfig
from enro_terminal.nlu import NluContext, QwenNlu
from enro_terminal.types import PersonaId, PersonaState, RoundState


LIVE_MODEL_ENABLED = os.environ.get("ENRO_RUN_LIVE_MODEL_TESTS") == "1"


@pytest.mark.live_model
@pytest.mark.skipif(
    not LIVE_MODEL_ENABLED,
    reason="ENRO_RUN_LIVE_MODEL_TESTS=1 verilmedi; model indirilmez veya başlatılmaz",
)
def test_running_local_qwen_passes_semantic_corpus():
    config = LlamaCppConfig.from_environment()
    client = LlamaCppClient(config)
    assert client.health(), f"llama-server hazır değil: {config.base_url}"

    backend = QwenNlu(client, seed=180)
    cases = load_corpus()
    limit_text = os.environ.get("ENRO_LIVE_CORPUS_LIMIT", "0")
    limit = int(limit_text)
    if limit > 0:
        cases = cases[:limit]
    failures: list[str] = []

    for case in cases:
        context = NluContext(
            PersonaState(PersonaId.LEYDI_SERVO),
            RoundState(),
        )
        event = backend.parse(case["text"], context)
        problems = evaluate_case(event, case["expected"])
        if problems:
            failures.append(f"{case['id']}: {'; '.join(problems)}")

    assert failures == []
