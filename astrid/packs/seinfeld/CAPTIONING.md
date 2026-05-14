# Seinfeld LoRA — Captioning Standard

This is the load-bearing doc for how we caption training data. It encodes the
LTX 2.3 four-section format and the trigger-token-vs-anchor-phrase strategy.
If you change the captioning approach, change THIS file first, then update
`vocab_compile.py` and `dataset_build/run.py` to match.

## Principle: match the model's training distribution

LTX 2.3 was trained on a specific caption distribution. Departing from it
loses signal even if a different format "feels" cleaner. We follow the
official format even when it costs more pipeline complexity.

## The four sections (verbatim, every caption)

```
Scene: A {shot_type} shot inside {scene_token}. {character_anchors_assembled}.
       {camera}. {scene_description}
Speech: "{verbatim_quote}" — {speaker}, {tone}.
        ... (one line per spoken line, in order)
        (or the literal line "No spoken dialogue." when none)
Sounds: {laugh_track_clause}. {ambient}. {music_clause}.
Style: Seinfeld sitcom, 90s NBC multi-cam look, studio sitcom lighting.
```

Concrete example:

```
Scene: A wide shot inside jerrys_apt. George, a short stocky balding man with
       glasses, wearing a polo shirt and chinos. Jerry, a thin man in his
       thirties with short dark hair, wearing a button-down shirt and jeans.
       Static camera, medium-wide framing. George stands by the door while
       Jerry naps on the couch; George approaches and shakes his shoulder.
Speech: "Jerry. Jerry, wake up." — George, hushed and urgent.
        "What. What is it." — Jerry, drowsy and irritated.
Sounds: Studio audience laughter present after Jerry's line. Soft apartment
        ambience, a refrigerator hum. No music.
Style: Seinfeld sitcom, 90s NBC multi-cam look, studio sitcom lighting.
```

## Why each section matters

| Section | What it gives the LoRA |
|---|---|
| **Scene (visual)** | Discrete scene token (`jerrys_apt`/`monks_diner`) becomes the *select-a-location* control at inference. Character anchors repeated verbatim across the dataset become learned identifiers via repetition (the LTX/WaveSpeed "Tom Shelby" pattern). Camera + action describe motion the LoRA must reproduce. |
| **Speech (verbatim)** | LTX 2.3 generates audio as well as video. Verbatim quotes anchor dialogue rhythm, cadence, and tone — *the* defining feature of Seinfeld. Omitting them trains off-distribution from the base model's captioner. |
| **Sounds** | Laugh track is a Seinfeld-style fingerprint; the slap-bass between-scene cue is iconic. Capturing both lets the LoRA inherit them. Ambient is free-text so descriptive richness isn't bounded. |
| **Style (repeated)** | The literal `style_suffix` is appended to every caption verbatim. Repetition anchors the style without burning a discrete trigger-token slot. |

## What we did NOT do, and why

| Option | Rejected because |
|---|---|
| Special token per `(character × outfit)` (e.g. `GeorgePolo`, `JerryButton`) | (1) Goal is a STYLE LoRA, not identity-replication. (2) ~30 clips across 7 (char × outfit) cells is too sparse to learn each as a discrete identifier. (3) Competes with scene tokens for rank-32 LoRA capacity. (4) Brittle at inference — natural-language outfit clauses inside the character anchor are easier to prompt. |
| Free-text scene description instead of `scene` token | The whole point of the token is to give the user an inference-time switch. "A wide shot of a 90s NYC apartment with exposed brick" lets the model wander; `jerrys_apt` doesn't. |
| Omit dialogue to keep captions short | LTX 2.3's official auto-captioner emits speech transcription as a first-class section. Omitting it trains off-distribution. The pipeline cost of running Whisper per clip is acceptable. |
| Use `visual_understand` (single frame) for the caption | Frames don't describe motion. A 12-second clip with "George enters" and "George sits down" both look like "George at a door" if you only see the midpoint. We use `video_understand` (Gemini, video-native, audio-aware) for captions. |
| Auto-generated trigger token (one global token, prepended) | The LTX trainer's global-trigger flag is for a *single* style trigger. Doesn't help us — we need multiple locations selectable at inference. We use scene tokens inside the caption text, not the trainer's global trigger. |
| Caption only verbatim speech + minimal action (Ostris recipe) | Ostris's *burn-in vs describe* rule (LTX-2.3 character LoRA tutorial, YT `JQIl8DFTL1M`): omitted attributes get burned into the LoRA, described ones stay prompt-controllable. He omits clothing/scene to lock them in. We do the **opposite** on purpose — describing `jerrys_apt`/`monks_diner` + outfits keeps them as inference-time switches, since we're training a style LoRA with selectable locations, not a single-character identity LoRA. Be aware of the tradeoff: our rich captions are intentional, not an oversight. |

