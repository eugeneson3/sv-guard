from pyslang import parsing

from app.editor.sv_keywords import KEYWORDS, TYPE_KEYWORDS


def _norm(word: str) -> str:
    return word.replace("_", "").lower()


def test_keywords_match_pyslang_one_to_one():
    """Every TokenKind.*Keyword in pyslang corresponds to exactly one word in KEYWORDS."""
    ours = {_norm(k) for k in KEYWORDS}
    theirs = {n.removesuffix("Keyword").lower() for n in dir(parsing.TokenKind) if n.endswith("Keyword")}
    assert len(ours) == len(KEYWORDS)  # no two words collapse to the same normalized form
    assert ours == theirs


def test_type_keywords_are_keywords():
    assert TYPE_KEYWORDS <= KEYWORDS
