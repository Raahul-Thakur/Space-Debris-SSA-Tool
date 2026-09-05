from sdebris.jobs.manager import ScreeningJobManager
from sdebris.ontology.database import Database


def test_local_job_backend_uses_executor(monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_JOB_BACKEND", "thread")
    database = Database("sqlite:///:memory:")
    manager = ScreeningJobManager(database.session_factory)
    try:
        assert manager.backend == "thread"
        assert manager.executor is not None
    finally:
        manager.shutdown()
        database.engine.dispose()


def test_worker_instance_has_no_local_executor(monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_JOB_BACKEND", "redis")
    database = Database("sqlite:///:memory:")
    manager = ScreeningJobManager(database.session_factory, enable_executor=False)
    assert manager.backend == "redis"
    assert manager.executor is None
    database.engine.dispose()