## Where each section comes from in the pipeline

| Section | Source executor | Output goes into |
|---|---|---|
| Scene (visual + characters + camera + action) | `builtin.video_understand --response-schema schemas/caption.json` (Gemini, sees both motion and audio) | `scene` / `shot_type` / `characters_visible` / `outfits_by_character` / `camera` / `scene_description` |
| Speech (verbatim quotes) | `builtin.transcribe` (Whisper) → fed as context into the same `video_understand` call so it can attribute speakers using the picture | `speech_transcription[]` |
| Sounds | `builtin.video_understand` (Gemini is audio-aware) | `sounds.{laugh_track, music, ambient}` |
| On-screen text | `builtin.video_understand` (sees the video) | `on_screen_text` |
| Style suffix | Constant from `vocabulary.yaml#style_suffix` | Last line of `caption` |
| Final assembled `caption` string | The VLM assembles per the schema's `caption` field description | `caption` |

## Hash inputs that invalidate captions

When any of these change, the orchestrator re-captions affected clips
(content-addressed freshness in `dataset_build`):

- `vocabulary.yaml` content (vocab_hash)
- `schemas/caption.json` content (schema_hash)
- The caption prompt template version (caption_prompt_hash)
- The clip's audio transcript (transcript content — included in the
  caption prompt, so changes in dialogue rewrite captions)

## Re-using this pattern for other LoRA projects

Drop-in process for a future style LoRA on a different show / domain:

1. Copy `astrid/packs/seinfeld/` to `astrid/packs/<yourproject>/`.
2. Edit `vocabulary.yaml`: list your locked scenes, characters with
   `base_description` + `outfit_variants`, shot types, `style_suffix`,
   `sound_features`.
3. Run `python3 -m astrid.packs.<yourproject>.vocab_compile` to regenerate
   schemas.
4. Edit `dataset_build/run.py`'s `BUCKET_QUERIES` and bucket-target
   defaults; everything else stays the same.

The 4-section format is LTX-2.3-wide, not Seinfeld-specific. Anything in
this doc above the "Re-using" section applies to any LTX 2.3 LoRA project.

## Sources

- [Lightricks/LTX-2 — dataset-preparation.md](https://github.com/Lightricks/LTX-2/blob/main/packages/ltx-trainer/docs/dataset-preparation.md) — official four-section format
- [LTX-2.3 LoRA Training Guide — WaveSpeed (2026)](https://wavespeed.ai/blog/posts/ltx-2-3-lora-training-guide-2026/) — Scene/Action/Music structured prompting
- [How To Fine-Tune A Video Generation Model With LoRA — Lightricks blog](https://ltx.io/model/model-blog/how-to-fine-tune-a-video-generation-model-with-lora)
- [malcolmrey/wan — captioning settings discussion](https://huggingface.co/malcolmrey/wan/discussions/4) — comparable WAN practice
- Banodoco Discord — `ltx_training`, `ltx_chatter`, `daily_summaries`
  channels (cseti007, oumoumad, LDWorks David, fredbliss, Kijai)
