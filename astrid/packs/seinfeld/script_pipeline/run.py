#!/usr/bin/env python3
"""seinfeld.script_pipeline - generate short Seinfeld-style script scenes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_SYSTEM_BASE = (
    "You are a comedy writer with deep knowledge of Seinfeld's voice and "
    "rhythm. You write tight, fast scenes - no fat."
)

DEFAULT_PROMPT = (
    "Write a VERY SHORT Seinfeld scene - about 30 seconds of screen time. "
    "Keep it to 8-12 short lines of dialogue total. "
    "Kramer bursts in EXTREMELY excited about open source AI. "
    "George is skeptical / dismissive. "
    "Jerry is confused - keeps interrupting with 'Who?' / 'What?' because "
    "none of the names or terms register. "
    "End on a button (one clean closing line). "
    "Format as a script: NAME: line. No stage directions beyond the opening."
)

SYSTEM_SYNTH = (
    "You are a comedy writer with a deep ear for Seinfeld's rhythm. "
    "Your one job in this pass is STRUCTURE - turning multiple rough attempts "
    "into a single coherent scene. Don't worry about polishing character "
    "voices yet; that's a later pass. Just thread the best material."
)

SYSTEM_VOICE = """You are a script doctor for Seinfeld. You receive a structurally-correct draft scene and your ONLY job is to fix lines that violate character voice. You do NOT restructure, reorder, add, or remove lines. You replace individual lines that sound wrong with versions that sound right. After the voice pass, you insert laugh tags.

CHARACTER VOICES - concrete rules:

GEORGE doesn't construct cute analogies. He panics, catastrophizes, and complains about specific people (his mother, his boss, an ex). His comedy comes from his neuroses leaking out, not from clever metaphors.
  WRONG: "Open source - what is that, a food bank for algorithms?"
  WRONG: "They share models like it's potluck for the singularity."
  RIGHT: "Free? Nothing's free. My mother gave me free advice for thirty years and look at me."

JERRY's voice is FLAT and declarative, not literary. He repeats himself slightly. He doesn't do poetic phrasings or clever buttons.
  WRONG: "I barely tolerate them at standard pitch."
  WRONG: "The one thing I asked the universe to forget."
  WRONG: "My fridge is open source, and it only knows to chill."
  RIGHT: "I don't want my thoughts fine-tuned. My thoughts are fine. Actually they're not, but I'm not adjusting them."

KRAMER is CONCRETE-ABSURD, not ideological or abstract. He physicalizes everything. He doesn't talk about "liberty" or "democratization" - he talks about specific objects in his apartment.
  WRONG: "It's democratizing intelligence!"
  WRONG: "It's about liberty! Digital liberty!"
  WRONG: "It'll tell you your soup is too salty in iambic pentameter."
  RIGHT: "I got a llama in my closet writing my Christmas cards."
  RIGHT: "It's running on the Roomba, Jerry - the Roomba!"

LAUGH TAGS - after the voice fixes, insert at most 5 tags total, ONLY on the biggest beats. Forms: [LAUGHTER], [BIG LAUGHTER], [LAUGHTER AND APPLAUSE]. Plus [APPLAUSE] on Kramer's entrance and [END SCENE] at the end. Do NOT tag every line.

Output ONLY the corrected script. No commentary."""

SYSTEM_JUDGE = """You are judging generated Seinfeld-style short scene scripts. Pick the single strongest candidate for:
- concrete Kramer physical absurdity over abstract tech talk
- Jerry's flat confusion and simple closing line
- George's neurotic specificity
- coherent escalation in about 30 seconds
- sparse laugh tags on actual beats

Return strict JSON only: {"winner": <1-based index>, "reason": "<one concise paragraph>"}."""


@dataclass(frozen=True)
class Candidate:
    index: int
    work_dir: Path
    md_path: Path
    final_scene: str
    draft_scene: str
    attempts_blob: str


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _call_deepseek(api_key: str, messages: list[dict], temperature: float, max_tokens: int = 8192) -> dict:
    body = {
        "model": "deepseek-v4-pro",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    last_error: Exception | None = None
    for attempt in range(1, 4):
        request = Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=320) as response:
                payload = response.read().decode("utf-8")
            break
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if 400 <= exc.code < 500 and exc.code != 429:
                raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
            last_error = RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}")
        except URLError as exc:
            last_error = RuntimeError(f"DeepSeek request failed: {exc}")
        if attempt < 3:
            wait_seconds = 2 ** attempt
            print(f"DeepSeek call failed; retrying in {wait_seconds}s ({attempt}/3): {last_error}", file=sys.stderr)
            time.sleep(wait_seconds)
    else:
        raise RuntimeError(str(last_error))
    data = json.loads(payload)
    if "error" in data:
        raise RuntimeError(f"DeepSeek API error: {data['error']}")
    return data


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_synth_prompt(prompt: str, attempts_blob: str) -> str:
    return f"""Below are 5 attempts at a 30-second Seinfeld scene.

