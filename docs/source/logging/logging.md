# Logging

Kedro uses, and facilitates, the use of Python’s `logging` library by providing a default logging configuration. This can be found in `conf/base/logging.yml` in every project generated using Kedro’s CLI `kedro new` command.

## Configure logging

You can customise project logging in `conf/<env>/logging.yml` using [standard Kedro mechanisms for handling configuration](../kedro_project_setup/configuration.md). The configuration should comply with the guidelines from the `logging` library. Find more about it in [the documentation for `logging` module](https://docs.python.org/3/library/logging.html).

## Use logging

After reading and applying project logging configuration, `kedro` will start emitting the logs automatically. To log your own code, you are advised to do the following:

```python
import logging

log = logging.getLogger(__name__)
log.warning("Issue warning")
log.info("Send information")
```

```eval_rst
.. note:: The name of a logger corresponds to a key in the ``loggers``  section in ``logging.yml`` (e.g. ``kedro.io``). See `Python's logging documentation <https://docs.python.org/3/library/logging.html#logger-objects>`_ for more information.
```

## Logging for `anyconfig`

By default, [anyconfig](https://github.com/ssato/python-anyconfig) library that is used by `kedro` to read configuration files emits a log message with `INFO` level on every read. To reduce the amount of logs being sent for CLI calls, default project logging configuration in `conf/base/logging.yml` sets the level for `anyconfig` logger to `WARNING`.

If you would like `INFO` level messages to propagate, you can update `anyconfig` logger level in `conf/base/logging.yml` as follows:

```yaml
loggers:
    anyconfig:
        level: INFO  # change
        handlers: [console, info_file_handler, error_file_handler]
        propagate: no
```
