import configparser
import json
import re
import textwrap
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Any, Dict

import pandas as pd
import pytest
import toml
import yaml
from pandas.util.testing import assert_frame_equal

from kedro import __version__ as kedro_version
from kedro.config import ConfigLoader, MissingConfigException
from kedro.framework.context import KedroContext
from kedro.framework.context.context import (
    _convert_paths_to_absolute_posix,
    _is_relative_path,
    _update_nested_dict,
    _validate_layers_for_transcoding,
)
from kedro.framework.hooks import _create_hook_manager
from kedro.framework.project import (
    ValidationError,
    _ProjectSettings,
    configure_project,
    pipelines,
)

MOCK_PACKAGE_NAME = "mock_package_name"


class BadCatalog:  # pylint: disable=too-few-public-methods
    """
    Catalog class that doesn't subclass `DataCatalog`, for testing only.
    """


def _write_yaml(filepath: Path, config: Dict):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    yaml_str = yaml.dump(config)
    filepath.write_text(yaml_str)


def _write_toml(filepath: Path, config: Dict):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    toml_str = toml.dumps(config)
    filepath.write_text(toml_str)


def _write_json(filepath: Path, config: Dict):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    json_str = json.dumps(config)
    filepath.write_text(json_str)


def _write_dummy_ini(filepath: Path):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    config = configparser.ConfigParser()
    config["prod"] = {"url": "postgresql://user:pass@url_prod/db"}
    config["staging"] = {"url": "postgresql://user:pass@url_staging/db"}
    with filepath.open("wt") as configfile:  # save
        config.write(configfile)


@pytest.fixture
def base_config(tmp_path):
    cars_filepath = (tmp_path / "cars.csv").as_posix()
    trains_filepath = (tmp_path / "trains.csv").as_posix()

    return {
        "trains": {"type": "pandas.CSVDataSet", "filepath": trains_filepath},
        "cars": {
            "type": "pandas.CSVDataSet",
            "filepath": cars_filepath,
            "save_args": {"index": True},
        },
    }


@pytest.fixture
def local_config(tmp_path):
    cars_filepath = (tmp_path / "cars.csv").as_posix()
    boats_filepath = (tmp_path / "boats.csv").as_posix()
    # use one dataset with a relative filepath
    horses_filepath = "horses.csv"
    return {
        "cars": {
            "type": "pandas.CSVDataSet",
            "filepath": cars_filepath,
            "save_args": {"index": False},
            "versioned": True,
        },
        "boats": {
            "type": "pandas.CSVDataSet",
            "filepath": boats_filepath,
            "versioned": True,
            "layer": "raw",
        },
        "horses": {
            "type": "pandas.CSVDataSet",
            "filepath": horses_filepath,
            "versioned": True,
        },
    }


@pytest.fixture
def local_logging_config() -> Dict[str, Any]:
    return {
        "version": 1,
        "formatters": {
            "simple": {"format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"}
        },
        "root": {"level": "INFO", "handlers": ["console"]},
        "loggers": {"kedro": {"level": "INFO", "handlers": ["console"]}},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": "INFO",
                "formatter": "simple",
                "stream": "ext://sys.stdout",
            }
        },
    }


@pytest.fixture(params=[None])
def env(request):
    return request.param


@pytest.fixture
def prepare_project_dir(tmp_path, base_config, local_config, local_logging_config, env):
    env = "local" if env is None else env
    proj_catalog = tmp_path / "conf" / "base" / "catalog.yml"
    env_catalog = tmp_path / "conf" / str(env) / "catalog.yml"
    logging = tmp_path / "conf" / "local" / "logging.yml"
    env_credentials = tmp_path / "conf" / str(env) / "credentials.yml"
    parameters = tmp_path / "conf" / "base" / "parameters.json"
    db_config_path = tmp_path / "conf" / "base" / "db.ini"
    project_parameters = {"param1": 1, "param2": 2, "param3": {"param4": 3}}
    _write_yaml(proj_catalog, base_config)
    _write_yaml(env_catalog, local_config)
    _write_yaml(logging, local_logging_config)
    _write_yaml(env_credentials, local_config)
    _write_json(parameters, project_parameters)
    _write_dummy_ini(db_config_path)

    _write_toml(tmp_path / "pyproject.toml", pyproject_toml_payload)


