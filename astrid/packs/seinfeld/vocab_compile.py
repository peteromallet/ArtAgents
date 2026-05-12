#!/usr/bin/env python3
"""Vocabulary → schemas compiler for the Seinfeld dataset.

Reads vocabulary.yaml, derives bucket_judge.json and caption.json schemas,
and writes them to schemas/. Provides compute_vocab_hash for content-addressed
freshness checking.

Run as an inline pre-step inside dataset_build/run.py.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml


def compute_vocab_hash(yaml_text: str) -> str:
    """sha256 over canonicalized vocabulary content.

    Parses YAML (which strips comments), then hashes a deterministic
    JSON-serialized form with sorted keys — stable across environments.
    """
    data = yaml.safe_load(yaml_text)
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _build_bucket_judge_schema(vocab: dict, hash_hex: str) -> dict:
    scenes = list(vocab.get("scenes", {}).keys())
    characters = list(vocab.get("characters", {}).keys())
    return {
        "x_generated_from_vocab_hash": hash_hex,
        "x_schema_dialect": "json-schema-draft-07",
        "type": "object",
        "required": ["scene", "confidence", "characters_present"],
        "properties": {
            "scene": {
                "type": "string",
                "description": "Which Seinfeld scene this frame belongs to.",
                "enum": sorted(scenes),
            },
            "confidence": {
                "type": "number",
                "description": "Confidence 0–1 that this is the correct scene.",
                "minimum": 0,
                "maximum": 1,
            },
            "characters_present": {
                "type": "array",
                "description": "Characters visible in the frame.",
                "items": {"type": "string", "enum": sorted(characters)},
            },
            "reasoning": {
                "type": "string",
                "description": "Brief explanation of the judgement.",
            },
        },
    }


def _build_caption_schema(vocab: dict, hash_hex: str) -> dict:
    """LTX 2.3 four-section caption schema.

    Follows the official Lightricks dataset-preparation contract:
    Scene / Speech / Sounds / Style (with explicit on_screen_text).
    See CAPTIONING.md for sources and rationale.
    """
    scenes = sorted(vocab.get("scenes", {}).keys())
    characters = sorted(vocab.get("characters", {}).keys())
    shot_types = sorted(vocab.get("shot_types", []))

    # Per-character outfit_variant enums (from base_description + outfit_variants[*]).
    outfit_variant_props: dict[str, dict] = {}
    for name, info in vocab.get("characters", {}).items():
        if isinstance(info, dict) and "outfit_variants" in info:
            outfit_variant_props[name] = {
                "type": "string",
                "description": f"Which outfit variant for {name} is visible.",
                "enum": sorted(info["outfit_variants"].keys()),
            }

    sound_features = vocab.get("sound_features", {}) or {}
    laugh_track_states = sorted(sound_features.get("laugh_track_states", ["present", "absent"]))
    music_states = sorted(sound_features.get("music_states", ["none", "score", "diegetic"]))

    return {
        "x_generated_from_vocab_hash": hash_hex,
        "x_schema_dialect": "json-schema-draft-07",
        "x_format": "LTX 2.3 four-section",
        "type": "object",
        "required": [
            "scene",
            "shot_type",
            "characters_visible",
            "outfits_by_character",
            "camera",
            "scene_description",
            "speech_transcription",
            "sounds",
            "on_screen_text",
            "caption",
        ],
        "properties": {
            # --- Section 1: SCENE (visual content) ---
            "scene": {
                "type": "string",
                "description": "DISCRETE TOKEN — which Seinfeld location. Used verbatim in the final caption.",
                "enum": scenes,
            },
            "shot_type": {
                "type": "string",
                "description": "DISCRETE TOKEN — camera shot type.",
                "enum": shot_types,
            },
            "characters_visible": {
                "type": "array",
                "description": "Named characters clearly visible in the clip, in left-to-right order if multiple.",
                "items": {"type": "string", "enum": characters},
            },
            "outfits_by_character": {
                "type": "object",
                "description": (
                    "For each character in characters_visible, which outfit_variant they are wearing. "
                    "Pick the closest match from the enum — do NOT invent new tokens."
                ),
                "properties": outfit_variant_props,
            },
            "camera": {
                "type": "string",
                "description": "Camera motion and framing in one short clause. Examples: 'static, medium-wide framing', 'slow handheld push-in', 'static, locked-off two-shot'.",
            },
            "scene_description": {
                "type": "string",
                "description": "What the characters are doing in this clip, in one or two sentences. Action verbs, motion across the clip. Do NOT redescribe their identity — that's in the anchor phrase.",
            },
            # --- Section 2: SPEECH TRANSCRIPTION (verbatim) ---
            "speech_transcription": {
                "type": "array",
                "description": (
                    "Word-for-word transcription of spoken dialogue, in order. "
                    "Match the audio exactly — do not paraphrase. Empty array if no dialogue."
                ),
                "items": {
                    "type": "object",
                    "required": ["speaker", "quote", "tone"],
                    "properties": {
                        "speaker": {
                            "type": "string",
                            "description": "Speaker name from the character vocabulary, or 'unknown' if off-screen / unnamed.",
                            "enum": characters + ["unknown"],
                        },
                        "quote": {
                            "type": "string",
                            "description": "The verbatim quote, with punctuation. Use ellipses for trailing-off speech.",
                        },
                        "tone": {
                            "type": "string",
                            "description": "Short tone descriptor (e.g. 'flat', 'agitated', 'hushed and urgent', 'dry').",
                        },
                    },
                },
            },
            # --- Section 3: SOUNDS (non-speech audio) ---
            "sounds": {
                "type": "object",
                "required": ["laugh_track", "music", "ambient"],
                "properties": {
                    "laugh_track": {
                        "type": "string",
                        "description": "Whether the iconic studio audience laugh track is audible.",
                        "enum": laugh_track_states,
                    },
                    "music": {
                        "type": "string",
                        "description": "Music presence. 'bass_slap_transition' is the signature Seinfeld between-scene slap-bass.",
                        "enum": music_states,
                    },
                    "ambient": {
                        "type": "string",
                        "description": "Short free-text description of non-speech ambient sound (e.g. 'low diner chatter', 'refrigerator hum', 'silence').",
                    },
                },
            },
            # --- Section 4: ON-SCREEN TEXT ---
            # NOTE: kept as plain string (empty when none) — Gemini's
            # response_schema enforcer rejects ["string","null"] unions
            # with AttributeError on .upper() (May 2026).
            "on_screen_text": {
                "type": "string",
                "description": "Any visible on-screen text (signs, captions, lower-thirds). Empty string if none.",
            },
            # --- The assembled final caption ---
            "caption": {
                "type": "string",
                "description": (
                    "The fully-assembled LTX 2.3 caption following the four-section format. "
                    "MUST be assembled exactly per CAPTIONING.md:\n"
                    "  Scene: A {shot_type} shot inside {scene}. {character_anchors_assembled}. {camera}. {scene_description}\n"
                    "  Speech: {quoted_lines or 'No spoken dialogue.'}\n"
                    "  Sounds: {laugh_track_clause}. {ambient}. {music_clause}.\n"
                    "  Style: <verbatim style_suffix from vocabulary>\n"
                    "Use the canonical character_anchor verbatim — do not paraphrase."
                ),
            },
        },
    }
    # Note: omitting `additionalProperties: False` at the top level — some Gemini
    # response_schema modes reject it; the model still adheres to required keys.


def compile_schemas(
    vocab_path: Path, schemas_dir: Path
) -> tuple[Path, Path, str]:
    """Read vocabulary.yaml and write bucket_judge.json + caption.json.

    Returns (judge_path, caption_path, vocab_hash).
    """
    yaml_text = vocab_path.read_text(encoding="utf-8")
    vocab = yaml.safe_load(yaml_text)
    if not isinstance(vocab, dict):
        raise ValueError(f"vocabulary.yaml must contain a YAML mapping, got {type(vocab)}")

    hash_hex = compute_vocab_hash(yaml_text)

    judge_schema = _build_bucket_judge_schema(vocab, hash_hex)
    caption_schema = _build_caption_schema(vocab, hash_hex)

    schemas_dir.mkdir(parents=True, exist_ok=True)

    judge_path = schemas_dir / "bucket_judge.json"
    caption_path = schemas_dir / "caption.json"

    judge_path.write_text(json.dumps(judge_schema, indent=2) + "\n", encoding="utf-8")
    caption_path.write_text(json.dumps(caption_schema, indent=2) + "\n", encoding="utf-8")

    return judge_path, caption_path, hash_hex


if __name__ == "__main__":
    import sys

    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    vocab_path = repo_root / "astrid" / "packs" / "seinfeld" / "vocabulary.yaml"
    schemas_dir = repo_root / "astrid" / "packs" / "seinfeld" / "schemas"

    if not vocab_path.exists():
        print(f"Error: vocabulary.yaml not found at {vocab_path}", file=sys.stderr)
        sys.exit(1)

    judge_path, caption_path, h = compile_schemas(vocab_path, schemas_dir)
    print(f"vocab_compile: hash={h}")
    print(f"  wrote {judge_path}")
    print(f"  wrote {caption_path}")