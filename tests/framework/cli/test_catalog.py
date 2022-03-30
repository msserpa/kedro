import shutil

import pytest
import yaml
from click.testing import CliRunner

from kedro.extras.datasets.pandas import CSVDataSet
from kedro.io import DataCatalog, MemoryDataSet
from kedro.pipeline import Pipeline, node


@pytest.fixture
def fake_load_context(mocker):
    context = mocker.MagicMock()
    return mocker.patch(
        "kedro.framework.session.KedroSession.load_context", return_value=context
    )


@pytest.fixture(autouse=True)
def mocked_logging(mocker):
    # Disable logging.config.dictConfig in KedroSession._setup_logging as
    # it changes logging.config and affects other unit tests
    return mocker.patch("logging.config.dictConfig")


PIPELINE_NAME = "pipeline"


@pytest.fixture
def mock_pipelines(mocker):
    dummy_pipelines = {PIPELINE_NAME: Pipeline([]), "second": Pipeline([])}
    return mocker.patch("kedro.framework.cli.catalog.pipelines", dummy_pipelines)


@pytest.mark.usefixtures(
    "chdir_to_dummy_project", "fake_load_context", "mock_pipelines"
)
class TestCatalogListCommand:
    def test_list_all_pipelines(self, fake_project_cli, fake_metadata, mocker):
        yaml_dump_mock = mocker.patch("yaml.dump", return_value="Result YAML")

        result = CliRunner().invoke(
            fake_project_cli, ["catalog", "list"], obj=fake_metadata
        )

        assert not result.exit_code
        expected_dict = {
            "DataSets in 'pipeline' pipeline": {},
            "DataSets in 'second' pipeline": {},
        }
        yaml_dump_mock.assert_called_once_with(expected_dict)

    def test_list_specific_pipelines(self, fake_project_cli, fake_metadata, mocker):
        yaml_dump_mock = mocker.patch("yaml.dump", return_value="Result YAML")

        result = CliRunner().invoke(
            fake_project_cli,
            ["catalog", "list", "--pipeline", PIPELINE_NAME],
            obj=fake_metadata,
        )

        assert not result.exit_code
        expected_dict = {f"DataSets in '{PIPELINE_NAME}' pipeline": {}}
        yaml_dump_mock.assert_called_once_with(expected_dict)

    def test_not_found_pipeline(self, fake_project_cli, fake_metadata):
        result = CliRunner().invoke(
            fake_project_cli,
            ["catalog", "list", "--pipeline", "fake"],
            obj=fake_metadata,
        )

        assert result.exit_code
        expected_output = (
            "Error: `fake` pipeline not found! Existing pipelines: pipeline, second"
        )
        assert expected_output in result.output

    def test_no_param_datasets_in_respose(
        self, fake_project_cli, fake_metadata, fake_load_context, mocker, mock_pipelines
    ):
        yaml_dump_mock = mocker.patch("yaml.dump", return_value="Result YAML")
        mocked_context = fake_load_context.return_value
        catalog_data_sets = {
            "iris_data": CSVDataSet("test.csv"),
            "intermediate": MemoryDataSet(),
            "parameters": MemoryDataSet(),
            "params:data_ratio": MemoryDataSet(),
            "not_used": CSVDataSet("test2.csv"),
        }

        mocked_context.catalog = DataCatalog(data_sets=catalog_data_sets)
        mocker.patch.object(
            mock_pipelines[PIPELINE_NAME],
            "data_sets",
            return_value=catalog_data_sets.keys() - {"not_used"},
        )

        result = CliRunner().invoke(
            fake_project_cli,
            ["catalog", "list"],
            obj=fake_metadata,
        )

        assert not result.exit_code
        # 'parameters' and 'params:data_ratio' should not appear in the response
        expected_dict = {
            f"DataSets in '{PIPELINE_NAME}' pipeline": {
                "Datasets mentioned in pipeline": {
                    "CSVDataSet": ["iris_data"],
                    "MemoryDataSet": ["intermediate"],
                },
                "Datasets not mentioned in pipeline": {"CSVDataSet": ["not_used"]},
            }
        }
        key = f"DataSets in '{PIPELINE_NAME}' pipeline"
        assert yaml_dump_mock.call_count == 1
        assert yaml_dump_mock.call_args[0][0][key] == expected_dict[key]

    def test_default_dataset(
        self, fake_project_cli, fake_metadata, fake_load_context, mocker, mock_pipelines
    ):
        """Test that datasets that are found in `Pipeline.data_sets()`,
        but not in the catalog, are outputted under the key "DefaultDataset".
        """
        yaml_dump_mock = mocker.patch("yaml.dump", return_value="Result YAML")
        mocked_context = fake_load_context.return_value
        catalog_data_sets = {"some_dataset": CSVDataSet("test.csv")}
        mocked_context.catalog = DataCatalog(data_sets=catalog_data_sets)
        mocker.patch.object(
            mock_pipelines[PIPELINE_NAME],
            "data_sets",
            return_value=catalog_data_sets.keys() | {"intermediate"},
        )

        result = CliRunner().invoke(
            fake_project_cli,
            ["catalog", "list"],
            obj=fake_metadata,
        )

        assert not result.exit_code
        expected_dict = {
            f"DataSets in '{PIPELINE_NAME}' pipeline": {
                "Datasets mentioned in pipeline": {
                    "CSVDataSet": ["some_dataset"],
                    "DefaultDataSet": ["intermediate"],
                }
            }
        }
        key = f"DataSets in '{PIPELINE_NAME}' pipeline"
        assert yaml_dump_mock.call_count == 1
        assert yaml_dump_mock.call_args[0][0][key] == expected_dict[key]


