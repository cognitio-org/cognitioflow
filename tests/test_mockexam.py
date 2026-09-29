"""mockexam: past papers banked verbatim, sat as a paper, marked against the model answer's points. Pure, no database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mockexam as mock  # noqa: E402


def test_the_header_of_each_real_paper_is_read():
    assert mock.header("Question 1 (19 points; estimated required time: 25 minutes)\nMarika ...") == {"points": 19, "minutes": 25, "words": None}
    assert mock.header("Question 4 (18 points; estimated required time: 30 minutes; maximum word count: 300)") == {"points": 18, "minutes": 30, "words": 300}
    assert mock.header("Question 3 (max. 500 words, 10 points)") == {"points": 10, "minutes": None, "words": 500}


def test_papers_group_in_question_order_with_their_time():
    qs = [{"id": "b", "source": mock.source("Practice exam 1", 2), "question": "Question 2 (19 points; 25 minutes)"},
          {"id": "a", "source": mock.source("Practice exam 1", 1), "question": "Question 1 (19 points; 25 minutes)"},
          {"id": "c", "source": mock.source("Mock Exam", 1), "question": "Question 1 (max. 400 words, 10 points)"},
          {"id": "x", "source": "selected files", "question": "a banked question"}]
    ps = mock.papers(qs)
    assert [p["paper"] for p in ps] == ["Mock Exam", "Practice exam 1"]
    assert [q["id"] for q in ps[1]["questions"]] == ["a", "b"] and ps[1]["minutes"] == 50 and ps[0]["minutes"] == 30


def test_question_files_pair_with_their_model_answers():
    files = [{"name": "Practice exam 1.pdf"}, {"name": "Practice exam 1 Model answers.pdf"},
             {"name": "Practice exam 2.pdf"}, {"name": "Practice exam 2 - Model answers.pdf"},
             {"name": "Questions & Answers  Mock Exam.pdf"}]
    pairs = [(t, q["name"], a["name"] if a else None) for t, q, a in mock.pair_files(files)]
    assert pairs == [("Practice exam 1", "Practice exam 1.pdf", "Practice exam 1 Model answers.pdf"),
                     ("Practice exam 2", "Practice exam 2.pdf", "Practice exam 2 - Model answers.pdf"),
                     ("Questions & Answers Mock Exam", "Questions & Answers  Mock Exam.pdf", None)]


def test_a_grade_is_cut_to_shape_and_has_no_total():
    g = mock.valid_grade({"points": [{"point": "Art 45 TFEU: Marika is a worker", "standing": "hit", "comment": "Right."},
                                     {"point": "Dir 2004/38 Art 7", "standing": "WRONG", "comment": ""}, {"point": ""}],
                          "missing": ["Lawrie-Blum"], "overall": "Good structure.", "score": 17})
    assert [p["standing"] for p in g["points"]] == ["hit", "missed"] and "score" not in g
    assert mock.valid_grade("nonsense") == {"points": [], "missing": [], "overall": ""}
