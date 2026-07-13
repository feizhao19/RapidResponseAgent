import unittest

from web.api.job_progress import PROGRESS_TOTAL, apply_progress_event, load_progress


class JobProgressTests(unittest.TestCase):
    def test_weighted_progress_with_vipde_tiles(self) -> None:
        from web.api.jobs import create_job, get_job

        job = create_job(aoi_id="upload_test", auto_match_pre=True)
        job_id = job["job_id"]

        apply_progress_event(job_id, {"type": "step_done", "step": "upload"})
        apply_progress_event(job_id, {"type": "step_done", "step": "align"})
        apply_progress_event(job_id, {"type": "step_done", "step": "route"})
        apply_progress_event(
            job_id,
            {"type": "step_start", "step": "perception", "message": "Running ViPDE…"},
        )
        apply_progress_event(
            job_id,
            {
                "type": "units",
                "step": "perception",
                "unit_current": 10,
                "unit_total": 40,
                "unit_label": "ViPDE tiles",
                "message": "ViPDE tiles 10/40",
            },
        )

        progress = load_progress(get_job(job_id))
        self.assertEqual(progress["unit_current"], 10)
        self.assertEqual(progress["unit_total"], 40)
        self.assertGreater(progress["overall_current"], 0)
        self.assertLess(progress["overall_current"], PROGRESS_TOTAL)
        self.assertEqual(progress["overall_total"], PROGRESS_TOTAL)
        self.assertEqual(PROGRESS_TOTAL, 100)

    def test_mark_complete_sets_full_progress(self) -> None:
        from web.api.jobs import create_job, get_job

        job = create_job(aoi_id="upload_test", auto_match_pre=True)
        job_id = job["job_id"]
        apply_progress_event(job_id, {"type": "step_done", "step": "upload"})

        from web.api.job_progress import mark_job_progress_complete

        mark_job_progress_complete(job_id)
        progress = load_progress(get_job(job_id))
        self.assertEqual(progress["overall_current"], 100)
        self.assertEqual(progress["overall_total"], 100)


if __name__ == "__main__":
    unittest.main()
