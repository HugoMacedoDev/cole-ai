"""Local interview corpus. Authored answers and generic guides stay distinct."""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from dataclasses import dataclass
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = ROOT / "perguntas_entrevista_ti_mais_20mil.csv"
DEFAULT_DB = ROOT / "data" / "interview.sqlite"
ANSWERS = Path(__file__).with_name("interview_answers.json")


def normalize(text: str) -> str:
    text = text.lower().replace("c#", " csharp ").replace("c++", " cplusplus ").replace(".net", " dotnet ")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9_]+", text))


def analytical_guide(theme: str, kind: str) -> str:
    if kind == "RH":
        return (
            f"Sobre {theme}, organize a resposta em contexto, evidências, decisão e aprendizado. "
            "Escolha uma situação verdadeira da sua trajetória, explique o que você analisou, "
            "quais alternativas considerou e como colaborou com as pessoas envolvidas. "
            "Conclua com o resultado que consegue comprovar e o que faria diferente. "
            "Se a pergunta pressupõe uma experiência que você não teve, diga isso e explique como agiria."
        )
    return (
        f"Para estruturar uma resposta sobre {theme}, comece pelo problema e pelas restrições. "
        "Explique o mecanismo técnico somente se você o conhece, compare alternativas e seus custos, "
        "e descreva como validaria a escolha com testes e métricas. "
        "Em produção, inclua riscos, observabilidade e recuperação. "
        "Este roteiro não contém a definição ou implementação específica do tema; "
        "confirme tecnologia, versão e cenário antes de detalhar a solução."
    )


@dataclass(frozen=True)
class BankMatch:
    question: str
    category: str
    theme: str
    answer: str
    ready: bool
    score: float

    def offline_text(self) -> str:
        label = "Resposta pronta · base local" if self.ready else "Roteiro local · ainda sem resposta específica"
        return f"[{label}]\n{self.answer}"


def build_bank(csv_path: Path, db_path: Path, answers_path: Path = ANSWERS) -> dict[str, int]:
    """Build beside the target and replace only after all input is validated."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=db_path.parent, suffix=".sqlite", delete=False) as temp:
        temporary = Path(temp.name)
    count = 0
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.execute("CREATE TABLE questions (id INTEGER PRIMARY KEY, question TEXT, normalized TEXT, category TEXT, theme TEXT, answer TEXT, ready INTEGER)")
            db.execute("CREATE INDEX question_exact ON questions(normalized)")
            db.execute("CREATE VIRTUAL TABLE search USING fts5(normalized, content='questions', content_rowid='id')")
            with csv_path.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source, delimiter=";")
                required = {"Categoria", "Tema", "Tipo", "Pergunta"}
                if not required.issubset(reader.fieldnames or []):
                    raise ValueError("CSV deve conter Categoria, Tema, Tipo e Pergunta, separados por ponto e vírgula.")
                for row in reader:
                    question, theme = row["Pergunta"].strip(), row["Tema"].strip()
                    if not question or not theme:
                        raise ValueError(f"Pergunta ou tema vazio na linha {reader.line_num}.")
                    # Only explicitly approved authored CSV answers are served as ready.
                    ready = row.get("Aprovada", "").strip().lower() in {"sim", "true", "1"}
                    answer = row.get("Resposta", "").strip()
                    if ready and not answer:
                        raise ValueError(f"Resposta aprovada vazia na linha {reader.line_num}.")
                    db.execute("INSERT INTO questions(question,normalized,category,theme,answer,ready) VALUES (?,?,?,?,?,?)",
                               (question, normalize(question), row["Categoria"], theme,
                                answer if ready else analytical_guide(theme, row["Tipo"]), int(ready)))
                    count += 1
            prepared = json.loads(answers_path.read_text(encoding="utf-8"))
            for entry in prepared:
                if not entry["answer"].strip() or not entry["questions"]:
                    raise ValueError("Resposta preparada inválida.")
                for question in entry["questions"]:
                    db.execute("INSERT INTO questions(question,normalized,category,theme,answer,ready) VALUES (?,?,?,?,?,1)",
                               (question, normalize(question), entry["category"], entry["theme"], entry["answer"]))
            db.execute("INSERT INTO search(search) VALUES ('rebuild')")
        os.replace(temporary, db_path)
        return {"imported_questions": count, "prepared_answers": len(prepared)}
    finally:
        temporary.unlink(missing_ok=True)


class QuestionBank:
    def __init__(self, path: Path) -> None:
        self.path = path

    def lookup(self, question: str) -> BankMatch | None:
        query = normalize(question)
        if not query:
            return None
        with closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            exact = db.execute("SELECT * FROM questions WHERE normalized=? ORDER BY ready DESC", (query,)).fetchall()
            if exact:
                best = exact[0]
                if any(row["answer"] != best["answer"] for row in exact if row["ready"] == best["ready"]):
                    return None
                return self._match(best, 1.0)
            tokens = set(query.split())
            if len(tokens) < 5 or len(tokens) > 100 or question.count("?") > 1:
                return None
            expression = " OR ".join(f'"{word}"' for word in sorted(tokens))
            candidates = db.execute(
                "SELECT q.* FROM search JOIN questions q ON q.id=search.rowid WHERE search MATCH ? ORDER BY rank LIMIT 40",
                (expression,),
            ).fetchall()
        ranked: list[tuple[float, sqlite3.Row]] = []
        modifiers = {"nao", "sem", "nunca", "exceto"}
        for row in candidates:
            other = set(row["normalized"].split())
            theme_tokens = set(normalize(row["theme"]).split()) - {"e", "de", "do", "da", "em"}
            if not theme_tokens.issubset(tokens):
                continue
            if (tokens & modifiers) != (other & modifiers):
                continue
            if {t for t in tokens if t.isdigit()} != {t for t in other if t.isdigit()}:
                continue
            score = len(tokens & other) / len(tokens | other)
            ranked.append((score, row))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked or ranked[0][0] < 0.90:
            return None
        score, best = ranked[0]
        if any(score - other_score < 0.06 and row["answer"] != best["answer"] for other_score, row in ranked[1:]):
            return None
        return self._match(best, score)

    @staticmethod
    def _match(row: sqlite3.Row, score: float) -> BankMatch:
        return BankMatch(row["question"], row["category"], row["theme"], row["answer"], bool(row["ready"]), score)


def get_bank() -> QuestionBank | None:
    path = Path(os.getenv("COLA_QUESTION_DB", str(DEFAULT_DB))).resolve()
    return QuestionBank(path) if path.exists() else None
