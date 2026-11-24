"""Router, sentence streaming, provenance, consultation and the mock end-to-end slice."""
from conftest import run
from jarvis_os.agent import router
from jarvis_os.agent.orchestrator import MockAgent, SentenceStream
from jarvis_os.agent.providers import MockProvider


def test_router(settings):
    assert router.route("what time is it", settings).name == "simple"
    assert router.route("what's on my screen", settings).name == "vision"
    assert router.route("research Acme and tell me if they're worth partnering with", settings).name == "research"
    assert router.route("research Acme", settings).model == settings.model_reasoning
    assert router.route("open notepad", settings).model == settings.model_fast


def test_sentence_stream():
    out = []
    s = SentenceStream(out.append)
    for d in ["Sure. I found", " it. Sarah wants", " the terms by Friday"]:
        s.feed(d)
    assert out == ["Sure.", "I found it."]
    s.flush()
    assert out[-1] == "Sarah wants the terms by Friday"


def test_sentence_stream_never_speaks_bare_list_numbers():
    out = []
    s = SentenceStream(out.append)
    s.feed("Here's what to do:\n1. Open BotFather.\n2. Send new bot.\n- Keep the token safe.\n")
    s.flush()
    assert out == ["Here's what to do:", "Open BotFather.", "Send new bot.", "Keep the token safe."]


def test_vertical_slice_mock(svc):
    """voice text -> agent -> tool -> computer action -> verification -> spoken reply + trace."""
    spoken = []
    out = run(MockAgent(svc).run("open notepad", spoken.append))
    assert ("launch", "notepad") in svc.computer.log
    assert out == "Notepad is open." and spoken == [out]
    run_id = svc.tracer.last_completed_run()
    trace = svc.tracer.explain(run_id)
    assert "open_application" in trace and "list_windows" in trace


def test_memory_roundtrip_via_agent(svc):
    agent = MockAgent(svc)
    run(agent.run("remember that I prefer short emails", lambda s: None))
    assert "short emails" in run(agent.run("recall short emails", lambda s: None))


def test_context_includes_memories(svc):
    svc.memory.add("Sarah Mitchell works at Acme", "person", "user said")
    ctx = MockAgent(svc).build_context("prepare for my call with Sarah")
    assert "Sarah Mitchell works at Acme" in ctx and "source: user said" in ctx


def test_consult_attribution_never_fabricated(svc):
    svc.providers.clear()
    svc.providers.update({"claude": MockProvider("claude"), "openai": _Unavailable()})
    r = run(svc.registry.execute("consult_model", {"question": "Is clause 4 risky?", "providers": "claude,openai"}))
    assert "Mock (claude)" in r.text and "NOT consulted" in r.text
    assert r.sources == ["model:Mock (claude)"]


class _Unavailable(MockProvider):
    def available(self):
        return False


def test_explain_previous_answer_tool(svc):
    agent = MockAgent(svc)
    run(agent.run("open calculator", lambda s: None))
    svc.registry.current_run = svc.tracer.start_run("who told you that?")
    r = run(svc.registry.execute("explain_previous_answer", {}))
    assert "open calculator" in r.text and "open_application" in r.text
