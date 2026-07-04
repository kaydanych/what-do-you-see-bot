import re

from photobot.strings import DEFAULT_LANG, STRINGS, t


def placeholders(s: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", s))


def test_all_languages_have_same_keys():
    key_sets = {lang: set(table) for lang, table in STRINGS.items()}
    ru = key_sets["ru"]
    for lang, keys in key_sets.items():
        assert keys == ru, f"{lang} keys differ from ru"


def test_placeholders_match_across_languages():
    for key in STRINGS["ru"]:
        expected = placeholders(STRINGS["ru"][key])
        for lang in STRINGS:
            assert placeholders(STRINGS[lang][key]) == expected, f"{lang}/{key}"


def test_t_falls_back_to_default():
    assert t(None, "LATE") == STRINGS[DEFAULT_LANG]["LATE"]
    assert t("de", "LATE") == STRINGS[DEFAULT_LANG]["LATE"]
    assert "10" in t("en", "COLLAGE_CAPTION", n=10)