@pytest.fixture
def mock_settings_file_bad_data_catalog_class(tmpdir):
    mock_settings_file = tmpdir.join("mock_settings_file.py")
    mock_settings_file.write(
        textwrap.dedent(
            f"""
            from {__name__} import BadCatalog
            DATA_CATALOG_CLASS = BadCatalog
            """
        )
    )
    return mock_settings_file


@pytest.fixture(autouse=True)
def mock_settings(mocker):
    mocked_settings = _ProjectSettings()
    mocker.patch("kedro.framework.session.session.settings", mocked_settings)
    return mocker.patch("kedro.framework.project.settings", mocked_settings)


@pytest.fixture
def dummy_dataframe():
    return pd.DataFrame({"col1": [1, 2], "col2": [4, 5], "col3": [5, 6]})


expected_message_middle = (
    "There are 2 nodes that have not run.\n"
    "You can resume the pipeline run by adding the following "
    "argument to your previous command:\n"
    '  --from-nodes "nodes3"'
)


expected_message_head = (
    "There are 4 nodes that have not run.\n"
    "You can resume the pipeline run by adding the following "
    "argument to your previous command:\n"
)

pyproject_toml_payload = {
    "tool": {
        "kedro": {
            "project_name": "mock_project_name",
            "project_version": kedro_version,
            "package_name": MOCK_PACKAGE_NAME,
        }
    }
}


@pytest.fixture(params=[None])
def extra_params(request):
    return request.param


@pytest.fixture(autouse=True)
def mocked_logging(mocker):
    # Disable logging.config.dictConfig in KedroSession._setup_logging as
    # it changes logging.config and affects other unit tests
    return mocker.patch("logging.config.dictConfig")


@pytest.fixture
def dummy_context(
    tmp_path, prepare_project_dir, env, extra_params
):  # pylint: disable=unused-argument
    configure_project(MOCK_PACKAGE_NAME)
    config_loader = ConfigLoader(str(tmp_path / "conf"), env=env)
    context = KedroContext(
        MOCK_PACKAGE_NAME,
        str(tmp_path),
        config_loader=config_loader,
        hook_manager=_create_hook_manager(),
        env=env,
        extra_params=extra_params,
    )

    yield context
    pipelines.configure()


