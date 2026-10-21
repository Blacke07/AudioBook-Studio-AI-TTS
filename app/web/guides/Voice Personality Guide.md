# Character Voice Personality Guide

## Start with personality, then choose the sound

A pleasant timbre alone does not establish a character. Pace, humor, relationships and reactions under
pressure shape the performance. Write a preview in the character's own manner: a fixed reference voice
also carries the delivery of the approved sample.

The bundled narrator is a synthetic demonstration. Use it immediately, or audition and fix your own voice.

**Editing a description does not replace a fixed voice.** A fixed voice continues to use its approved WAV
and exact reference text. Choose a new take and click Fix only when you intend to change that voice.
Reading, copying or downloading this guide changes no voices or settings.

## Prepare your source material

Give the prompt below to an assistant that can access your story's character notes, glossary and relevant
chapters. Replace the example character list and source names. A prompt does not grant an assistant
access to local files. AudioBook Studio does not send these documents to an online assistant for you.

Separate established story facts from proposed acoustic choices. Require verified quotations and chapter
references. If sources are missing, leave those fields incomplete rather than inventing evidence.

The adjacent **Voice Sheet Example.md** is fictional demonstration material, not a real book extract.

## Complete prompt to copy

```text
I need VOICE SHEETS for an English-language audiobook of my story, for these speakers:
Narrator, Alex, Morgan [replace this list and add other characters as needed].

Use the story's canon/reference notes, character glossary and relevant chapters, including any notes
about comic delivery. Do not invent traits that contradict the story. When the sources do not establish
something, mark it "(proposal)". If you cannot access a source, say exactly what you cannot verify.
Do not fabricate quotations, chapter numbers or evidence. Do not claim to have read unavailable files.

For EACH speaker, complete exactly these fields in this order:

- Gender and age:
- Origin / accent (for American English: urban, rural, educated, working-class, regional nuances, etc.):
- Register and timbre (low/middle/high; rough, velvety, hoarse, clear, breathy, etc.):
- Tempo and rhythm (slow, quick, deliberate pauses, short sentences, etc.):
- Speaking personality on 0–5 scales:
  sarcasm __, warmth __, energy __, formality __, deadpan humor __, visible vulnerability __
- Type of humor, if any: describe what the voice actually does when joking.
  Example: "States the absurd completely seriously, without an audible smile."
- How the speaker talks to each other character: one sentence per relationship.
- Under pressure / in danger: how the voice changes.
- What this voice must NEVER do: boundaries that prevent caricature.
- Voice description in English: 2–3 sentences suitable for the voice generator.
- Delivery directions in English: 1–2 sentences.
- NEW PREVIEW LINE in English: approximately 35–55 words, aiming for 12–20 seconds when spoken.
  Write a fresh sample in the character's typical voice and humor. No other characters' names, quotation
  marks or speech tags. Use complete sentences and a natural conversational rhythm.
- A second, calmer or more serious preview of the same approximate length, for comparison.
- Three real lines from the book, with chapter references, that should sound convincing in this voice.

For the Narrator, the new previews should be narrative prose, not a character's dialogue.
Identify the volume as well when chapter numbering is ambiguous. Preserve real quotations exactly.
If you cannot find three verified lines, mark the missing examples instead of inventing them.
The preview duration is a target, not a measured result until actual audio exists.

At the end, include:
- The character pairs that must sound most distinct, and the audible differences between them.
  Example: "Alex is clipped and grounded; Morgan is precise and clear with longer, even phrasing."
- How much the Narrator should perform the characters in speech tags and prose, on a 0–5 scale.

Do not edit the book, application settings or approved voices. Deliver the sheets for the author's review.
```

## Transfer the result into AudioBook Studio

1. **Name, aliases and gender:** use the matching fields in Characters.
2. **Context for speaker detection:** summarize the role, relationships and speaking habits. This helps
   speaker attribution; it does not create the sound of the voice by itself.
3. **Model → VoiceDesign**, then **Voice description → Custom description:** paste the English voice
   description. Add any character-specific directions after `Delivery:` in the same description.
4. **Character sample — personality (English):** paste only the text to be spoken. Do not paste the whole
   sheet, headings, labels or multiple quotations into this field.
5. **Listen:** compare the performance with the sheet. Check the actual duration rather than relying only
   on word count. For an already fixed voice, Listen uses the existing reference. Find a more distinct voice
   auditions the description without automatically replacing the reference.
6. **Fix / Fix this voice:** choose this only after approving the take. Its WAV and exact text become the
   reference used for later passages.

The narrator has separate description and delivery fields on the Narrator page. Keep any reference you
already like until you explicitly choose a replacement. A seed selects a sampling take; temperature
controls sampling variation. Neither replaces the identity provided by a fixed reference.

The three real quotations help check suitability. Compare important pairs by listening: a written sheet
and an embedding score cannot guarantee that listeners will distinguish two synthesized voices.

## Scope

These Markdown sheets are reference documents. There is no automatic Markdown-to-character import in
this workflow. Opening the guide does not generate audio, change characters or contact an online service.
Each installation stores one shared character glossary; consider that before reusing names across books.
