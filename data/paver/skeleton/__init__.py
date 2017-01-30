import os
import re
from datetime import datetime

import six
import jinja2
import sphinx.quickstart

env = jinja2.Environment()

__here__ = os.path.dirname(os.path.abspath(__file__))


def render(to_render, settings):
    if isinstance(to_render, six.string_types):
        return env.from_string(to_render).render(settings)
    else:
        with open(os.path.join(__here__, *to_render)) as template_file:
            return env.from_string(template_file.read()).render(settings)


def create_plugin(plugins_dir, plugin, **settings):
    assert ' ' not in plugin, "plugins probably shouldn't have spaces; but either way we aren't specifically handling spaces"
    module = plugin.replace('-', '_')
    plugin = plugin.replace('_', '-')
    settings.update({'plugin': plugin, 'module': module, 'generated_date': datetime.utcnow()})

    package_dir = os.path.join(plugins_dir, plugin)
    assert not os.path.exists(package_dir), '{} plugin already exists at {}'.format(plugin, package_dir)
    os.makedirs(os.path.join(package_dir, module, 'tests'))
    for fname, template in TEMPLATES.items():
        fname = render(fname, settings)
        if fname:
            fpath = os.path.join(package_dir, fname)
            try:
                os.makedirs(os.path.dirname(fpath))
            except (OSError, IOError) as e:
                pass

            with open(fpath, 'w') as f:
                # our templates often have a lot of {% if %} clauses which lead to a lot of blank lines,
                # so we collapse those such that we never have more than 1 blank line in a row
                f.write(re.sub(r'\n{3,}', '\n\n', render(template, settings).strip() + '\n'))

    if settings.get('sphinx', True):
        sphinx_settings = dict(
            path=os.path.join(package_dir, 'docs'),
            sep=False,
            dot='_',
            project=plugin,
            author='{} Team'.format(plugin),
            release='0.1.0',
            version='0.1.0',
            suffix='.rst',
            master='index',
            epub=False,
            ext_autodoc=False,
            ext_doctest=False,
            ext_intersphinx=False,
            ext_todo=False,
            ext_coverage=False,
            ext_pngmath=False,
            ext_mathjax=False,
            ext_ifconfig=False,
            ext_viewcode=False,
            makefile=True,
            batchfile=False
        )
        sphinx.quickstart.generate(sphinx_settings)

TEMPLATES = {
    '{{ module }}/_version.py': ('templates', '_version.py.template'),
    'requirements.txt': ('templates', 'requirements.txt.template'),
    'setup.cfg': ('templates', 'setup.cfg.template'),
    'setup.py': ('templates', 'setup.py.template'),
    'conftest.py': ('templates', 'conftest.py.template'),
    '{{ module }}/__init__.py': ('templates', '__init__.py.template'),
    '{{ module }}/tests/__init__.py': ('templates', 'tests-__init__.py.template'),
    '{% if sqlalchemy %}{{ module }}/sa.py{% endif %}': ('templates', 'sa.py.template'),
    '{% if service %}{{ module }}/service.py{% endif %}': ('templates', 'service.py.template'),
    '{{ module }}/configspec.ini': ('templates', 'configspec.ini.template'),
    'development-defaults.ini': ('templates', 'development-defaults.ini'),
    '{% if webapp %}{{ module }}/templates/index.html{% endif %}': ('templates', 'index.html.template'),
    'MANIFEST.in': ('templates', 'MANIFEST.in.template'),
    '.gitignore': ('templates', '.gitignore.template'),
    'fabfile.py': ('templates', 'fabfile.py.template'),
    'package-support/{{ plugin }}.cfg': ('templates', 'plugin_name.cfg.template'),
    '{% if cli %}{{ module }}/cli.py{% endif %}': ('templates', 'cli.py.template'),
}
