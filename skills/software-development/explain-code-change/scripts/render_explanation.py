#!/usr/bin/env python3
"""Render deterministic, offline explanation artifacts from a JSON content spec."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REQUIRED_METADATA_FIELDS = {
    "title",
    "artifact_slug",
    "change_id",
    "base_ref",
    "target_ref",
}
REQUIRED_SECTION_ORDER = ("background", "intuition", "code", "quiz")
BLOCK_TYPES = {"paragraph", "heading", "callout", "code", "list", "table", "flow", "before_after"}
CALL_OUT_TONES = {"note", "tip", "warning", "info", "critical"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a deterministic self-contained HTML explanation from JSON."
    )
    parser.add_argument("input_json", help="Path to the content-spec JSON file")
    parser.add_argument("--output", dest="output", help="Output HTML path")
    parser.add_argument("--slug", help="Slug used for default filename when --output is not set")
    parser.add_argument(
        "--artifact-dir",
        help="Default artifact directory when --output is omitted",
        default=None,
    )
    parser.add_argument("--seed", type=int, help="Seed for quiz option shuffling")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat quiz-quality warnings as hard failures",
    )
    return parser.parse_args()


def fail(message: str, code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def warn(message: str, warnings: List[str]) -> None:
    warnings.append(message)


def as_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def ensure_slug(value: Optional[str]) -> str:
    if not value:
        return "explain-code-change"
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower())
    cleaned = cleaned.strip("-_.")
    return cleaned[:64] if cleaned else "explain-code-change"


def safe_html(value: Any) -> str:
    return html.escape(as_text(value), quote=True)


def validate_metadata(metadata: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
    if not isinstance(metadata, dict):
        fail("metadata must be a JSON object")

    missing = [field for field in REQUIRED_METADATA_FIELDS if not as_text(metadata.get(field))]
    if missing:
        fail(f"metadata missing required fields: {', '.join(sorted(missing))}")

    if "seed" in metadata:
        if type(metadata["seed"]) is not int:
            warn("metadata.seed should be an integer", warnings)
    return metadata


def validate_sections(sections: Any, warnings: List[str]) -> List[Dict[str, Any]]:
    if not isinstance(sections, list):
        fail("sections must be a list")

    if len(sections) != 4:
        fail("sections must contain exactly 4 items")

    parsed_sections: List[Dict[str, Any]] = []
    for index, expected_id in enumerate(REQUIRED_SECTION_ORDER):
        section = sections[index]
        if not isinstance(section, dict):
            fail(f"section[{index}] must be an object")

        section_id = as_text(section.get("id"))
        if section_id != expected_id:
            fail(
                "sections must be in exact order: background, intuition, code, quiz. "
                f"found %r at index {index}" % section_id
            )

        blocks = section.get("blocks")
        title = as_text(section.get("title")) or expected_id.title()

        if section_id == "quiz":
            questions = section.get("questions")
            if not isinstance(questions, list):
                fail("quiz section must include a 'questions' list")
            if len(questions) != 5:
                fail("quiz must contain exactly five questions")

            for qi, question in enumerate(questions):
                if not isinstance(question, dict):
                    fail(f"quiz.questions[{qi}] must be an object")

                prompt = as_text(question.get("prompt")) or as_text(question.get("question"))
                if not prompt:
                    fail(f"quiz.questions[{qi}] missing required 'prompt' field")
                question["prompt"] = prompt

                options = question.get("options")
                if not isinstance(options, list):
                    fail(f"quiz.questions[{qi}] must include an options list")
                if not (3 <= len(options) <= 5):
                    fail(f"quiz.questions[{qi}] must have 3 to 5 options")
                if any(not as_text(option) for option in options):
                    fail(f"quiz.questions[{qi}] has empty option text")

                correct_index = question.get("correct_index")
                if type(correct_index) is not int or not (0 <= correct_index < len(options)):
                    fail(f"quiz.questions[{qi}] has invalid correct_index")
                if as_text(question.get("explanation")):
                    question["explanation"] = as_text(question.get("explanation"))

                normalized = [re.sub(r"\s+", " ", as_text(opt).lower()) for opt in options]
                if len(set(normalized)) != len(normalized):
                    warn(f"quiz question {qi + 1}: duplicated options detected", warnings)

                correct_len = len(as_text(options[correct_index]))
                distractor_lens = [len(as_text(opt)) for i, opt in enumerate(options) if i != correct_index]
                avg_distractor = sum(distractor_lens) / len(distractor_lens)
                if avg_distractor > 0:
                    ratio = max(correct_len / avg_distractor, avg_distractor / max(1, correct_len))
                    if ratio >= 2.5:
                        warn(
                            f"quiz question {qi + 1}: correct option length outlier "
                            f"(len={correct_len}, avg distractor len={avg_distractor:.1f})",
                            warnings,
                        )

            quiz = {"id": section_id, "title": title, "questions": questions}
            parsed_sections.append(quiz)
            continue

        if not isinstance(blocks, list):
            fail(f"section {section_id} requires a blocks list")
        if not blocks:
            fail(f"section {section_id} must not be empty")

        for bi, block in enumerate(blocks):
            if not isinstance(block, dict):
                fail(f"section {section_id} block[{bi}] must be an object")

            block_type = as_text(block.get("type"))
            if block_type not in BLOCK_TYPES:
                fail(f"section {section_id} block[{bi}] has invalid type {block_type!r}")

            if block_type == "paragraph":
                text = as_text(block.get("text"))
                if not text:
                    fail(f"section {section_id} block[{bi}] missing text")
                block["text"] = text
            elif block_type == "heading":
                heading_text = as_text(block.get("text"))
                if not heading_text:
                    fail(f"section {section_id} heading block[{bi}] missing text")
                level = block.get("level", 3)
                if not isinstance(level, int) or level < 2 or level > 4:
                    fail(f"section {section_id} heading block[{bi}] must have level 2..4")
            elif block_type == "callout":
                text = as_text(block.get("text"))
                if not text:
                    fail(f"section {section_id} callout block[{bi}] missing text")
                tone = as_text(block.get("tone")) or "note"
                if tone not in CALL_OUT_TONES:
                    warn(f"section {section_id} callout block[{bi}] tone {tone!r} is unknown", warnings)
                block["tone"] = tone
            elif block_type == "code":
                code = as_text(block.get("code"))
                if not code:
                    fail(f"section {section_id} code block[{bi}] missing code")
                language = as_text(block.get("language")) or "text"
                block["code"] = code
                block["language"] = language
            elif block_type == "list":
                items = block.get("items")
                if not isinstance(items, list) or not items:
                    fail(f"section {section_id} list block[{bi}] requires items")
                block["items"] = [as_text(item) for item in items]
                if not all(block["items"]):
                    fail(f"section {section_id} list block[{bi}] has empty items")
            elif block_type == "table":
                header = block.get("header")
                rows = block.get("rows")
                if not isinstance(header, list) or not all(as_text(c) for c in header):
                    fail(f"section {section_id} table block[{bi}] requires header")
                if not isinstance(rows, list):
                    fail(f"section {section_id} table block[{bi}] requires rows")
                for ri, row in enumerate(rows):
                    if not isinstance(row, list):
                        fail(f"section {section_id} table block[{bi}] row[{ri}] must be a list")
                    if len(row) != len(header):
                        warn(
                            f"section {section_id} table block[{bi}] row[{ri}] length does not match header",
                            warnings,
                        )
            elif block_type == "flow":
                steps = block.get("steps")
                if not isinstance(steps, list) or not steps:
                    fail(f"section {section_id} flow block[{bi}] requires steps")
                block["steps"] = [as_text(step) for step in steps]
                if not all(block["steps"]):
                    fail(f"section {section_id} flow block[{bi}] has empty steps")
            elif block_type == "before_after":
                before = block.get("before")
                after = block.get("after")
                if not isinstance(before, list) or not isinstance(after, list):
                    fail(f"section {section_id} before_after block[{bi}] requires before and after lists")
                if not before or not after:
                    warn(f"section {section_id} before_after block[{bi}] should include both before and after", warnings)
            
            block_type_entry = block.get("type")
            if block_type_entry not in BLOCK_TYPES:
                fail(f"section {section_id} includes invalid block type {block_type_entry!r}")

        parsed_sections.append({
            "id": section_id,
            "title": title,
            "blocks": blocks,
        })

    return parsed_sections


def balance_and_shuffle_questions(
    questions: List[Dict[str, Any]],
    seed: int,
    warnings: List[str],
) -> List[Dict[str, Any]]:
    position_counts = [0, 0, 0, 0, 0]
    balanced: List[Dict[str, Any]] = []

    for index, question in enumerate(questions):
        options = [as_text(opt) for opt in question["options"]]
        correct_index = int(question["correct_index"])
        correct_text = options[correct_index]
        distractors = [options[i] for i in range(len(options)) if i != correct_index]

        rng = random.Random(seed + index)
        max_positions = len(options)
        min_count = min(position_counts[:max_positions])
        candidate_positions = [i for i in range(max_positions) if position_counts[i] == min_count]
        chosen_position = rng.choice(candidate_positions)

        rng.shuffle(distractors)
        rendered_options: List[str] = []
        distractor_index = 0
        for slot in range(max_positions):
            if slot == chosen_position:
                rendered_options.append(correct_text)
            else:
                rendered_options.append(distractors[distractor_index])
                distractor_index += 1

        if len(set(rendered_options)) != len(rendered_options):
            warn(f"quiz question has become ambiguous after shuffle: duplicate options", warnings)

        position_counts[chosen_position] += 1
        balanced.append(
            {
                "question_id": as_text(question.get("id")) or f"q{index + 1}",
                "prompt": as_text(question["prompt"]),
                "explanation": as_text(question.get("explanation", "")),
                "options": rendered_options,
                "correct_index": chosen_position,
            }
        )

    return balanced


def render_nested_blocks(blocks: Sequence[Any], warnings: List[str]) -> str:
    html_parts: List[str] = []
    for item in blocks:
        if isinstance(item, str):
            html_parts.append(f"<p>{safe_html(item)}</p>")
            continue
        if not isinstance(item, dict):
            warn("encountered unsupported content block while rendering before_after", warnings)
            continue
        html_parts.append(render_block(item, warnings))
    return "\n".join(html_parts)


def render_block(block: Dict[str, Any], warnings: List[str]) -> str:
    block_type = as_text(block.get("type"))
    if block_type == "paragraph":
        return f"<p>{safe_html(block.get('text', ''))}</p>"

    if block_type == "heading":
        level = int(block.get("level", 3))
        tag = "h3" if level < 2 or level > 4 else f"h{level}"
        return f"<{tag}>{safe_html(block.get('text', ''))}</{tag}>"

    if block_type == "callout":
        tone = as_text(block.get("tone")) or "note"
        return (
            f"<aside class='callout callout-{safe_html(tone)}'>"
            f"<p>{safe_html(block.get('text', ''))}</p>"
            "</aside>"
        )

    if block_type == "code":
        code = safe_html(block.get("code", ""))
        lang = safe_html(block.get("language", "text"))
        return (
            f"<figure class='code-block'><figcaption>{safe_html(block.get('label', ''))}</figcaption>"
            f"<pre><code class='language-{lang}'>{code}</code></pre></figure>"
        )

    if block_type == "list":
        ordered = bool(block.get("ordered"))
        tag = "ol" if ordered else "ul"
        items = "".join(f"<li>{safe_html(item)}</li>" for item in block.get("items", []))
        return f"<{tag} class='content-list'>{items}</{tag}>"

    if block_type == "table":
        header = [safe_html(cell) for cell in block.get("header", [])]
        rows = block.get("rows", [])
        header_html = "".join(f"<th>{cell}</th>" for cell in header)
        row_parts = []
        for row in rows:
            if not isinstance(row, list):
                continue
            padded = list(row) + ["" for _ in range(len(header) - len(row))]
            cells = "".join(f"<td>{safe_html(cell)}</td>" for cell in padded[:len(header)])
            row_parts.append(f"<tr>{cells}</tr>")
        return (
            "<div class='table-wrap'><table class='content-table'>"
            f"<thead><tr>{header_html}</tr></thead>"
            f"<tbody>{''.join(row_parts)}</tbody></table></div>"
        )

    if block_type == "flow":
        items = "".join(f"<li>{safe_html(step)}</li>" for step in block.get("steps", []))
        return f"<ol class='flow-list'>{items}</ol>"

    if block_type == "before_after":
        before = render_nested_blocks(block.get("before", []), warnings)
        after = render_nested_blocks(block.get("after", []), warnings)
        title = safe_html(block.get("title", "Before and after"))
        return (
            f"<section class='before-after'><h4>{title}</h4>"
            f"<div class='ba-grid'><div><h5>Before</h5>{before}</div>"
            f"<div><h5>After</h5>{after}</div></div></section>"
        )

    warn(f"unhandled block type: {block_type}", warnings)
    return ""


def render_quiz(questions: List[Dict[str, Any]]) -> Tuple[str, str]:
    rendered = []
    quiz_payload = []

    for index, question in enumerate(questions):
        qid = question["question_id"]
        options = question["options"]
        rendered_options = "".join(
            f"<li><button type='button' class='option' data-question='{index}' "
            f"data-option='{option_index}'>{safe_html(option)}</button></li>"
            for option_index, option in enumerate(options)
        )
        rendered.append(
            f"<article class='quiz-question' data-question-index='{index}'>"
            f"<p class='quiz-prompt'>{safe_html(question['prompt'])}</p>"
            f"<ul class='quiz-options'>{rendered_options}</ul>"
            f"<p class='quiz-feedback' aria-live='polite' data-question='{index}'></p>"
            "</article>"
        )
        quiz_payload.append(
            {
                "question": qid,
                "options_count": len(options),
                "correct_index": question["correct_index"],
                "explanation": question.get("explanation", ""),
            }
        )

    return "\n".join(rendered), json.dumps(quiz_payload, ensure_ascii=False)


def render_html(
    metadata: Dict[str, Any],
    sections: List[Dict[str, Any]],
    quiz_payload: List[Dict[str, Any]],
    warnings: List[str],
) -> str:
    toc = [
        (section["id"], safe_html(section.get("title", section["id"])))
        for section in sections
    ]

    body_sections: List[str] = []
    quiz_data_json = "[]"
    for section in sections:
        sec_id = section["id"]
        title = safe_html(section.get("title", sec_id.title()))

        if sec_id == "quiz":
            questions_html, quiz_data_json = render_quiz(quiz_payload)
            section_body = (
                f"<section id='quiz' class='card'>"
                f"<h2>{title}</h2>"
                "<p class='section-intro'>Attempt each question once. Feedback is provided as text.</p>"
                f"{questions_html}"
                "</section>"
            )
            body_sections.append(section_body)
            continue

        blocks = "\n".join(render_block(block, warnings) for block in section.get("blocks", []))
        body_sections.append(f"<section id='{sec_id}' class='card'><h2>{title}</h2>{blocks}</section>")

    safe_quiz_json = (
        quiz_data_json
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{safe_html(metadata['title'])}</title>
<style>
:root {{
  --bg: #f3f6fc;
  --panel: #ffffff;
  --panel-border: #d7e0ee;
  --text: #0f1a2d;
  --muted: #3a4a64;
  --accent: #2152cc;
  --accent-strong: #163d95;
  --ok: #1b7f4f;
  --warn: #b95a00;
  --danger: #a31a1a;
  --focus: #2451ff;
}}

* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: "Trebuchet MS", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  color: var(--text);
  background: linear-gradient(135deg, #f5f8ff 0%, #edf3ff 40%, #ffffff 100%);
  line-height: 1.55;
}}

main {{
  max-width: 980px;
  margin: 2rem auto;
  padding: 1rem;
}}

h1, h2, h3, h4, h5 {{
  margin: 0 0 0.7rem;
  line-height: 1.2;
}}

.card {{
  background: var(--panel);
  border: 1px solid var(--panel-border);
  border-radius: 12px;
  padding: 1rem 1.15rem;
  margin-bottom: 1rem;
  box-shadow: 0 12px 28px rgba(20, 40, 90, 0.06);
}}

#table-of-contents {{
  position: sticky;
  top: 0.5rem;
  background: rgba(255, 255, 255, 0.85);
  border: 1px dashed var(--panel-border);
  border-radius: 10px;
  margin-bottom: 1rem;
  padding: 0.75rem 1rem;
  backdrop-filter: blur(3px);
}}

.toc-list {{
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}}

.toc-list a {{
  text-decoration: none;
  color: var(--accent);
  padding: 0.2rem 0.5rem;
  border-radius: 999px;
  border: 1px solid #d2ddf4;
}}

.toc-list a:focus-visible {{
  outline: 3px solid var(--focus);
  outline-offset: 2px;
}}

.callout {{
  border-left: 4px solid var(--accent);
  padding: 0.6rem 0.8rem;
  border-radius: 8px;
  margin: 0.6rem 0;
  background: #edf3ff;
}}

.callout-tip {{ border-left-color: #0f7a66; background: #edf9f4; }}
.callout-warning {{ border-left-color: #9a5a00; background: #fff3db; }}
.callout-critical {{ border-left-color: #9c1d1d; background: #ffe9e9; }}

.code-block {{
  margin: 0.8rem 0;
}}

pre {{
  margin: 0;
  overflow-x: auto;
  white-space: pre-wrap;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 0.85rem;
}}

.content-list, .flow-list {{
  padding-left: 1.25rem;
}}

.table-wrap {{ overflow-x: auto; }}
.content-table {{
  width: 100%;
  border-collapse: collapse;
  margin-top: 0.5rem;
}}

.content-table th, .content-table td {{
  border: 1px solid #d6e1f5;
  text-align: left;
  padding: 0.6rem;
}}

.content-table th {{
  background: #f2f6fe;
}}

.before-after {{
  margin-top: 0.75rem;
}}
.ba-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}}

.quiz-options {{
  list-style: none;
  margin: 0.75rem 0;
  padding: 0;
  display: grid;
  gap: 0.45rem;
}}

.option {{
  width: 100%;
  text-align: left;
  border: 1px solid #d2deee;
  border-radius: 8px;
  padding: 0.65rem 0.75rem;
  cursor: pointer;
  background: #f8fbff;
  color: var(--text);
}}

.option:focus-visible,
button:focus-visible {{
  outline: 3px solid var(--focus);
  outline-offset: 2px;
}}

.option.is-correct {{
  border-color: var(--ok);
  background: #e8f8ee;
}}

.option.is-incorrect {{
  border-color: var(--danger);
  background: #fdecec;
}}

.quiz-feedback {{
  font-weight: 600;
}}

.quiz-feedback.correct {{
  color: var(--ok);
}}

.quiz-feedback.incorrect {{
  color: var(--danger);
}}

@media (max-width: 760px) {{
  main {{
    margin: 0.6rem auto;
    padding: 0.75rem;
  }}
  .ba-grid {{
    grid-template-columns: 1fr;
  }}
}}

@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }}
}}
</style>
</head>
<body>
  <main>
    <header class="card">
      <h1>{safe_html(metadata['title'])}</h1>
      <p>Change: {safe_html(metadata['change_id'])}</p>
      <p>From {safe_html(metadata['base_ref'])} to {safe_html(metadata['target_ref'])}</p>
    </header>
    <nav id="table-of-contents" class="card" aria-label="Table of contents">
      <strong>Contents</strong>
      <ul class="toc-list">""" + "".join(
        f'<li><a href="#{sid}">{name}</a></li>' for sid, name in toc
      ) + """
      </ul>
    </nav>
    """ + "\n".join(body_sections) + """
  </main>

  <script>
    const QUIZ_DATA = """ + safe_quiz_json + """;
    document.addEventListener('DOMContentLoaded', () => {
      const feedbacks = Array.from(document.querySelectorAll('.quiz-feedback'));
      const buttons = document.querySelectorAll('.option');
      buttons.forEach((button) => {
        button.addEventListener('click', () => {
          const qIndex = Number(button.dataset.question);
          const selected = Number(button.dataset.option);
          const data = QUIZ_DATA[qIndex];
          const questionButtons = Array.from(
            document.querySelectorAll(`.quiz-question[data-question-index="${qIndex}"] .option`)
          );
          if (questionButtons.some((item) => item.disabled)) {
            return;
          }
          questionButtons.forEach((item) => {
            item.disabled = true;
            item.classList.remove('is-correct', 'is-incorrect');
          });
          const isCorrect = selected === data.correct_index;
          button.classList.add(isCorrect ? 'is-correct' : 'is-incorrect');
          const correctButton = questionButtons[data.correct_index];
          if (correctButton) {
            correctButton.classList.add('is-correct');
          }
          const feedback = document.querySelector(`.quiz-feedback[data-question="${qIndex}"]`);
          if (!feedback) {
            return;
          }
          if (isCorrect) {
            feedback.textContent = 'Correct: Your selection matches the expected behavior.';
            feedback.className = 'quiz-feedback correct';
          } else {
            feedback.textContent = `Incorrect: The correct option is option ${data.correct_index + 1}.`;
            feedback.className = 'quiz-feedback incorrect';
          }
          if (data.explanation) {
            feedback.textContent += ` ${data.explanation}`;
          }
        });
      });
    });
  </script>
</body>
</html>
"""


