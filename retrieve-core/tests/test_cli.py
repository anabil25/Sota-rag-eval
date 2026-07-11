"""Tests for cli.py — CLI command wiring and argument parsing."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrieve.cli import app

runner = CliRunner()


class TestCLIHelp:
    def test_main_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Eval-driven retrieval architecture selection" in result.output

    def test_eval_help(self):
        result = runner.invoke(app, ["eval", "--help"])
        assert result.exit_code == 0
        assert "generate" in result.output
        assert "run" in result.output
        assert "compare" in result.output
        assert "curate" in result.output

    def test_info_command(self):
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0
        assert "Architecture Registry" in result.output
        assert "Keyword only" in result.output
        assert "Embedding Models" in result.output
        assert "Reranker Models" in result.output


class TestIngestCommand:
    @patch("retrieve.ingest.run_ingest")
    def test_ingest_calls_run_ingest(self, mock_run):
        from retrieve.ingest.plugin import CorpusStats

        mock_run.return_value = CorpusStats(doc_count=10)
        result = runner.invoke(
            app, ["ingest", "--source", "/tmp/test", "--plugin", "markdown", "--output", "/tmp/out"]
        )
        assert result.exit_code == 0


class TestEvalGenerateCommand:
    @patch("retrieve.eval.generate.generate_eval_set")
    def test_eval_generate_calls_function(self, mock_gen):
        mock_gen.return_value = 1
        result = runner.invoke(
            app, ["eval", "generate", "--corpus", "/tmp/corpus", "--output", "test-v1"]
        )
        assert result.exit_code == 0
        mock_gen.assert_called_once()


class TestEvalRunCommand:
    @patch("retrieve.eval.runner.run_evaluation")
    def test_eval_run_all(self, mock_run):
        result = runner.invoke(app, ["eval", "run", "--eval-set", "v1"])
        assert result.exit_code == 0
        mock_run.assert_called_once()

    @patch("retrieve.eval.runner.run_evaluation")
    def test_eval_run_specific_archs(self, mock_run):
        result = runner.invoke(
            app, ["eval", "run", "--eval-set", "v1", "--architectures", "keyword,hybrid"]
        )
        assert result.exit_code == 0
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["architectures"] == ["keyword", "hybrid"]


class TestEvalCompareCommand:
    @patch("retrieve.eval.compare.compare_runs")
    def test_eval_compare_default(self, mock_compare):
        result = runner.invoke(app, ["eval", "compare"])
        assert result.exit_code == 0
        mock_compare.assert_called_once()

    @patch("retrieve.eval.compare.compare_runs")
    def test_eval_compare_with_runs(self, mock_compare):
        result = runner.invoke(app, ["eval", "compare", "--runs", "1,2,3"])
        assert result.exit_code == 0
        call_kwargs = mock_compare.call_args
        assert call_kwargs.kwargs["run_ids"] == [1, 2, 3]


class TestProvisionCommand:
    @patch("retrieve.provision.provision_architectures")
    def test_provision_calls_function(self, mock_prov):
        result = runner.invoke(app, ["provision"])
        assert result.exit_code == 0


class TestIndexCommand:
    @patch("retrieve.indexing.index_corpus")
    def test_index_calls_function(self, mock_idx):
        result = runner.invoke(app, ["index"])
        assert result.exit_code == 0


class TestTeardownCommand:
    @patch("retrieve.provision.teardown.teardown")
    def test_teardown_no_keep(self, mock_td):
        result = runner.invoke(app, ["teardown"])
        assert result.exit_code == 0

    @patch("retrieve.provision.teardown.teardown")
    def test_teardown_with_keep(self, mock_td):
        result = runner.invoke(app, ["teardown", "--keep", "hybrid,keyword"])
        assert result.exit_code == 0


class TestUICommand:
    @patch("uvicorn.run")
    @patch("retrieve.web.app.create_app")
    def test_ui_command(self, mock_create, mock_uvicorn):
        mock_create.return_value = MagicMock()
        result = runner.invoke(app, ["ui", "--port", "9000"])
        assert result.exit_code == 0
        mock_uvicorn.assert_called_once()
        assert mock_uvicorn.call_args.kwargs["port"] == 9000
