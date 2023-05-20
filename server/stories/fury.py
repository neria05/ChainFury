import os
import json
import fire
from requests import Session
from typing import Dict, Any

from fury import (
    Chain,
    programatic_actions_registry,
    model_registry,
    Node,
    ai_actions_registry,
    Edge,
)
import components  # import to register all the components that we have


def _get_openai_token() -> str:
    openai_token = os.environ.get("OPENAI_TOKEN", "")
    if not openai_token:
        raise ValueError("OpenAI token not found")
    return openai_token


class FormAiAction:
    # when the AI action is built using a form or via FE then we need to conver the JSON
    # configuration to a callable for the chain.
    def __init__(self, model_id: str, model_params: Dict[str, Any]):
        pass


class _Nodes:
    def callp(self, fail: bool = False):
        """Call a programatic action"""
        node = programatic_actions_registry.get("call_api_requests")
        print(node)
        data = {
            "method": "get",
            "url": "http://127.0.0.1:8000/api/v1/components/",
            "headers": {"token": "my-booomerang-token"},
        }
        if fail:
            data["some-key"] = "some-value"
        out, err = node(data, ret_fields=True)
        if err:
            print("ERROR:", err)
            print("TRACE:", out)
            return
        print("OUT:", out)

    def callm(self, fail: bool = False):
        """Call a model"""
        model = model_registry.get("openai-completion")
        print("Found model:", model)
        data = {
            "openai_api_key": _get_openai_token(),
            "model": "text-curie-001",
            "prompt": "What comes after 0,1,1,2?",
        }
        if fail:
            data["model"] = "this-does-not-exist"
        out, err = model(data)
        if err:
            print("ERROR:", err)
            print("TRACE:", out)
            return
        print("OUT:", out)

    def callai(self, jtype: bool = False, fail: bool = False):
        """Call the AI action"""
        action_id = "hello-world"
        if fail:
            action_id = "write-a-poem"
        if jtype:
            action_id += "-2"
        action = ai_actions_registry.get(action_id)
        # print(action)

        out, err = action(
            {
                "openai_api_key": _get_openai_token(),
                "message": "hello world",
                "temperature": 0.12,
                # "style": "snoop dogg", # uncomment to get the fail version running correctly
            }
        )
        if err:
            print("ERROR:", err)
            print("TRACE:", out)
            return
        print("OUT:", out)

    def callai_chat(self, jtype: bool = False):
        """Call the AI action"""
        action_id = "chat-sum-numbers"
        if jtype:
            action_id += "-2"
        action = ai_actions_registry.get(action_id)
        print(action)

        out, err = action(
            {
                "openai_api_key": _get_openai_token(),
                "num1": "a mexican taco",
                "num2": "a spicy korean noodle",
            },
            ret_fields=True,
        )
        if err:
            print("ERROR:", err)
            print("TRACE:", out)
            return
        print("OUT:", out)


class _Chain:
    def callpp(self):
        p1 = programatic_actions_registry.get("call_api_requests")
        p2 = programatic_actions_registry.get("regex_substitute")
        e = Edge(p1.id, p2.id, ("text", "text"))
        c = Chain([p1, p2], [e])
        print(c)

        # run the chain
        out, full_ir = c(
            {
                "method": "get",
                "url": "http://127.0.0.1:8000/api/v1/components/",
                "headers": {"token": "booboo"},
                "pattern": "components",
                "repl": "booboo",
            }
        )
        print("OUT:", out)

    def callpj(self, fail: bool = False):
        p = programatic_actions_registry.get("call_api_requests")

        # create a new ai action to build a poem
        NODE_ID = "sarcastic-agent"
        j = ai_actions_registry.register(
            node_id=NODE_ID,
            description="AI will add two numbers and give a sarscastic response. J-type action",
            model_id="openai-chat",
            model_params={
                "model": "gpt-3.5-turbo",
            },
            fn={
                "messages": [
                    {
                        "role": "user",
                        "content": "Hello there, can you add these two numbers for me? 1023, 97. Be super witty in all responses.",
                    },
                    {
                        "role": "assistant",
                        "content": "It is 1110. WTF I mean I am a powerful AI, I have better things to do!",
                    },
                    {
                        "role": "user",
                        "content": "Can you explain this json to me? {{ json_thingy }}",
                    },
                ],
            },
            outputs={
                "chat_reply": ("choices", 0, "message", "content"),
            },
        )

        e = Edge(p.id, j.id, ("text", "json_thingy"))

        c = Chain(
            [p, j],
            [
                e,
            ],
        )
        print(c)

        # run the chain
        out, full_ir = c(
            {
                "method": "get",
                "url": "http://127.0.0.1:8000/api/v1/components/",
                "headers": {"token": "booboo"},
                "openai_api_key": _get_openai_token(),
            }
        )
        print("OUT:", out)

    def calljj(self):
        j1 = ai_actions_registry.get("hello-world")
        print(j1)
        j2 = ai_actions_registry.get("write-a-poem")
        e = Edge(j1.id, j2.id, ("text", "text"))
        c = Chain([j1, j2], [e])
        print(c)

        # run the chain
        out = c(
            {
                "openai_api_key": _get_openai_token(),
                "message": "hello world",
                "style": "snoop dogg",
            }
        )
        print("OUT:", out)


if __name__ == "__main__":

    def help():
        return """
Fury Story
==========

python3 -m stories.fury nodes callp [--fail]
python3 -m stories.fury nodes callai [--jtype --fail]
python3 -m stories.fury nodes callai_chat [--jtype --fail]
""".strip()

    fire.Fire({"nodes": _Nodes, "chain": _Chain, "help": help})
