"""English numbers, ordinals, money, times and titles written out in words, so the engine does not guess them.

Conservative on purpose: only clear patterns change, everything else is left as the author wrote it. The source text
is never touched; this is applied to the spoken version (an edit by the author in Spoken text still wins).
"""
import re

ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
        "seventeen eighteen nineteen").split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
SCALES = ((10 ** 9, "billion"), (10 ** 6, "million"), (10 ** 3, "thousand"))
ORDINAL_ENDINGS = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
                   "nine": "ninth", "twelve": "twelfth"}
TITLES = {"Mr": "Mister", "Mrs": "Missus", "Ms": "Miss", "Dr": "Doctor", "Prof": "Professor", "Capt": "Captain",
          "Col": "Colonel", "Gen": "General", "Lt": "Lieutenant", "Sgt": "Sergeant", "Mt": "Mount",
          "Rev": "Reverend", "Gov": "Governor", "Sen": "Senator"}
PHRASES = {"vs.": "versus", "e.g.": "for example,", "i.e.": "that is,"}
CURRENCY = {"$": ("dollar", "dollars", "cent", "cents"), "£": ("pound", "pounds", "penny", "pence"),
            "€": ("euro", "euros", "cent", "cents")}
YEAR_CUES = r"(?:in|since|of|by|from|until|till|during|before|after|around|circa|year|summer|winter|spring|autumn|fall)"


def cardinal(number):
    if number < 20:
        return ONES[number]
    if number < 100:
        tens, rest = divmod(number, 10)
        return TENS[tens] + (f"-{ONES[rest]}" if rest else "")
    if number < 1000:
        hundreds, rest = divmod(number, 100)
        return f"{ONES[hundreds]} hundred" + (f" {cardinal(rest)}" if rest else "")
    for size, name in SCALES:
        if number >= size:
            high, rest = divmod(number, size)
            return f"{cardinal(high)} {name}" + (f" {cardinal(rest)}" if rest else "")
    raise ValueError(number)


def ordinal(number):
    prefix, last = re.match(r"^(.*?)([a-z]+)$", cardinal(number)).groups()
    last = ORDINAL_ENDINGS.get(last) or (last[:-1] + "ieth" if last.endswith("y") else last + "th")
    return prefix + last


def year(number):
    """1998 -> nineteen ninety-eight, 1905 -> nineteen oh five, 2007 -> two thousand seven, 2010 -> twenty ten."""
    if 2000 <= number < 2010:
        return "two thousand" + (f" {ONES[number - 2000]}" if number > 2000 else "")
    high, low = divmod(number, 100)
    if low == 0:
        return f"{cardinal(high)} hundred"
    return f"{cardinal(high)} {'oh ' + ONES[low] if low < 10 else cardinal(low)}"


def _integer(text):
    return int(text.replace(",", ""))


def _decimal(text):
    whole, _, fraction = text.partition(".")
    spoken = cardinal(_integer(whole))
    return spoken + (" point " + " ".join(ONES[int(digit)] for digit in fraction) if fraction else "")


def _money(match):
    unit, amount, scale = match.group(1), match.group(2), (match.group(3) or "").lower()
    singular, plural, minor, minors = CURRENCY[unit]
    if scale:
        return f"{_decimal(amount)} {scale} {plural}"
    whole, _, fraction = amount.partition(".")
    value = _integer(whole)
    words = f"{cardinal(value)} {singular if value == 1 else plural}"
    if len(fraction) == 2 and int(fraction):
        cents = int(fraction)
        words += f" and {cardinal(cents)} {minor if cents == 1 else minors}"
    return words


def _time(match):
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 24 or minute > 59:
        return match.group(0)
    spoken = cardinal(hour)
    if minute:
        spoken += " oh " + ONES[minute] if minute < 10 else " " + cardinal(minute)
    return spoken + (" " + match.group(3).lower().replace(".", "") if match.group(3) else "")


def _year_phrase(match):
    number = int(match.group(2))
    return f"{match.group(1)} {year(number)}"


def _decade(match):
    base = int(match.group(1))
    spoken = year(base)
    if base % 100 == 0:
        return spoken + "s"
    words = spoken.rsplit(" ", 1)
    last = words[-1]
    last = last[:-1] + "ies" if last.endswith("y") else last + "s"
    return " ".join(words[:-1] + [last])


def normalize(text):
    """The text with numbers, money, times, ordinals and common titles spelled out."""
    for title, spoken in TITLES.items():
        text = re.sub(rf"\b{title}\.(?=\s+[A-Z])", spoken, text)
    for short, spoken in PHRASES.items():
        text = re.sub(rf"(?<![\w.]){re.escape(short)}(?!\w)", spoken, text)
    text = re.sub(r"(?<![\w.])etc\.(\s+[A-Z\"“]|\s*$|(?=[\"”)]))", lambda m: "et cetera." + m.group(1), text)
    text = re.sub(r"(?<![\w.])etc\.", "et cetera", text)
    text = re.sub(r"([$£€])(\d+(?:,\d{3})*(?:\.\d+)?)(?:\s?(million|billion|thousand)\b)?", _money, text)
    text = re.sub(r"\b(\d{1,2}):(\d{2})(?:\s?([AaPp]\.?[Mm]\.?))?(?![\d:])", _time, text)
    text = re.sub(r"\b(1[1-9]\d0|20[0-9]0)s\b", _decade, text)
    text = re.sub(rf"\b({YEAR_CUES})\s+(1[1-9]\d\d|20\d\d)\b(?!,\d)", _year_phrase, text, flags=re.I)
    text = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", lambda m: ordinal(int(m.group(1))), text)
    text = re.sub(r"\b(\d+(?:,\d{3})*(?:\.\d+)?)\s?%", lambda m: f"{_decimal(m.group(1))} percent", text)
    text = re.sub(r"(?<![\w.,/])(?<!\d-)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\w/]|-\d|\.\d)",
                  lambda m: _decimal(m.group(0)) if m.group(2) else cardinal(_integer(m.group(1))), text)
    return text
