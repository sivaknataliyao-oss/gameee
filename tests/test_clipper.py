from src.video.clipper import plan_from_timings


def test_plan_splits_long_chapters():
    plans = plan_from_timings([(0.0, 200.0, "hook1"), (200.0, 260.0, "hook2")], max_short_sec=75.0)
    # first chapter is 200s -> 3 windows; second is 60s -> 1 window
    assert len(plans) == 4
    assert plans[0].index == 1 and plans[-1].index == 4
    for p in plans[:3]:
        assert (p.end_sec - p.start_sec) <= 75 + 1e-6
