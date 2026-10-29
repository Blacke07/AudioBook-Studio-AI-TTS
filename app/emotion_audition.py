"""Build an emotional audition from the approved voice's recorded description and an explicit seed."""
from dataclasses import replace

import emotions
from voices import describe

MAX_SEED = 2147483647


def prepare_voice(recipe, fixed, emotion, seed=None):
    emotions.check(emotion)
    origin = fixed.get('origin') or {}
    if seed is None:
        seed = int(origin.get('seed', recipe.seed))
    if type(seed) is not int or not 0 <= seed <= MAX_SEED:
        raise ValueError(f'Enter a whole-number seed between 0 and {MAX_SEED}.')
    # A character's editable profile can have changed since its reference was approved.
    # The stored description is evidence of the approved recipe, not a new voice choice.
    description = describe(origin.get('design') or recipe.description)
    return replace(recipe, description=description, seed=seed,
                   instructions=f'{recipe.instructions} {emotions.instruction(emotion)}'.strip())
