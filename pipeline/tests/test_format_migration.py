"""P0 cadence->format rename: Post legacy-value shim + migration docID parsing."""

from app.models import Format, Post
from scripts.migrate_cadence_to_format import (
    BACKWARD,
    FORWARD,
    remap_channel_id,
    remap_prompt_id,
)

# ---------- Post legacy-cadence compat shim ----------


def test_post_accepts_legacy_cadence_values():
    assert Post(cadence="daily", categoryId="c").format is Format.short
    assert Post(cadence="weekly", categoryId="c").format is Format.article
    assert Post(cadence="monthly", categoryId="c").format is Format.report


def test_post_native_format_unaffected():
    assert Post(format="short", categoryId="c").format is Format.short


def test_post_prefers_format_when_both_present():
    # A doc mid-migration could carry both; the new field wins, no crash.
    p = Post(format="article", cadence="daily", categoryId="c")
    assert p.format is Format.article


def test_post_dump_writes_format_not_cadence():
    dumped = Post(cadence="weekly", categoryId="c").model_dump()
    assert dumped["format"] == "article"
    assert "cadence" not in dumped


# ---------- migration docID remap (pure) ----------


def test_remap_prompt_id_forward():
    assert remap_prompt_id("science-technology_daily", FORWARD) == "science-technology_short"
    assert remap_prompt_id("geopolitics-history_monthly", FORWARD) == "geopolitics-history_report"


def test_remap_prompt_id_preserves_underscored_category():
    # Category slug may contain '_' — split from the END only.
    assert remap_prompt_id("a_b_c_weekly", FORWARD) == "a_b_c_article"


def test_remap_prompt_id_ignores_unknown_or_migrated():
    assert remap_prompt_id("cat_short", FORWARD) is None   # already migrated
    assert remap_prompt_id("cat_foo", FORWARD) is None     # unknown token
    assert remap_prompt_id("cadence", FORWARD) is None      # no separator


def test_remap_channel_id_forward():
    assert remap_channel_id("business-economics_daily_x", FORWARD) == "business-economics_short_x"
    assert remap_channel_id("a_b_weekly_notion", FORWARD) == "a_b_article_notion"


def test_remap_channel_id_ignores_unknown_or_short():
    assert remap_channel_id("cat_short_x", FORWARD) is None  # already migrated
    assert remap_channel_id("cat_foo_x", FORWARD) is None    # unknown token
    assert remap_channel_id("cat_x", FORWARD) is None        # too few tokens


def test_remap_is_reversible_with_backward():
    assert remap_prompt_id("cat_short", BACKWARD) == "cat_daily"
    assert remap_channel_id("cat_report_threads", BACKWARD) == "cat_monthly_threads"
    # forward then backward is identity for known docs
    fwd = remap_prompt_id("cat_weekly", FORWARD)
    assert remap_prompt_id(fwd, BACKWARD) == "cat_weekly"