Original brief:
{prompt}

Pick the strongest weird ideas, specific name-jokes, and character-true beats from across the attempts, and weave them into ONE coherent ~12-line scene. Loose threading - connected enough to flow, not so neat it reads as a sketch.

Rules for this pass:
- Preserve the brief's requested wackiness level: funny, wacky, somewhat grounded in reality, and also over the top. Favor Seinfeld-style comic escalation over surreal sci-fi, random escalation, or pure tech-name jokes.
- Choose one concrete, playable modern-life problem or object as the scene engine. The final scene should feel like it could physically happen in Jerry's apartment today.
- Keep the absurdity practical: Kramer's scheme can be ridiculous, but it should involve specific objects, errands, apartments, neighbors, dating, food, money, etiquette, or daily inconvenience.
- Open with a one-line stage direction: location + what each character is doing.
- Kramer bursts in early.
- Include the "puffy shirt" callback if any attempt has it.
- Add a small physical beat (eating cereal, opening fridge, etc.) inline somewhere mid-scene.
- End on an action or exit line (Kramer leaving, Jerry walking away) - NOT a clever metaphor.
- NO laugh tags this pass. Just dialogue.
- Output ONLY the script. No commentary, no headers.

ATTEMPTS:

{attempts_blob}
"""


def _build_voice_prompt(draft_scene: str) -> str:
    return f"""Here is the draft scene. Find lines that violate the character-voice rules and rewrite ONLY those lines in place. Leave any line that already sounds right untouched. Do not change the structure, the order, or the count of lines. Then insert the laugh tags per the rules above.

DRAFT:

{draft_scene}
"""


def _run_candidate(
    *,
    index: int,
    api_key: str,
    produces_dir: Path,
    prompt: str,
    rough_attempts: int,
) -> Candidate:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_id = f"{stamp}_{index:02d}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    work_dir = produces_dir / "work" / run_id
    work_dir.mkdir(parents=True, exist_ok=False)

    def base_run(attempt_index: int) -> str:
        print(f"candidate {index}: starting rough attempt {attempt_index}...", file=sys.stderr)
        data = _call_deepseek(
            api_key,
            [
                {"role": "system", "content": DEFAULT_SYSTEM_BASE},
                {"role": "user", "content": prompt},
            ],
            temperature=2.0,
        )
        content = data["choices"][0]["message"]["content"]
        _write_text(work_dir / f"scene_{attempt_index}.txt", content)
        print(f"candidate {index}: done rough attempt {attempt_index}", file=sys.stderr)
        return content

    print(f"candidate {index}: generating {rough_attempts} rough scenes...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=rough_attempts) as pool:
        scenes = list(pool.map(base_run, range(1, rough_attempts + 1)))

    attempts_blob = "\n\n---\n\n".join(
        f"### Attempt {attempt_index + 1}\n\n{scene.strip()}"
        for attempt_index, scene in enumerate(scenes)
    )
    print(f"candidate {index}: synthesizing structure...", file=sys.stderr)
    data = _call_deepseek(
        api_key,
        [
            {"role": "system", "content": SYSTEM_SYNTH},
            {"role": "user", "content": _build_synth_prompt(prompt, attempts_blob)},
        ],
        temperature=1.0,
    )
    draft_scene = data["choices"][0]["message"]["content"].strip()
    _write_text(work_dir / "draft_scene.txt", draft_scene)

    print(f"candidate {index}: applying voice + laugh pass...", file=sys.stderr)
    data = _call_deepseek(
        api_key,
        [
            {"role": "system", "content": SYSTEM_VOICE},
            {"role": "user", "content": _build_voice_prompt(draft_scene)},
        ],
        temperature=1.0,
    )
    final_scene = data["choices"][0]["message"]["content"].strip()

    md_path = produces_dir / "candidates" / f"candidate_{index:02d}_{run_id}.md"
    md = f"""# Seinfeld Script Pipeline - candidate {index}

