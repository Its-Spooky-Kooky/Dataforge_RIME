"""
Phonetic and scientific text preprocessor for laboratory nomenclature.
Transforms complex laboratory IDs, units, chemistry formulas, and metric measurements
into natural phonetic representations optimized for Rime TTS (Coda and Mist models).
"""

import re
from typing import Dict

# Number to English words conversion dictionary
ONES = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four",
    5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
    10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
    15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen"
}

TENS = {
    2: "twenty", 3: "thirty", 4: "forty", 5: "fifty",
    6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety"
}

# NATO-style phonetic spelling for isolated single letters in lab tubes
LETTER_PHONETICS: Dict[str, str] = {
    "A": "ay", "B": "bee", "C": "cee", "D": "dee", "E": "ee",
    "F": "eff", "G": "jee", "H": "aitch", "I": "eye", "J": "jay",
    "K": "kay", "L": "ell", "M": "em", "N": "en", "O": "oh",
    "P": "pee", "Q": "cue", "R": "ar", "S": "ess", "T": "tee",
    "U": "you", "V": "vee", "W": "double-you", "X": "ex", "Y": "why", "Z": "zee"
}


def number_to_words(n: int) -> str:
    """Convert an integer up to 999,999 to English words."""
    if n < 0:
        return "negative " + number_to_words(abs(n))
    if n in ONES:
        return ONES[n]
    if n < 100:
        ten = n // 10
        rem = n % 10
        return TENS[ten] if rem == 0 else f"{TENS[ten]}-{ONES[rem]}"
    if n < 1000:
        hundred = n // 100
        rem = n % 100
        base = f"{ONES[hundred]} hundred"
        return base if rem == 0 else f"{base} {number_to_words(rem)}"
    if n < 1000000:
        thousands = n // 1000
        rem = n % 1000
        base = f"{number_to_words(thousands)} thousand"
        return base if rem == 0 else f"{base} {number_to_words(rem)}"
    return str(n)


def decimal_to_words(s: str) -> str:
    """Convert a decimal number string like '0.5' to 'zero point five'."""
    parts = s.split(".")
    if len(parts) != 2:
        return s
    whole = int(parts[0]) if parts[0].isdigit() else 0
    whole_words = number_to_words(whole)
    dec_digits = [ONES[int(d)] for d in parts[1] if d.isdigit()]
    return f"{whole_words} point {' '.join(dec_digits)}"


