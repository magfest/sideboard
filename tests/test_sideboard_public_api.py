from __future__ import unicode_literals

import pytest

import sideboard.lib.sa


@pytest.fixture
def public_modules():
    return [sideboard.lib, sideboard.lib.sa]


@pytest.fixture
def version_contract():
    return {
        '0.1': {
            sideboard.lib: [
                'log', 'listify', 'services', 'ConfigurationError', 'parse_config',
                'threadlocal', 'subscribes', 'notifies', 'notify', 'stopped', 'on_startup',
                'on_shutdown', 'DaemonTask', 'ajax', 'renders_template', 'render_with_templates',
                'WebSocket', 'Model', 'Subscription'
            ],
            sideboard.lib.sa: [
                'UUID', 'JSON', 'UTCDateTime', 'declarative_base', 'SessionManager',
                'CrudException', 'crudable', 'crud_validation', 'text_length_validation',
                'regex_validation'
            ]
        }
    }


class TestBackwardsCompatibility(object):

    def test_current_version_represented_and_matches_expectation(self, version_contract):
        major_minor = ".".join(sideboard.__version__.split(".")[:2])
        assert major_minor in version_contract, ("Current sideboard version ({}) is not in "
                                                 "version_contract".format(major_minor))


    def test_nothing_missing_from_all(self, public_modules):
        failures = []
        for module in public_modules:
            for name, x in module.__dict__.items():
                if (name not in module.__all__ and not name.startswith("_") and
                    getattr(x, '__module__', None) == module.__name__):
                    failures.append('{} defines {} which is not present in __all__'.format(
                        module.__name__, name))

        assert not failures, '\n'.join(failures)

    def test_can_import_everything_in_all(self, public_modules):
        failures = []
        for module in public_modules:
            for name in module.__all__:
                if not hasattr(module, name):
                    failures.append("{} defines {} in __all__ but it's not present in the "
                                    "module namespace".format(module.__name__, name))
        assert not failures, '\n'.join(failures)

    def test_all_previous_versions(self, version_contract):
        failures = []
        for version, modules in version_contract.items():
            for module, dunder_all in modules.items():
                for name in dunder_all:
                    if not hasattr(module, name) and name != 'UTCDateTime':  # TODO: test for this
                        failures.append("{} doesn't define {} which was included in "
                                        "version {}".format(module.__name__, name, version))
        assert not failures, '\n'.join(failures)
