import os

# Set ENCRYPTION_KEY before any app imports
os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import ChatMessage, Config, Conversation
from app.services import chat_service
from app.services.chat_service import MAX_TOOL_ROUNDS, ChatService
from app.utils.crypto import encrypt_value


async def _make_conversation_and_config(session):
    conv = Conversation()
    session.add(conv)
    config = Config(
        llm_provider="openai",
        llm_model="gpt-4",
        api_key=encrypt_value("sk-test"),
    )
    session.add(config)
    await session.commit()
    await session.refresh(conv)
    return conv


async def _consume(session, conversation_id):
    events = []
    async for event in ChatService.stream_response(str(conversation_id), "hello", session):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_finishes_within_budget_answers_normally_without_extra_call(session):
    conv = await _make_conversation_and_config(session)

    mock_stream_llm = AsyncMock(return_value=("Bonjour !", None))
    with patch.object(chat_service, "_stream_llm", mock_stream_llm):
        events = await _consume(session, conv.id)

    # Only one LLM call needed: the model answered without requesting tools.
    assert mock_stream_llm.call_count == 1

    joined = "".join(events)
    assert "Bonjour !" in joined
    assert "event: done" in joined

    result = await session.execute(
        select(ChatMessage).where(
            ChatMessage.conversation_id == conv.id, ChatMessage.role == "assistant"
        )
    )
    assistant_msg = result.scalar_one()
    assert assistant_msg.content == "Bonjour !"


@pytest.mark.asyncio
async def test_exhausted_budget_triggers_synthesis_turn_that_reaches_user(session):
    conv = await _make_conversation_and_config(session)

    # Every round the model keeps wanting to call a tool, so the loop never
    # breaks and runs out its full budget. The final (synthesis) call is
    # answered with tools=None and must return text with no tool calls.
    tool_round = ("", [{"name": "list_sims", "args": {"gateway": "guinee-red24-01"}}])
    synthesis_round = ("Voici les SIM trouvees.", None)
    mock_stream_llm = AsyncMock(side_effect=[tool_round] * MAX_TOOL_ROUNDS + [synthesis_round])

    with patch.object(chat_service, "_stream_llm", mock_stream_llm):
        events = await _consume(session, conv.id)

    # MAX_TOOL_ROUNDS regular rounds + exactly one synthesis round.
    assert mock_stream_llm.call_count == MAX_TOOL_ROUNDS + 1

    # The synthesis call must be made with a falsy `tools` argument (no tools).
    last_call_args = mock_stream_llm.call_args_list[-1].args
    assert not last_call_args[4]

    joined = "".join(events)
    assert "Voici les SIM trouvees." in joined

    result = await session.execute(
        select(ChatMessage).where(
            ChatMessage.conversation_id == conv.id, ChatMessage.role == "assistant"
        )
    )
    assistant_msg = result.scalar_one()
    assert assistant_msg.content == "Voici les SIM trouvees."


@pytest.mark.asyncio
async def test_synthesis_turn_returning_nothing_emits_french_fallback(session):
    conv = await _make_conversation_and_config(session)

    tool_round = ("", [{"name": "list_sims", "args": {}}])
    empty_synthesis_round = ("", None)
    mock_stream_llm = AsyncMock(
        side_effect=[tool_round] * MAX_TOOL_ROUNDS + [empty_synthesis_round]
    )

    with patch.object(chat_service, "_stream_llm", mock_stream_llm):
        events = await _consume(session, conv.id)

    assert mock_stream_llm.call_count == MAX_TOOL_ROUNDS + 1

    joined = "".join(events)
    assert "limite d'appels d'outils" in joined
    assert "event: done" in joined

    result = await session.execute(
        select(ChatMessage).where(
            ChatMessage.conversation_id == conv.id, ChatMessage.role == "assistant"
        )
    )
    assistant_msg = result.scalar_one()
    assert assistant_msg.content != ""
    assert "limite d'appels d'outils" in assistant_msg.content


@pytest.mark.asyncio
async def test_all_max_tool_rounds_are_actually_attempted(session):
    conv = await _make_conversation_and_config(session)

    tool_round = ("", [{"name": "list_sims", "args": {}}])
    synthesis_round = ("Reponse finale.", None)
    mock_stream_llm = AsyncMock(side_effect=[tool_round] * MAX_TOOL_ROUNDS + [synthesis_round])

    with patch.object(chat_service, "_stream_llm", mock_stream_llm):
        await _consume(session, conv.id)

    # Asserting the exact count guards against silently shrinking the budget:
    # MAX_TOOL_ROUNDS tool-requesting rounds, then one synthesis round.
    assert mock_stream_llm.call_count == MAX_TOOL_ROUNDS + 1
