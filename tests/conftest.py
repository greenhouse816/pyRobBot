import os

import lorem
import numpy as np
import openai
import pytest

import gpt_buddy_bot
from gpt_buddy_bot.chat import Chat
from gpt_buddy_bot.chat_configs import ChatOptions


# Register markers and constants
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "no_chat_completion_create_mocking: do not mock openai.ChatCompletion.create",
    )
    config.addinivalue_line(
        "markers",
        "no_embedding_create_mocking: mark test to not mock openai.Embedding.create",
    )

    pytest.ORIGINAL_PACKAGE_CACHE_DIRECTORY = (
        gpt_buddy_bot.GeneralConstants.PACKAGE_CACHE_DIRECTORY
    )


@pytest.fixture(autouse=True)
def set_env():
    # Make sure we don't consume our tokens in tests
    os.environ["OPENAI_API_KEY"] = "INVALID_API_KEY"
    openai.api_key = os.environ["OPENAI_API_KEY"]


@pytest.fixture(autouse=True)
def mocked_general_constants(tmp_path):
    gpt_buddy_bot.GeneralConstants.PACKAGE_CACHE_DIRECTORY = tmp_path / "cache"


@pytest.fixture(autouse=True)
def openai_api_request_mockers(request, mocker):
    """Mockers for OpenAI API requests. We don't want to consume our tokens in tests."""

    def _mock_openai_ChatCompletion_create(*args, **kwargs):
        """Mock `openai.ChatCompletion.create`. Yield from lorem ipsum instead."""
        completion_chunk = type("CompletionChunk", (), {})
        completion_chunk_choice = type("CompletionChunkChoice", (), {})
        completion_chunk_choice_delta = type("CompletionChunkChoiceDelta", (), {})
        for word in lorem.get_paragraph().split():
            completion_chunk_choice_delta.content = word + " "
            completion_chunk_choice.delta = completion_chunk_choice_delta
            completion_chunk.choices = [completion_chunk_choice]
            yield completion_chunk

    def _mock_openai_Embedding_create(*args, **kwargs):
        """Mock `openai.Embedding.create`. Yield from lorem ipsum instead."""
        embedding_request = {
            "data": [{"embedding": np.random.rand(512).tolist()}],
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }
        return embedding_request

    if "no_chat_completion_create_mocking" not in request.keywords:
        mocker.patch(
            "openai.ChatCompletion.create", new=_mock_openai_ChatCompletion_create
        )
    if "no_embedding_create_mocking" not in request.keywords:
        mocker.patch("openai.Embedding.create", new=_mock_openai_Embedding_create)


@pytest.fixture()
def input_builtin_mocker(mocker, user_input):
    """Mock the `input` builtin. Raise `KeyboardInterrupt` after the second call."""

    # We allow two calls in order to allow for the chat context handler to kick in
    def _mock_input(*args, **kwargs):
        try:
            _mock_input.execution_counter += 1
        except AttributeError:
            _mock_input.execution_counter = 0
        if _mock_input.execution_counter > 1:
            raise KeyboardInterrupt
        return user_input

    mocker.patch("builtins.input", new=lambda _: _mock_input(user_input=user_input))


@pytest.fixture()
def default_chat_configs(tmp_path):
    return ChatOptions(
        token_usage_db_path=tmp_path / "token_usage.db",  # Don't use the regular db file
        cache_dir=tmp_path,  # Don't use our cache files
    )


@pytest.fixture()
def cli_args_overrides(default_chat_configs):
    args = []
    for field, value in default_chat_configs.model_dump().items():
        if value is not None:
            args = [*args, *[f"--{field.replace('_', '-')}", str(value)]]
    return args


@pytest.fixture()
def default_chat(default_chat_configs):
    return Chat(configs=default_chat_configs)
