"""
PART B, step 2: quick rules for small talk. Greetings, "who are you", thanks and
goodbyes don't need a search - they get instant, friendly canned replies.
"""
import random
import re

RULES = [
    ("greeting", r"^\s*(hi+|hello+|hey+|namaste|namaskar|good (morning|afternoon|evening))\b[\s!.,]*(van ?mitra|there|friend)?[\s!.?]*$",
     ["Namaskar! I am Van Mitra. Ask me anything about the forests, rivers and wildlife of Angul.",
      "Hello, my friend! What would you like to know about our forests today?"]),
    ("how_are_you", r"\bhow are you\b|\bhow do you do\b",
     ["I am very well, thank you! My leaves are green and happy. What would you like to know about the forest?"]),
    ("identity", r"\b(who|what) are you\b|\byour name\b|\bwho made you\b|\bwhat is van ?mitra\b|\bare you (a )?(robot|ai|tree|human)\b",
     ["I am Van Mitra, which means friend of the forest. I am a talking tree spirit, powered by artificial intelligence, "
      "and I answer questions using the knowledge given to me by the forest department."]),
    ("thanks", r"^\s*(ok(ay)?\s+|oh\s+)?(thank(s| you)|dhanyabad|dhanyavaad|great|awesome|nice|wow|cool)\b",
     ["You are most welcome! Please protect our forests and wildlife.",
      "My pleasure! Remember, a friend of the forest never leaves plastic behind."]),
    ("bye", r"^\s*(bye|goodbye|good bye|see you|ok bye|tata)\b",
     ["Goodbye, friend of the forest! Come back again soon.",
      "Bye bye! Plant a tree and think of me."]),
]
_compiled = [(n, re.compile(p, re.I), a) for n, p, a in RULES]


def match(text):
    t = text.strip()
    if len(t.split()) > 9:  # long questions are real questions, never small talk
        return None
    for name, rx, answers in _compiled:
        if rx.search(t):
            return {"rule": name, "answer": random.choice(answers)}
    return None