def identity(data):
    return data  # pragma: no cover


@pytest.mark.usefixtures("chdir_to_dummy_project", "patch_log")
class TestCatalogCreateCommand:
    PIPELINE_NAME = "de"

    @staticmethod
    @pytest.fixture(params=["base"])
    def catalog_path(request, fake_repo_path):
        catalog_path = fake_repo_path / "conf" / request.param / "catalog"

        yield catalog_path

        shutil.rmtree(catalog_path, ignore_errors=True)

    def test_pipeline_argument_is_required(self, fake_project_cli):
        result = CliRunner().invoke(fake_project_cli, ["catalog", "create"])
        assert result.exit_code
        expected_output = "Error: Missing option '--pipeline' / '-p'."
        assert expected_output in result.output

    @pytest.mark.usefixtures("fake_load_context")
    def test_not_found_pipeline(self, fake_project_cli, fake_metadata, mock_pipelines):
        result = CliRunner().invoke(
            fake_project_cli,
            ["catalog", "create", "--pipeline", "fake"],
            obj=fake_metadata,
        )

        assert result.exit_code

        existing_pipelines = ", ".join(sorted(mock_pipelines.keys()))
        expected_output = (
            f"Error: `fake` pipeline not found! Existing "
            f"pipelines: {existing_pipelines}\n"
        )
        assert expected_output in result.output

    def test_catalog_is_created_in_base_by_default(
        self, fake_project_cli, fake_metadata, fake_repo_path, catalog_path
    ):
        main_catalog_path = fake_repo_path / "conf" / "base" / "catalog.yml"
        main_catalog_config = yaml.safe_load(main_catalog_path.read_text())
        assert "example_iris_data" in main_catalog_config

        data_catalog_file = catalog_path / f"{self.PIPELINE_NAME}.yml"

        result = CliRunner().invoke(
            fake_project_cli,
            ["catalog", "create", "--pipeline", self.PIPELINE_NAME],
            obj=fake_metadata,
        )

        assert not result.exit_code
        assert data_catalog_file.is_file()

        expected_catalog_config = {
            "example_test_x": {"type": "MemoryDataSet"},
            "example_test_y": {"type": "MemoryDataSet"},
            "example_train_x": {"type": "MemoryDataSet"},
            "example_train_y": {"type": "MemoryDataSet"},
        }
        catalog_config = yaml.safe_load(data_catalog_file.read_text())
        assert catalog_config == expected_catalog_config

    @pytest.mark.parametrize("catalog_path", ["local"], indirect=True)
    def test_catalog_is_created_in_correct_env(
        self, fake_project_cli, fake_metadata, catalog_path
    ):
        data_catalog_file = catalog_path / f"{self.PIPELINE_NAME}.yml"

        env = catalog_path.parent.name
        result = CliRunner().invoke(
            fake_project_cli,
            ["catalog", "create", "--pipeline", self.PIPELINE_NAME, "--env", env],
            obj=fake_metadata,
        )

        assert not result.exit_code
        assert data_catalog_file.is_file()

    def test_no_missing_datasets(
        self,
        fake_project_cli,
        fake_metadata,
        fake_load_context,
        fake_repo_path,
        mock_pipelines,
    ):
        mocked_context = fake_load_context.return_value

        catalog_data_sets = {
            "input_data": CSVDataSet("test.csv"),
            "output_data": CSVDataSet("test2.csv"),
        }
        mocked_context.catalog = DataCatalog(data_sets=catalog_data_sets)
        mocked_context.project_path = fake_repo_path
        mock_pipelines[self.PIPELINE_NAME] = Pipeline(
            [node(identity, "input_data", "output_data")]
        )

        data_catalog_file = (
            fake_repo_path / "conf" / "base" / "catalog" / f"{self.PIPELINE_NAME}.yml"
        )

        result = CliRunner().invoke(
            fake_project_cli,
            ["catalog", "create", "--pipeline", self.PIPELINE_NAME],
            obj=fake_metadata,
        )

        assert not result.exit_code
        assert not data_catalog_file.exists()

    @pytest.mark.usefixtures("fake_repo_path")
    def test_missing_datasets_appended(
        self, fake_project_cli, fake_metadata, catalog_path
    ):
        data_catalog_file = catalog_path / f"{self.PIPELINE_NAME}.yml"
        assert not catalog_path.exists()
        catalog_path.mkdir()

        catalog_config = {
            "example_test_x": {"type": "pandas.CSVDataSet", "filepath": "test.csv"}
        }
        with data_catalog_file.open(mode="w") as catalog_file:
            yaml.safe_dump(catalog_config, catalog_file, default_flow_style=False)

        result = CliRunner().invoke(
            fake_project_cli,
            ["catalog", "create", "--pipeline", self.PIPELINE_NAME],
            obj=fake_metadata,
        )

        assert not result.exit_code

        expected_catalog_config = {
            "example_test_x": catalog_config["example_test_x"],
            "example_test_y": {"type": "MemoryDataSet"},
            "example_train_x": {"type": "MemoryDataSet"},
            "example_train_y": {"type": "MemoryDataSet"},
        }
        catalog_config = yaml.safe_load(data_catalog_file.read_text())
        assert catalog_config == expected_catalog_config

    def test_bad_env(self, fake_project_cli, fake_metadata):
        """Test error when provided conf environment does not exist"""
        env = "no_such_env"
        cmd = ["catalog", "list", "-e", env, "--pipeline", PIPELINE_NAME]

        result = CliRunner().invoke(fake_project_cli, cmd, obj=fake_metadata)

        assert result.exit_code
        assert "Unable to instantiate Kedro session" in result.output
