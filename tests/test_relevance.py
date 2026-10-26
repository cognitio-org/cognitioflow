"""The TF-IDF ranker that picks exam-relevant material for broad-scope games."""
import relevance


def test_on_topic_outranks_off_topic():
    q = "State aid Article 107 TFEU selectivity private investor test"
    docs = ["State aid and Article 107 TFEU selectivity, the market economy investor principle.",
            "Free movement of goods, Article 34 TFEU, quantitative restrictions."]
    s = relevance.rank(q, docs)
    assert s[0] > s[1] > 0.0


def test_empty_query_or_docs_fall_back_to_zero():
    assert relevance.rank("", ["a word here", "another word"]) == [0.0, 0.0]
    assert relevance.rank("anything", []) == []
    assert relevance.rank("anything at all", ["", ""]) == [0.0, 0.0]


def test_scores_stay_in_unit_range():
    s = relevance.rank("contract offer acceptance", ["offer and acceptance in contract", "tort of negligence", ""])
    assert all(0.0 <= x <= 1.0 for x in s) and len(s) == 3