class LabPhoneticNormalizer:
    """Normalizes laboratory scientific text into phonetic tokens for Rime TTS."""

    def __init__(self):
        # Specific known chemical formulas and scientific terms
        self.chemical_map = {
            r"\bH2O2\b": "H-two-O-two",
            r"\bCO2\b": "C-O-two",
            r"\bNaCl\b": "sodium chloride",
            r"\bEtOH\b": "ethanol",
            r"\bPBS\b": "P-B-S",
            r"\bEDTA\b": "E-D-T-A",
            r"\bDMSO\b": "D-M-S-O",
            r"\bBSL-([1-4])\b": r"B-S-L \1",
            r"\bOD600\b": "O-D six hundred",
        }

    def normalize_tube_ids(self, text: str) -> str:
        """
        Convert laboratory alphanumeric tube/plate/rack identifiers:
        - '4B' -> 'four-bee'
        - '12C' -> 'twelve-cee'
        - 'A3' -> 'ay-three'
        - 'P2' -> 'pee-two'
        """
        # Pattern 1: Number followed by single letter (e.g., 4B, 12C, 102A)
        def num_letter_repl(match):
            num = int(match.group(1))
            letter = match.group(2).upper()
            letter_phone = LETTER_PHONETICS.get(letter, letter.lower())
            return f"{number_to_words(num)}-{letter_phone}"

        text = re.sub(r"\b([0-9]{1,4})([A-Za-z])\b", num_letter_repl, text)

        # Pattern 2: Single letter followed by number (e.g., A3, P2, T7)
        def letter_num_repl(match):
            letter = match.group(1).upper()
            num = int(match.group(2))
            letter_phone = LETTER_PHONETICS.get(letter, letter.lower())
            return f"{letter_phone}-{number_to_words(num)}"

        text = re.sub(r"\b([A-Za-z])([0-9]{1,4})\b", letter_num_repl, text)
        return text

    def normalize_units_and_metrics(self, text: str) -> str:
        """
        Normalizes scientific units, percentages, concentrations, and speeds.
        - '15%' -> 'fifteen percent'
        - '0.5µL' -> 'zero point five microliters'
        - '250 RPM' -> 'two hundred fifty R-P-M'
        - 'pH 7.4' -> 'p-H seven point four'
        """
        # pH normalization: pH 7.4 or pH 7
        def ph_repl(match):
            val = match.group(1)
            if "." in val:
                return f"p-H {decimal_to_words(val)}"
            return f"p-H {number_to_words(int(val))}"

        text = re.sub(r"\bpH\s*([0-9]+(?:\.[0-9]+)?)\b", ph_repl, text, flags=re.IGNORECASE)

        # Temperature: 37°C or 37 C or 37C or -80°C
        def temp_repl(match):
            sign = match.group(1) or ""
            val = int(match.group(2))
            words = number_to_words(val)
            prefix = "minus " if sign == "-" else ""
            return f"{prefix}{words} degrees Celsius"

        text = re.sub(r"(-)?\b([0-9]{1,3})\s*(?:°\s*C|°C|deg\s*C)\b", temp_repl, text, flags=re.IGNORECASE)

        # RPM: e.g. 3000 RPM or 2400RPM
        def rpm_repl(match):
            num = int(match.group(1))
            return f"{number_to_words(num)} R-P-M"

        text = re.sub(r"\b([0-9]+)\s*RPM\b", rpm_repl, text, flags=re.IGNORECASE)

        # Percent: 15% or 0.5%
        def pct_repl(match):
            num_str = match.group(1)
            if "." in num_str:
                return f"{decimal_to_words(num_str)} percent"
            return f"{number_to_words(int(num_str))} percent"

        text = re.sub(r"\b([0-9]+(?:\.[0-9]+)?)\s*%", pct_repl, text)

        # Microliters: µL, uL, ul
        def ul_repl(match):
            num_str = match.group(1)
            words = decimal_to_words(num_str) if "." in num_str else number_to_words(int(num_str))
            return f"{words} microliters"

        text = re.sub(r"\b([0-9]+(?:\.[0-9]+)?)\s*(?:µL|uL|ul)\b", ul_repl, text)

        # Milliliters: mL, ml
        def ml_repl(match):
            num_str = match.group(1)
            words = decimal_to_words(num_str) if "." in num_str else number_to_words(int(num_str))
            return f"{words} milliliters"

        text = re.sub(r"\b([0-9]+(?:\.[0-9]+)?)\s*(?:mL|ml)\b", ml_repl, text)

        # Milligrams / grams: mg, g
        def mg_repl(match):
            num_str = match.group(1)
            words = decimal_to_words(num_str) if "." in num_str else number_to_words(int(num_str))
            return f"{words} milligrams"

        text = re.sub(r"\b([0-9]+(?:\.[0-9]+)?)\s*(?:mg)\b", mg_repl, text)

        # Concentrations: mg/mL, mg/dL
        def conc_repl(match):
            num_str = match.group(1)
            denom = match.group(2).lower()
            words = decimal_to_words(num_str) if "." in num_str else number_to_words(int(num_str))
            unit_name = "milliliter" if denom == "ml" else "deciliter"
            return f"{words} milligrams per {unit_name}"

        text = re.sub(r"\b([0-9]+(?:\.[0-9]+)?)\s*mg/(mL|dL|ml|dl)\b", conc_repl, text)

        # General decimal numbers like 0.8 -> zero point eight
        def dec_repl(match):
            return decimal_to_words(match.group(0))

        text = re.sub(r"\b([0-9]+)\.([0-9]+)\b", dec_repl, text)

        return text

    def normalize_chemicals(self, text: str) -> str:
        """Replace chemical formulas and standard lab acronyms."""
        for pattern, replacement in self.chemical_map.items():
            text = re.sub(pattern, replacement, text)
        return text

    def enforce_prosody_and_pauses(self, text: str) -> str:
        """
        Enforce natural pauses and sentence chunking for Rime streaming TTS:
        - Replaces semi-colons with periods.
        - Cleans double spaces.
        - Ensures short clauses that the ear processes smoothly.
        """
        text = text.replace(";", ".")
        text = re.sub(r"\s+", " ", text).strip()
        # Ensure proper comma spacing for rhythmic TTS pauses
        text = re.sub(r"\s*,\s*", ", ", text)
        text = re.sub(r"(?<!\d)\s*\.\s*(?!\d)", ". ", text)
        return text.strip()

    def normalize(self, text: str) -> str:
        """
        Complete normalization pipeline for Rime TTS synthesis.
        """
        if not text:
            return ""

        # Step 1: Normalize tube / sample IDs first before other rules touch letters
        res = self.normalize_tube_ids(text)
        # Step 2: Normalize chemical formulas and abbreviations
        res = self.normalize_chemicals(res)
        # Step 3: Normalize units, metrics, decimals, and percentages
        res = self.normalize_units_and_metrics(res)
        # Step 4: Prosody, punctuation, and flow
        res = self.enforce_prosody_and_pauses(res)
        return res


# Global singleton instance for quick import
normalizer = LabPhoneticNormalizer()


def normalize_for_rime(text: str) -> str:
    """Helper functional interface for TTS pre-processing."""
    return normalizer.normalize(text)
