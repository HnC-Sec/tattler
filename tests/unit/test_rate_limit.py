from tattler.notifier.rate_limit import RateLimiter


def test_first_event_passes():
    rl = RateLimiter(clock=lambda: 100.0)
    assert rl.allow("rule_a", 999, cooldown=60) is True


def test_second_event_within_cooldown_blocked():
    t = [100.0]
    rl = RateLimiter(clock=lambda: t[0])
    assert rl.allow("rule_a", 999, cooldown=60) is True
    t[0] = 130.0
    assert rl.allow("rule_a", 999, cooldown=60) is False


def test_event_after_cooldown_passes():
    t = [100.0]
    rl = RateLimiter(clock=lambda: t[0])
    assert rl.allow("rule_a", 999, cooldown=60) is True
    t[0] = 170.0
    assert rl.allow("rule_a", 999, cooldown=60) is True


def test_different_channels_independent():
    rl = RateLimiter(clock=lambda: 100.0)
    assert rl.allow("rule_a", 1, cooldown=60) is True
    assert rl.allow("rule_a", 2, cooldown=60) is True


def test_different_rules_independent():
    rl = RateLimiter(clock=lambda: 100.0)
    assert rl.allow("rule_a", 1, cooldown=60) is True
    assert rl.allow("rule_b", 1, cooldown=60) is True


def test_zero_cooldown_always_allows():
    t = [100.0]
    rl = RateLimiter(clock=lambda: t[0])
    assert rl.allow("rule_a", 1, cooldown=0) is True
    assert rl.allow("rule_a", 1, cooldown=0) is True