class TestKedroContext:
    def test_attributes(self, tmp_path, dummy_context):
        assert isinstance(dummy_context.project_path, Path)
        assert dummy_context.project_path == tmp_path.resolve()

    def test_get_catalog_always_using_absolute_path(self, dummy_context):
        config_loader = dummy_context._config_loader
        conf_catalog = config_loader.get("catalog*")

        # even though the raw configuration uses relative path
        assert conf_catalog["horses"]["filepath"] == "horses.csv"

        # the catalog and its dataset should be loaded using absolute path
        # based on the project path
        catalog = dummy_context._get_catalog()
        ds_path = catalog._data_sets["horses"]._filepath
        assert PurePath(ds_path.as_posix()).is_absolute()
        assert (
            ds_path.as_posix()
            == (dummy_context._project_path / "horses.csv").as_posix()
        )

    def test_get_catalog_validates_layers(self, dummy_context, mocker):
        mock_validate = mocker.patch(
            "kedro.framework.context.context._validate_layers_for_transcoding"
        )
        catalog = dummy_context.catalog

        mock_validate.assert_called_once_with(catalog)

    def test_catalog(self, dummy_context, dummy_dataframe):
        assert dummy_context.catalog.layers == {"raw": {"boats"}}
        dummy_context.catalog.save("cars", dummy_dataframe)
        reloaded_df = dummy_context.catalog.load("cars")
        assert_frame_equal(reloaded_df, dummy_dataframe)

    def test_wrong_catalog_type(self, mock_settings_file_bad_data_catalog_class):
        pattern = (
            "Invalid value `tests.framework.context.test_context.BadCatalog` received "
            "for setting `DATA_CATALOG_CLASS`. "
            "It must be a subclass of `kedro.io.data_catalog.DataCatalog`."
        )
        mock_settings = _ProjectSettings(
            settings_file=str(mock_settings_file_bad_data_catalog_class)
        )
        with pytest.raises(ValidationError, match=re.escape(pattern)):
            assert mock_settings.DATA_CATALOG_CLASS

    @pytest.mark.parametrize(
        "extra_params",
        [None, {}, {"foo": "bar", "baz": [1, 2], "qux": None}],
        indirect=True,
    )
    def test_params(self, dummy_context, extra_params):
        extra_params = extra_params or {}
        expected = {"param1": 1, "param2": 2, "param3": {"param4": 3}, **extra_params}
        assert dummy_context.params == expected

    @pytest.mark.parametrize(
        "param,expected",
        [("params:param3", {"param4": 3}), ("params:param3.param4", 3)],
    )
    def test_nested_params(self, param, expected, dummy_context):
        param = dummy_context.catalog.load(param)
        assert param == expected

    @pytest.mark.parametrize(
        "extra_params",
        [None, {}, {"foo": "bar", "baz": [1, 2], "qux": None}],
        indirect=True,
    )
    def test_params_missing(self, mocker, extra_params, dummy_context):
        mock_config_loader = mocker.patch("kedro.config.ConfigLoader.get")
        mock_config_loader.side_effect = MissingConfigException("nope")
        extra_params = extra_params or {}

        pattern = "Parameters not found in your Kedro project config"
        with pytest.warns(UserWarning, match=pattern):
            actual = dummy_context.params
        assert actual == extra_params

    @pytest.mark.parametrize("env", ["custom_env"], indirect=True)
    def test_custom_env(self, dummy_context, env):
        assert dummy_context.env == env

    def test_missing_parameters(self, tmp_path, dummy_context):
        parameters = tmp_path / "conf" / "base" / "parameters.json"
        parameters.unlink()

        pattern = "Parameters not found in your Kedro project config."
        with pytest.warns(UserWarning, match=re.escape(pattern)):
            _ = dummy_context.catalog

    def test_missing_credentials(self, dummy_context):
        env_credentials = (
            dummy_context.project_path / "conf" / "local" / "credentials.yml"
        )
        env_credentials.unlink()

        pattern = "Credentials not found in your Kedro project config."
        with pytest.warns(UserWarning, match=re.escape(pattern)):
            _ = dummy_context.catalog


@pytest.mark.parametrize(
    "path_string,expected",
    [
        # remote paths shouldn't be relative paths
        ("s3://", False),
        ("gcp://path/to/file.json", False),
        # windows absolute path shouldn't relative paths
        ("C:\\path\\to\\file.json", False),
        ("C:", False),
        ("C:/Windows/", False),
        # posix absolute path shouldn't be relative paths
        ("/tmp/logs/info.log", False),
        ("/usr/share", False),
        # test relative paths
        ("data/01_raw/data.json", True),
        ("logs/info.log", True),
        ("logs\\error.txt", True),
        ("data", True),
    ],
)
def test_is_relative_path(path_string: str, expected: bool):
    assert _is_relative_path(path_string) == expected


def test_convert_paths_raises_error_on_relative_project_path():
    path = Path("relative") / "path"

    pattern = f"project_path must be an absolute path. Received: {path}"
    with pytest.raises(ValueError, match=re.escape(pattern)):
        _convert_paths_to_absolute_posix(project_path=path, conf_dictionary={})


@pytest.mark.parametrize(
    "project_path,input_conf,expected",
    [
        (
            PurePosixPath("/tmp"),
            {"handler": {"filename": "logs/info.log"}},
            {"handler": {"filename": "/tmp/logs/info.log"}},
        ),
        (
            PurePosixPath("/User/kedro"),
            {"my_dataset": {"filepath": "data/01_raw/dataset.json"}},
            {"my_dataset": {"filepath": "/User/kedro/data/01_raw/dataset.json"}},
        ),
        (
            PureWindowsPath("C:\\kedro"),
            {"my_dataset": {"path": "data/01_raw/dataset.json"}},
            {"my_dataset": {"path": "C:/kedro/data/01_raw/dataset.json"}},
        ),
        # test: the function shouldn't modify paths for key not associated with filepath
        (
            PurePosixPath("/User/kedro"),
            {"my_dataset": {"fileurl": "relative/url"}},
            {"my_dataset": {"fileurl": "relative/url"}},
        ),
    ],
)
def test_convert_paths_to_absolute_posix_for_all_known_filepath_keys(
    project_path: Path, input_conf: Dict[str, Any], expected: Dict[str, Any]
):
    assert _convert_paths_to_absolute_posix(project_path, input_conf) == expected


