from tattler.invites import extract_invite_codes


def test_extracts_discord_gg_short_form():
    assert extract_invite_codes("come join discord.gg/abc123") == ["abc123"]


def test_extracts_https_discord_gg():
    assert extract_invite_codes("https://discord.gg/abc123 yo") == ["abc123"]


def test_extracts_discord_com_invite():
    assert extract_invite_codes("see https://discord.com/invite/xyz789") == ["xyz789"]


def test_extracts_discordapp_com_invite():
    assert extract_invite_codes("https://discordapp.com/invite/legacy42") == ["legacy42"]


def test_extracts_with_www_prefix():
    assert extract_invite_codes("https://www.discord.gg/abc") == ["abc"]


def test_extracts_multiple_invites_in_order():
    text = "first discord.gg/aaa then https://discord.com/invite/bbb and discord.gg/ccc"
    assert extract_invite_codes(text) == ["aaa", "bbb", "ccc"]


def test_deduplicates_repeated_codes_preserving_order():
    text = "discord.gg/dup discord.gg/other discord.gg/dup"
    assert extract_invite_codes(text) == ["dup", "other"]


def test_no_invites_returns_empty_list():
    assert extract_invite_codes("nothing to see here") == []


def test_code_charset_allows_hyphens():
    assert extract_invite_codes("discord.gg/abc-def-123") == ["abc-def-123"]


def test_strips_trailing_punctuation():
    # Common case: invite URL followed by sentence punctuation.
    # The regex captures code until non-[a-zA-Z0-9-], so this is implicit.
    assert extract_invite_codes("Join discord.gg/abc!") == ["abc"]


def test_does_not_match_random_substrings():
    # "abc.gg/xxx" should not match — must be discord host.
    assert extract_invite_codes("abc.gg/notreal") == []
