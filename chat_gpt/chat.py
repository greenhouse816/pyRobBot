#!/usr/bin/env python3
from collections import defaultdict

import openai

from . import GeneralConstants
from .chat_context import BaseChatContext, EmbeddingBasedChatContext
from .tokens import TokenUsageDatabase, get_n_tokens


class Chat:
    def __init__(
        self,
        model: str,
        base_instructions: str,
        context_model: str = "text-embedding-ada-002",
        report_estimated_costs_when_done: bool = True,
    ):
        self.model = model.lower()

        if context_model is not None:
            context_model = context_model.lower()
        self.context_model = context_model

        self.username = "chat_user"
        self.assistant_name = f"chat_{model.replace('.', '_')}"
        self.system_name = "chat_manager"

        self.ground_ai_instructions = " ".join(
            [
                instruction.strip()
                for instruction in [
                    f"Your name is {self.assistant_name}.",
                    f"You are a helpful assistant to {self.username}.",
                    "You answer correctly. You do not lie.",
                    f"{base_instructions.strip(' .')}.",
                    f"You follow all directives by {self.system_name}.",
                ]
                if instruction.strip()
            ]
        )

        self.token_usage = defaultdict(lambda: {"input": 0, "output": 0})
        self.token_usage_db = TokenUsageDatabase(
            fpath=GeneralConstants.TOKEN_USAGE_DATABASE
        )

        if self.context_model is None:
            self.context_handler = BaseChatContext(parent_chat=self)
        elif self.context_model == "text-embedding-ada-002":
            self.context_handler = EmbeddingBasedChatContext(
                embedding_model=self.context_model, parent_chat=self
            )
        else:
            raise NotImplementedError(f"Unknown context model: {self.context_model}")

        self.report_estimated_costs_when_done = report_estimated_costs_when_done

        self.base_directive = {
            "role": "system",
            "name": self.system_name,
            "content": self.ground_ai_instructions,
        }

    def __del__(self):
        # Store token usage to database
        for model in [self.model, self.context_model]:
            self.token_usage_db.insert_data(
                model=model,
                n_input_tokens=self.token_usage[model]["input"],
                n_output_tokens=self.token_usage[model]["output"],
            )
        if self.report_estimated_costs_when_done:
            self.report_token_usage()

    @classmethod
    def from_cli_args(cls, cli_args):
        return cls(
            model=cli_args.model,
            context_model=cli_args.context_model,
            base_instructions=cli_args.initial_ai_instructions,
            report_estimated_costs_when_done=not cli_args.skip_reporting_costs,
        )

    def yield_response(self, prompt: str):
        prompt = prompt.strip()
        prompt_as_msg = {"role": "user", "name": self.username, "content": prompt}

        prompt_context_request = self.context_handler.get_context(text=prompt)
        context = prompt_context_request["context_messages"]
        conversation = [self.base_directive, *context, prompt_as_msg]

        full_reply_content = ""
        for chunk in _make_api_call(conversation=conversation, model=self.model):
            full_reply_content += chunk
            yield chunk

        history_entry_registration_tokens_usage = self.context_handler.add_to_history(
            text=f"{self.username}: {prompt}. {self.assistant_name}: {full_reply_content}"
        )

        # Update self.token_usage
        # 1: With tokens used in chat input
        self.token_usage[self.model]["input"] += sum(
            get_n_tokens(string=msg["content"], model=self.model) for msg in conversation
        )
        # 2: With tokens used in chat output
        self.token_usage[self.model]["output"] += get_n_tokens(
            string=full_reply_content, model=self.model
        )
        # 3: With tokens used in context handler for prompt
        self.token_usage[self.context_model]["input"] += sum(
            prompt_context_request["tokens_usage"].values()
        )
        # 4: With tokens used in context handler for reply
        self.token_usage[self.context_model]["output"] += sum(
            history_entry_registration_tokens_usage.values()
        )

    def start(self):
        try:
            while True:
                question = input(f"{self.username}: ").strip()
                if not question:
                    continue
                print(f"{self.assistant_name}: ", end="", flush=True)
                for chunk in self.yield_response(prompt=question):
                    print(chunk, end="", flush=True)
                print()
                print()
        except (KeyboardInterrupt, EOFError):
            print("Exiting chat.")

    def report_token_usage(self, current_chat: bool = True):
        self.token_usage_db.print_usage_costs(self.token_usage, current_chat=current_chat)


def _make_api_call(conversation: list, model: str):
    success = False
    while not success:
        try:
            for line in openai.ChatCompletion.create(
                model=model,
                messages=conversation,
                request_timeout=10,
                stream=True,
                temperature=0.8,
            ):
                reply_content_token = getattr(line.choices[0].delta, "content", "")
                yield reply_content_token
                success = True
        except (
            openai.error.ServiceUnavailableError,
            openai.error.Timeout,
        ) as error:
            print(f"    > {error}. Retrying...")
