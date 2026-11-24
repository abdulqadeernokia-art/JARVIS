"""Application controller: the voice conversation loop.

  standby --("Jarvis" / hotkey / click)--> listen --> agent (streamed speech) --> follow-up listen --> ...

Human-style turn taking:
  - "Jarvis, <request>" in one breath is handled directly; "Jarvis" alone gets a "Yes, sir?" and he listens.
  - Saying "Jarvis" while he talks or works stops him at once ("Yes?"); "carry on" resumes.
  - After he speaks he keeps listening without the wake word; longer if he just asked you a question.
  - If a request takes a moment, he says so instead of going silent.
"""
from __future__ import annotations

import asyncio
import queue
import random
import re
import threading
import time

from .agent.orchestrator import Agent
from .tasks.scheduler import Notification, Scheduler

# Only a short, direct command shuts him down ("Jarvis, shut down"), never the phrase inside a question
# ("when you are completely shut down, how do I...").
QUIT = re.compile(r"^(ok(ay)?,? |please |now )?(jarvis,? )?(shut ?down|goodbye|good bye|bye( bye)?|power off|go offline|"
                  r"turn (yourself )?off|go to sleep completely)( now| jarvis| please| for now| for today)*\W*$", re.I)
CANCEL = re.compile(r"^(stop|cancel|never ?mind|wait|hold on|don'?t (send|do) (it|that))\b", re.I)
STANDBY = re.compile(r"^(that'?s (all|it)|thanks?( you)?( jarvis)?|go to sleep|stand ?by|nothing|no thanks?)\W*$",
                     re.I)
PRIVACY_ON = re.compile(r"\b(privacy mode( on)?|go private|stop listening)\b", re.I)
NEW_CONV = re.compile(r"\b(new conversation|start over|clear (the )?context|forget this conversation)\b", re.I)
RESUME = re.compile(r"^(carry on|go on|continue|keep going|as you were|sorry,? (go on|continue))\b", re.I)
CONVERSE = re.compile(r"\b(let'?s (talk|chat|have a (chat|conversation))|conversation mode|"
                      r"(start|have) a conversation)\b", re.I)
WAKE_PREFIX = re.compile(r"^((hey|ok|okay|hi|yo)\s+)?(jarvis|jervis)[,.!?]?\s*", re.I)

ACKS = ["Yes, sir?", "Sir?", "I'm listening.", "Yes?", "At your service."]
INTERRUPT_ACKS = ["Yes?", "Sir?", "Go ahead.", "I'm listening."]
FILLERS = ["Let me check.", "One moment.", "On it.", "Give me a second.", "Let me take a look."]