def write_html(output_path: Path, content: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, output_path)
    os.chmod(output_path, 0o600)


def main() -> None:
    args = parse_args()
    warnings: List[str] = []

    try:
        data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"cannot read content spec: {exc}")
    except json.JSONDecodeError as exc:
        fail(f"content spec is not valid JSON: {exc}")
    if not isinstance(data, dict):
        fail("content spec must be a JSON object")

    metadata = validate_metadata(data.get("metadata", {}), warnings)
    sections = validate_sections(data.get("sections", []), warnings)

    seed = args.seed
    if seed is None:
        metadata_seed = metadata.get("seed")
        seed = metadata_seed if type(metadata_seed) is int else 4242

    non_quiz_sections = [section for section in sections if section["id"] != "quiz"]
    quiz_section = next(section for section in sections if section["id"] == "quiz")

    shuffled = balance_and_shuffle_questions(quiz_section["questions"], seed, warnings)

    html_text = render_html(metadata, non_quiz_sections + [
        {"id": "quiz", "title": quiz_section.get("title", "Quiz")},
    ], shuffled, warnings)

    default_artifact_dir = Path(args.artifact_dir) if args.artifact_dir else Path.home() / ".hermes" / "artifacts" / "explain-code-change"
    default_slug = ensure_slug(args.slug or metadata.get("artifact_slug"))
    date_prefix = datetime.now().strftime("%Y-%m-%d")

    output_path = (
        Path(args.output)
        if args.output
        else default_artifact_dir / f"{date_prefix}-{default_slug}.html"
    )

    if warnings:
        print("Quality warnings:", file=sys.stderr)
        for item in warnings:
            print(f" - {item}", file=sys.stderr)
        if args.strict:
            fail("strict mode enabled: validation failed due to quality warnings", 2)

    write_html(output_path, html_text)
    print(output_path)


if __name__ == "__main__":
    main()
