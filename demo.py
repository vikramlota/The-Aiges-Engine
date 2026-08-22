"""
Run this to see the engine work end-to-end on a handful of sample posts --
including the exact two examples from the "Audit Checklist" spreadsheet,
so you can see the code and the spreadsheet agree.

    python3 demo.py
"""

from vishwas_compliance import PostInput, audit_post, aggregate_summary
from rules import CONFIRMED_ABSENT

posts = [
    PostInput(
        client="Sample Client", influencer_handle="@sample_creator", post_url="instagram.com/p/example1",
        platform="Instagram", content_type="static_post", material_connection="paid",
        caption="#ad Loving this new serum from XYZ Skincare! My skin has never felt better.",
    ),
    PostInput(
        client="Sample Client", influencer_handle="@sample_creator_2", post_url="instagram.com/reel/example2",
        platform="Instagram", content_type="reel_story", material_connection="gifted_barter",
        caption="Had so much fun trying this out! #style #ootd #fashion #india #reels #trending #collab",
        story_label_superimposed=False,
    ),
    PostInput(
        client="Sample Client", influencer_handle="@tech_reviewer", post_url="youtube.com/watch?v=example3",
        platform="YouTube", content_type="video", material_connection="paid",
        caption="#ad My honest review of the new XYZ phone",
        video_verbal_disclosure_second=25, video_overlay_covers_sponsored_segment=True,
    ),
    PostInput(
        client="Sample Client", influencer_handle="@wellness_ai", post_url="instagram.com/p/example4",
        platform="Instagram", content_type="static_post", material_connection="paid",
        caption="#ad this supplement cleared my skin in 3 days flat",
        makes_health_finance_or_technical_claim=True, credentials_or_substantiation_shown=False,
    ),
    PostInput(
        client="Sample Client", influencer_handle="@my_own_thoughts", post_url="instagram.com/p/example5",
        platform="Instagram", content_type="static_post", material_connection="none_genuine",
        caption="Been using this for months, genuinely love it, bought it myself.",
    ),
]

results = [audit_post(p) for p in posts]

for post, result in zip(posts, results):
    print(f"\n{post.influencer_handle} -- {post.post_url}")
    print(result.summary())

print("\n" + "=" * 60)
print("SUMMARY DASHBOARD")
print("=" * 60)
summary = aggregate_summary(results)
for k, v in summary.items():
    print(f"{k}: {v}")

print("\n" + "=" * 60)
print("SPREADSHEET-COMPATIBLE ROW (first result)")
print("=" * 60)
for k, v in results[0].to_checklist_row().items():
    print(f"{k}: {v}")