@pytest.mark.parametrize(
    "project_path,input_conf,expected",
    [
        (
            PurePosixPath("/tmp"),
            {"handler": {"filename": "/usr/local/logs/info.log"}},
            {"handler": {"filename": "/usr/local/logs/info.log"}},
        ),
        (
            PurePosixPath("/User/kedro"),
            {"my_dataset": {"filepath": "s3://data/01_raw/dataset.json"}},
            {"my_dataset": {"filepath": "s3://data/01_raw/dataset.json"}},
        ),
    ],
)
def test_convert_paths_to_absolute_posix_not_changing_non_relative_path(
    project_path: Path, input_conf: Dict[str, Any], expected: Dict[str, Any]
):
    assert _convert_paths_to_absolute_posix(project_path, input_conf) == expected


@pytest.mark.parametrize(
    "project_path,input_conf,expected",
    [
        (
            PureWindowsPath("D:\\kedro"),
            {"my_dataset": {"path": r"C:\data\01_raw\dataset.json"}},
            {"my_dataset": {"path": "C:/data/01_raw/dataset.json"}},
        )
    ],
)
def test_convert_paths_to_absolute_posix_converts_full_windows_path_to_posix(
    project_path: Path, input_conf: Dict[str, Any], expected: Dict[str, Any]
):
    assert _convert_paths_to_absolute_posix(project_path, input_conf) == expected


@pytest.mark.parametrize(
    "layers",
    [
        {"raw": {"A"}, "interm": {"B", "C"}},
        {"raw": {"A"}, "interm": {"B@2", "B@1"}},
        {"raw": {"C@1"}, "interm": {"A", "B@1", "B@2", "B@3"}},
    ],
)
def test_validate_layers(layers, mocker):
    mock_catalog = mocker.MagicMock()
    mock_catalog.layers = layers

    _validate_layers_for_transcoding(mock_catalog)  # it shouldn't raise any error


@pytest.mark.parametrize(
    "layers,conflicting_datasets",
    [
        ({"raw": {"A", "B@1"}, "interm": {"B@2"}}, ["B@2"]),
        ({"raw": {"A"}, "interm": {"B@1", "B@2"}, "prm": {"B@3"}}, ["B@3"]),
        (
            {
                "raw": {"A@1"},
                "interm": {"B@1", "B@2"},
                "prm": {"B@3", "B@4"},
                "other": {"A@2"},
            },
            ["A@2", "B@3", "B@4"],
        ),
    ],
)
def test_validate_layers_error(layers, conflicting_datasets, mocker):
    mock_catalog = mocker.MagicMock()
    mock_catalog.layers = layers
    error_str = ", ".join(conflicting_datasets)

    pattern = (
        f"Transcoded datasets should have the same layer. "
        f"Mismatch found for: {error_str}"
    )
    with pytest.raises(ValueError, match=re.escape(pattern)):
        _validate_layers_for_transcoding(mock_catalog)


@pytest.mark.parametrize(
    "old_dict, new_dict, expected",
    [
        (
            {
                "a": 1,
                "b": 2,
                "c": {
                    "d": 3,
                },
            },
            {"c": {"d": 5, "e": 4}},
            {
                "a": 1,
                "b": 2,
                "c": {"d": 5, "e": 4},
            },
        ),
        ({"a": 1}, {"b": 2}, {"a": 1, "b": 2}),
        ({"a": 1, "b": 2}, {"b": 3}, {"a": 1, "b": 3}),
        (
            {"a": {"a.a": 1, "a.b": 2, "a.c": {"a.c.a": 3}}},
            {"a": {"a.c": {"a.c.b": 4}}},
            {"a": {"a.a": 1, "a.b": 2, "a.c": {"a.c.a": 3, "a.c.b": 4}}},
        ),
    ],
)
def test_update_nested_dict(old_dict: Dict, new_dict: Dict, expected: Dict):
    _update_nested_dict(old_dict, new_dict)  # _update_nested_dict change dict in place
    assert old_dict == expected
