"""Small text helpers shared by the index builder and the live retriever."""
import re

STOPWORDS = set("""
a an the and or but if then else of to in on at by for with from into onto over under about as is are was were be been being
am do does did doing have has had having i me my we our you your he him his she her it its they them their this that these
those what which who whom whose when where why how can could would should will shall may might must not no nor so too very
just also than there here up down out off again further once all any both each few more most other some such only own same
tell please know show give get let like want say said one ones thing things much many lot lots really
see happen happens kind type name named called
""".split())

_token_re = re.compile(r"[a-z0-9]+")


def tokenize(text: str):
    """Lower-case word tokens with stop-words removed and a tiny plural stemmer."""
    out = []
    for t in _token_re.findall(text.lower()):
        if t in STOPWORDS or len(t) < 2:
            continue
        if len(t) > 4 and t.endswith("ies"):
            t = t[:-3] + "y"
        elif len(t) > 3 and t.endswith("es") and t[-3] in "sxz":
            t = t[:-2]
        elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


_sent_re = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")


def split_sentences(text: str):
    return [s.strip() for s in _sent_re.split(text.strip()) if s.strip()]


def clean_for_speech(text: str) -> str:
    """Strip markdown/list symbols an LLM might still produce, collapse whitespace."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"[*_#`>|]+", " ", text)
    text = re.sub(r"^\s*[-•\d]+[.)]?\s+", "", text, flags=re.M)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def trim_sentences(text: str, n: int) -> str:
    sents = split_sentences(text)
    return " ".join(sents[:n]) if sents else text
