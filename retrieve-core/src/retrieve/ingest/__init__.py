from retrieve.ingest import run


def run_ingest(*args, **kwargs):
	return run.run_ingest(*args, **kwargs)

__all__ = ["run_ingest"]
