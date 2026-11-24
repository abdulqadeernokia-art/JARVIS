"""Conversation controller and scheduler, with a scripted fake voice."""
import asyncio
import datetime as dt

from conftest import run
from jarvis_os.agent.orchestrator import MockAgent
from jarvis_os.app import JarvisApp
from jarvis_os.tasks.scheduler import Scheduler


class ScriptedVoice:
    def __init__(self, app_ref, script):
        self.app_ref, self.script = app_ref, list(script)

    def listen_ex(self, timeout=6, silence=1.3, max_seconds=30):
        if not self.script:
            self.app_ref[0].request_quit()
            return "", False
        text = self.script.pop(0)
        return text, bool(text)          # "" = silence (nothing heard)


def make_app(svc, script):
    ref = []
    app = JarvisApp(svc, MockAgent(svc), voice=ScriptedVoice(ref, script))
    app.first_start_today = lambda: True
    ref.append(app)
    said = []
    app.say = said.append
    return app, said


def test_conversation_with_follow_up_and_standby(svc):
    app, said = make_app(svc, ["open notepad", "remember that I like tea", "that's all"])
    app.wake.set()

    async def go():
        t = asyncio.create_task(app.main())
        for _ in range(100):            # after "that's all" he returns to standby and waits for the wake word
            if len(said) >= 4:
                break
            await asyncio.sleep(0.05)
        app.request_quit()
        await asyncio.wait_for(t, 5)
    run(go())
    assert "Notepad is open." in said and "Noted." in said
    assert said[3] in ("Very good, sir.", "Anytime.", "I'll be here.", "My pleasure.")
    assert svc.memory.search("tea")


class SlowAgent(MockAgent):
    """Takes 3 s before saying anything, and records whether it was cancelled."""
    cancelled = False

    async def run(self, text, speak, channel="voice"):
        await asyncio.sleep(3)
        speak(f"done: {text}")
        return "done"

    async def cancel(self):
        SlowAgent.cancelled = True


def test_name_alone_gets_acknowledged(svc):
    app, said = make_app(svc, ["", "what time is it"])     # silence after "Jarvis", then the request
    app.wake.set()

    async def go():
        t = asyncio.create_task(app.main())
        for _ in range(100):
            if any("2026" in s or ":" in s for s in said[2:]):
                break
            await asyncio.sleep(0.05)
        app.request_quit()
        await asyncio.wait_for(t, 5)
    run(go())
    from jarvis_os.app import ACKS
    assert any(s in ACKS for s in said)


def test_saying_name_interrupts_and_stop_cancels(svc):
    ref = []
    agent = SlowAgent(svc)
    SlowAgent.cancelled = False
    app = JarvisApp(svc, agent, voice=ScriptedVoice(ref, ["stop"]))
    ref.append(app)
    said = []
    app.say = said.append

    async def go():
        t = asyncio.create_task(app.run_agent("research something long"))
        await asyncio.sleep(0.3)
        app.trigger_wake()                     # user says "Jarvis" mid-task
        return await asyncio.wait_for(t, 15)
    assert run(go()) is None
    assert SlowAgent.cancelled and any("topped" in s or "course" in s for s in said)
    assert not any(s.startswith("done:") for s in said)


def test_interrupt_with_correction_and_resume(svc):
    for spoken, expected in (("actually make it a PDF", "make it a PDF"), ("carry on", "carry on where you left off")):
        ref = []
        app = JarvisApp(svc, SlowAgent(svc), voice=ScriptedVoice(ref, [spoken]))
        ref.append(app)
        app.say = lambda s: None

        async def go():
            t = asyncio.create_task(app.run_agent("write the report"))
            await asyncio.sleep(0.2)
            app.trigger_wake()
            return await asyncio.wait_for(t, 15)
        assert expected in run(go())


def test_filler_when_agent_is_slow(svc):
    ref = []
    app = JarvisApp(svc, SlowAgent(svc), voice=ScriptedVoice(ref, []))
    ref.append(app)
    said = []
    app.say = lambda s: (said.append(s), app._spoke.set())
    run(app.run_agent("compare three laptops"))
    from jarvis_os.app import FILLERS
    assert said[0] in FILLERS and said[-1].startswith("done:")


def test_longer_follow_up_after_a_question(svc):
    app, _ = make_app(svc, [])
    app.last_said = "How did the interview go?"
    assert app.follow_up_window() >= 15
    app.last_said = "Done."
    assert app.follow_up_window() == svc.settings.follow_up_seconds


def test_quit_by_voice(svc):
    app, said = make_app(svc, ["jarvis shut down"])
    app.wake.set()
    run(asyncio.wait_for(app.main(), 10))
    assert any("say Jarvis" in s for s in said) and app.exit_code == 0   # sleep, supervisor keeps listening


def test_privacy_mode_pauses_memory(svc):
    app, said = make_app(svc, ["privacy mode on"])
    app.wake.set()

    async def go():
        t = asyncio.create_task(app.main())
        await asyncio.sleep(0.5)
        assert svc.privacy and svc.memory.paused
        app.request_quit()
        await asyncio.wait_for(t, 5)
    run(go())


def test_scheduler_fires_reminders_and_jobs(svc):
    delivered = []

    async def deliver(n):
        delivered.append(n)
    past = (dt.datetime.now() - dt.timedelta(minutes=1)).timestamp()
    svc.tasks.create("Call mom", due_at=past, kind="reminder")
    svc.tasks.create("Weekly report", due_at=past, kind="agent", recurrence="weekly",
                     payload={"prompt": "summarize my week"})
    stale = (dt.datetime.now() - dt.timedelta(days=2)).timestamp()
    svc.tasks.create("Old job", due_at=stale, kind="agent", payload={"prompt": "old"})
    run(Scheduler(svc, deliver).tick())
    texts = [n.text for n in delivered]
    prompts = [n.agent_prompt for n in delivered if n.agent_prompt]
    assert any("Call mom" in t for t in texts)
    assert prompts == ["summarize my week"]        # stale one-off job is not run days later


def test_scheduler_calendar_headsup_once(svc):
    delivered = []

    async def deliver(n):
        delivered.append(n)
    start = (dt.datetime.now() + dt.timedelta(minutes=10)).isoformat(timespec="seconds")
    end = (dt.datetime.now() + dt.timedelta(minutes=40)).isoformat(timespec="seconds")
    svc.calendar.create_event("Call with Sarah", start, end)
    s = Scheduler(svc, deliver)
    run(s.tick())
    s._last_calendar_check = 0
    run(s.tick())
    heads = [n for n in delivered if "Call with Sarah" in n.text]
    assert len(heads) == 1 and heads[0].follow_up


def test_briefing_job_created_once(svc):
    s = Scheduler(svc, None)
    s.ensure_briefing()
    s.ensure_briefing()
    assert len(svc.tasks.open_tasks(kind="briefing")) == 1
