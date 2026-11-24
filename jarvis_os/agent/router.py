"""Model router: classify each request and pick the model tier. Cheap, local, deterministic."""
from __future__ import annotations

import re
from dataclasses import dataclass

ROUTES = ("chat", "simple", "reasoning", "research", "vision", "computer", "writing")

_PATTERNS = [
    ("chat", r"^(how are you|how's it going|i('m| am) (feeling|so|really|tired|happy|sad|bored|stressed)|"
             r"good (morning|evening|night|afternoon)|thanks|thank you|tell me (a joke|something)|"
             r"what do you think|guess what|you know what|i just|my day)"),
    ("vision", r"\b(screen|see|look at|what('s| is) (this|that) (error|on)|watch (this|me)|click|this page|"
               r"this window|fill (this|in))\b"),
    ("computer", r"\b(open|close|type|press|scroll|drag|minimi[sz]e|maximi[sz]e|switch to|desktop|folder|file|move)\b"),
    ("research", r"\b(research|investigate|compare|find out|look up|briefing on|worth|competitor|analy[sz]e|"
                 r"pros and cons|deep dive|report on)\b"),
    ("writing", r"\b(write|draft|reply|compose|email to|dictat|rewrite|summari[sz]e|meeting mode)\b"),
    ("reasoning", r"\b(plan|prepare|why|explain|decide|should i|strategy|contract|figure out|handle my|"
                  r"organi[sz]e|clean up)\b"),
]


@dataclass
class Route:
    name: str
    model: str
    reason: str


def classify(text: str) -> tuple[str, str]:
    t = text.lower()
    for name, pat in _PATTERNS:
        m = re.search(pat, t)
        if m:
            return name, f"matched '{m.group(0)}'"
    if len(t.split()) > 25:
        return "reasoning", "long request"
    return "simple", "short command"


def route(text: str, settings) -> Route:
    name, reason = classify(text)
    # Voice needs speed: only screen reading and real research use the slower reasoning model.
    model = settings.model_reasoning if name in ("research", "vision") else settings.model_fast
    return Route(name, model, reason)
