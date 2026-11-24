"""Tool modules. Each exposes register(svc) and adds its tools to svc.registry."""


def load_all(svc) -> None:
    from . import ai_tools, comm_tools, computer_tools, file_tools, knowledge_tools, voice_tools
    for mod in (knowledge_tools, comm_tools, computer_tools, file_tools, voice_tools, ai_tools):
        mod.register(svc)