class JarvisApp:
    def __init__(self, svc, agent: Agent, voice=None, speaker=None, audio=None, chime=None):
        self.svc, self.agent, self.voice, self.speaker, self.audio = svc, agent, voice, speaker, audio
        self.chime = chime or (lambda kind: None)
        self.wake = threading.Event()
        self.quit = threading.Event()
        self.notifications: asyncio.Queue | None = None
        self.last_said = ""
        self._spoke = threading.Event()
        self.exit_code = 0          # 0 = sleep (supervisor listens for "Jarvis"), 3 = quit completely
        self.start_woken = False    # launched because the supervisor heard "Jarvis"
        self.loop: asyncio.AbstractEventLoop | None = None
        self.typed: queue.Queue[str] = queue.Queue()   # text typed in the galaxy UI
        self.conv = None                # running ConversationSession (hands-free mode), if any
        self._conv_parts = None         # brain/STT/TTS kept warm between conversations
        self.start_conversation = False  # --converse: open straight into conversation mode

    def submit_text(self, text: str) -> None:
        """Typed input from the UI. Behaves like saying "Jarvis, <text>": interrupts and is handled next."""
        text = text.strip()
        if not text:
            return
        self.typed.put(text)
        self.svc.bus.publish("voice.transcript", text=text, partial=False, typed=True)
        if self.speaker and self.speaker.speaking:
            self.speaker.interrupt()
        self.wake.set()

    def _take_typed(self) -> str | None:
        try:
            return self.typed.get_nowait()
        except queue.Empty:
            return None

    # ---------------- triggers (any thread) ----------------
    def trigger_wake(self) -> None:
        if self.svc.privacy:
            self.set_privacy(False)
            return
        if self.speaker and self.speaker.speaking:
            self.speaker.interrupt()          # stop talking the instant he hears his name
        self.wake.set()

    def set_privacy(self, on: bool) -> None:
        self.svc.privacy = on
        self.svc.memory.paused = on
        if self.audio:
            self.audio.paused = on
        self.svc.bus.publish("privacy.changed", on=on)
        if not on:
            self.say("Privacy mode off. I'm listening again.")

    def request_quit(self, completely: bool = False) -> None:
        self.exit_code = 3 if completely else 0
        if self.conv:
            self.conv.stop("quit")
        self.quit.set()
        self.wake.set()

    # ---------------- helpers ----------------
    def say(self, text: str) -> None:
        self.last_said = text
        self._spoke.set()
        if self.speaker:
            self.speaker.say(text)
        else:
            print(f"JARVIS: {text}")

    async def wait_spoken(self) -> None:
        if self.speaker:
            await asyncio.to_thread(self.speaker.wait)

    async def listen(self, timeout: float) -> tuple[str, bool]:
        typed = self._take_typed()
        if typed:
            self.wake.clear()
            return typed, True
        if self.voice is None:          # no microphone: wait for typed text only
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                if (typed := self._take_typed()):
                    self.wake.clear()
                    return typed, True
                await asyncio.sleep(0.05)
            return "", False
        fut = asyncio.ensure_future(asyncio.to_thread(self.voice.listen_ex, timeout))
        while not fut.done():
            if (typed := self._take_typed()):
                self.wake.clear()
                return typed, True      # the mic read finishes in the background and is discarded
            await asyncio.sleep(0.05)
        text, heard = fut.result()
        return WAKE_PREFIX.sub("", text).strip(), heard

    async def listen_after_name(self, acks: list[str]) -> tuple[str, bool]:
        """After 'Jarvis': if the user keeps talking, take it; otherwise acknowledge like a person and listen."""
        typed = self._take_typed()
        if typed:
            self.wake.clear()
            return typed, True
        text, heard = await self.listen(1.2)
        if text or heard:
            return text, heard
        self.say(random.choice(acks))
        await self.wait_spoken()
        return await self.listen(8)

    async def deliver(self, n: Notification) -> None:
        await self.notifications.put(n)

    def greeting(self) -> str:
        import datetime as dt
        h = dt.datetime.now().hour
        part = "morning" if h < 12 else "afternoon" if h < 17 else "evening"
        name = self.svc.settings.user_name
        follow = random.choice(["How has your day been?", "What are we working on today?",
                                "How are you doing?", "What can I do for you?"])
        return f"Good {part}, {name}. All systems online. {follow}"

    def first_start_today(self) -> bool:
        import datetime as dt

        from .config import DATA_DIR
        marker = DATA_DIR / "last_greeting.txt"
        today = dt.date.today().isoformat()
        try:
            if marker.read_text().strip() == today:
                return False
        except OSError:
            pass
        try:
            marker.write_text(today)
        except OSError:
            pass
        return True

    def follow_up_window(self) -> float:
        # If he just asked something, give the user time to think before answering.
        base = self.svc.settings.follow_up_seconds
        return max(base, 15.0) if self.last_said.rstrip().endswith("?") else base

    # ---------------- main loop ----------------
    async def main(self) -> None:
        self.notifications = asyncio.Queue()
        self.loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        sched = asyncio.create_task(Scheduler(self.svc, self.deliver).run(stop))
        asyncio.create_task(self.agent.warm())   # start the AI in the background so the first reply is quick
        in_conversation = False
        if self.start_conversation:
            await self.converse()
        elif self.start_woken:
            self.say(random.choice(ACKS))          # you called him by name: answer like he never left
            in_conversation = True
        elif self.first_start_today():
            self.say(self.greeting())
            in_conversation = True         # he opened with a question, so listen for the answer
        else:
            self.chime("notify")           # restarts later in the day are silent: don't disturb the user
        try:
            while not self.quit.is_set():
                if not in_conversation:
                    await self.wait_spoken()
                    self.svc.bus.publish("voice.state", state="privacy" if self.svc.privacy else "idle")
                    while not (self.wake.is_set() or self.quit.is_set() or not self.notifications.empty()):
                        await asyncio.sleep(0.05)
                    if self.quit.is_set():
                        break
                    if not self.wake.is_set():
                        in_conversation = await self.handle_notification(self.notifications.get_nowait())
                        continue
                    self.wake.clear()
                    self.chime("wake")
                    text, heard = await self.listen_after_name(ACKS)
                else:
                    await self.wait_spoken()
                    await asyncio.sleep(0.2)          # let the room echo die away
                    if self.wake.is_set():            # "Jarvis" said right as he finished
                        self.wake.clear()
                        text, heard = await self.listen_after_name(ACKS)
                    else:
                        text, heard = await self.listen(self.follow_up_window())

                if not text:
                    if heard:
                        self.say(random.choice(["Sorry, I didn't catch that.", "Sorry, say that again?"]))
                        in_conversation = True
                    else:
                        in_conversation = False      # quietly drift back to standby, like a person would
                    continue
                in_conversation = await self.handle_text(text)
        finally:
            stop.set()
            sched.cancel()
            if self.exit_code == 3:
                self.say(f"Shutting down completely. Goodbye, {self.svc.settings.user_name}.")
            else:
                self.say("Going offline. Just say Jarvis when you need me.")
            await self.wait_spoken()
            if self._conv_parts:
                await self._conv_parts.brain.close()
            await self.agent.close()

    async def handle_notification(self, n: Notification) -> bool:
        self.chime("notify")
        if n.agent_prompt:
            await self.run_agent(n.agent_prompt, channel="scheduler")
            return True
        self.say(n.text)
        return n.follow_up

    async def handle_text(self, text: str) -> bool:
        """Returns True to stay in conversation (listen for a follow-up without the wake word)."""
        print(f"YOU: {text}")
        if QUIT.search(text):
            self.quit.set()
            return False
        if PRIVACY_ON.search(text) and "off" not in text.lower():
            self.say("Privacy mode on. I won't listen or remember anything. Press the hotkey or click me when you "
                     "want me back.")
            await self.wait_spoken()
            self.set_privacy(True)
            return False
        if STANDBY.match(text):
            self.say(random.choice(["Very good, sir.", "Anytime.", "I'll be here.", "My pleasure."]))
            return False
        if CANCEL.match(text) and len(text.split()) <= 4:
            self.say(random.choice(["Okay.", "Of course.", "Understood."]))
            return False
        if NEW_CONV.search(text):
            await self.agent.reset()
            self.say("Fresh start. What's on your mind?")
            return True
        if CONVERSE.search(text) and len(text.split()) <= 8:
            await self.converse()
            return False                # back to wake-word mode
        while text:
            text = await self.run_agent(text)
        return True

    async def converse(self) -> str:
        """Hands-free conversation mode (jarvis_os/conversation). Returns the exit reason."""
        if self.conv:
            return "already running"
        from .conversation import ConversationSession, build
        await self.wait_spoken()
        if self._conv_parts is None:
            self._conv_parts = await asyncio.to_thread(build, self.svc.settings)
        p = self._conv_parts
        if self.audio:
            self.audio.paused = True     # the wake-word engine sleeps; the session owns the mic
        self.conv = ConversationSession(p.cfg, p.brain, p.stt, p.tts, bus=self.svc.bus, history=p.history)
        try:
            return await self.conv.run()
        except Exception as e:
            print(f"[app] conversation mode failed: {e!r}")
            self.say("Conversation mode isn't working right now. I've logged the error.")
            return "error"
        finally:
            self.conv = None
            if self.audio:
                self.audio.paused = self.svc.privacy
            self.wake.clear()
            self.svc.bus.publish("voice.state", state="idle")

    def stop_conversation(self) -> None:
        if self.conv:
            self.conv.stop("user")

    async def run_agent(self, text: str, channel: str = "voice") -> str | None:
        """Run one request. Saying "Jarvis" stops it; returns the user's next instruction if they gave one."""
        self.wake.clear()
        self._spoke.clear()
        started = time.monotonic()
        filler_done = channel != "voice"
        gate = {"open": True}      # once interrupted, nothing more from this request is spoken

        def speak(s: str) -> None:
            if gate["open"]:
                self.say(s)
        task = asyncio.create_task(self.agent.run(text, speak, channel))
        while not task.done():
            if self.wake.is_set():
                self.wake.clear()
                gate["open"] = False
                if self.speaker:
                    self.speaker.interrupt()
                await self.agent.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(task), 3)
                except Exception:
                    task.cancel()
                new, _ = await self.listen_after_name(INTERRUPT_ACKS)
                if not new:
                    return None
                print(f"YOU (interrupting): {new}")
                if QUIT.search(new):
                    self.quit.set()
                    return None
                if CANCEL.match(new) or STANDBY.match(new):
                    self.say(random.choice(["Okay, stopped.", "Of course.", "Stopped."]))
                    return None
                if RESUME.match(new):
                    return "Please carry on where you left off."
                return f"(I interrupted you while you were handling '{text}'.) {new}"
            if not filler_done and not self._spoke.is_set() and time.monotonic() - started > 1.6:
                filler_done = True        # don't go silent on longer requests
                self.say(random.choice(FILLERS))
            await asyncio.sleep(0.05)
        try:
            task.result()
        except Exception as e:
            print(f"[app] agent error: {e}")
            self.chime("error")
            self.say("Something went wrong on my end. I've logged it.")
        return None


async def text_console(app: JarvisApp) -> None:
    """--text mode: type instead of speaking (no microphone, no UI)."""
    print(f"JARVIS: {app.greeting()}")
    while True:
        try:
            text = await asyncio.to_thread(input, "\nYOU> ")
        except (EOFError, KeyboardInterrupt):
            break
        text = text.strip()
        if not text:
            continue
        if QUIT.search(text):
            break
        if NEW_CONV.search(text):
            await app.agent.reset()
            print("JARVIS: Fresh start.")
            continue
        await app.agent.run(text, lambda s: print(f"JARVIS: {s}"), channel="text")
    await app.agent.close()