*3-phase pipeline:*
1. *Ideation - {rough_attempts}x DeepSeek V4 Pro at temp 2.0*
2. *Synthesis - 1x DeepSeek at temp 1.0, structure only*
3. *Voice + laugh tags - 1x DeepSeek at temp 1.0, character-voice doctor*

---

## Final scene (after voice pass)

{final_scene}

---

## Phase 2 draft (before voice pass)

{draft_scene}

---

## Source attempts (phase 1)

{attempts_blob}
"""
    _write_text(md_path, md)
    print(md_path)
    return Candidate(index, work_dir, md_path, final_scene, draft_scene, attempts_blob)


def _judge_best(api_key: str, candidates: list[Candidate]) -> tuple[int, str]:
    if len(candidates) == 1:
        return candidates[0].index, "Only one candidate was generated."
    blob = "\n\n---\n\n".join(
        f"## Candidate {candidate.index}\n\n{candidate.final_scene}"
        for candidate in candidates
    )
    data = _call_deepseek(
        api_key,
        [
            {"role": "system", "content": SYSTEM_JUDGE},
            {"role": "user", "content": blob},
        ],
        temperature=0.2,
        max_tokens=1024,
    )
    content = data["choices"][0]["message"]["content"].strip()
    try:
        payload = json.loads(content)
        winner = int(payload["winner"])
        reason = str(payload["reason"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Judge returned invalid JSON: {content}") from exc
    if winner not in {candidate.index for candidate in candidates}:
        raise RuntimeError(f"Judge selected unknown candidate {winner}")
    return winner, reason


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Seinfeld-style short scene scripts.")
    parser.add_argument("--produces-dir", type=Path, required=True)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Scene brief.")
    parser.add_argument("--prompt-file", type=Path, help="Read scene brief from a text file.")
    parser.add_argument("--candidates", type=int, default=1, help="Complete pipeline candidates to generate.")
    parser.add_argument("--rough-attempts", type=int, default=5, help="Rough attempts per candidate.")
    parser.add_argument("--select-best", action="store_true", help="Use a judge pass to select the best candidate.")
    parser.add_argument("--open-result", action="store_true", help="Open selected_scene.md after writing it.")
    parser.add_argument("--env-file", type=Path, default=Path.home() / ".hermes" / ".env")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.candidates < 1:
        raise SystemExit("--candidates must be >= 1")
    if args.rough_attempts < 1:
        raise SystemExit("--rough-attempts must be >= 1")

    _load_env_file(args.env_file)
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is required")

    prompt = args.prompt_file.read_text(encoding="utf-8").strip() if args.prompt_file else args.prompt
    produces_dir: Path = args.produces_dir
    produces_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[Candidate] = []
    max_workers = min(args.candidates, 5)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(
                _run_candidate,
                index=index,
                api_key=api_key,
                produces_dir=produces_dir,
                prompt=prompt,
                rough_attempts=args.rough_attempts,
            )
            for index in range(1, args.candidates + 1)
        ]
        for future in as_completed(futures):
            candidates.append(future.result())
    candidates.sort(key=lambda candidate: candidate.index)

    if args.select_best or len(candidates) == 1:
        winner_index, judge_reason = _judge_best(api_key, candidates)
    else:
        winner_index = candidates[0].index
        judge_reason = "Selection skipped; defaulted to first candidate."
    selected = next(candidate for candidate in candidates if candidate.index == winner_index)

    selected_md = selected.md_path.read_text(encoding="utf-8")
    selected_md += f"\n---\n\n## Selection\n\nWinner: candidate {winner_index}\n\n{judge_reason}\n"
    selected_path = produces_dir / "selected_scene.md"
    _write_text(selected_path, selected_md)

    manifest = {
        "prompt": prompt,
        "candidates": [
            {
                "index": candidate.index,
                "markdown": str(candidate.md_path),
                "work_dir": str(candidate.work_dir),
            }
            for candidate in candidates
        ],
        "selected_index": winner_index,
        "selected_scene": str(selected_path),
        "judge_reason": judge_reason,
    }
    _write_text(produces_dir / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    print(f"selected: {selected_path}")

    if args.open_result:
        subprocess.run(["open", str(selected_path)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
