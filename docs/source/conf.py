# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath("../.."))
conf_dir = Path(__file__)
# from python_test import __version__


# -- Project information -----------------------------------------------------

project = "python_test"
copyright = "2020, Cielquan"
author = "Cielquan"

# The full version, including alpha/beta/rc tags
version = __version__ = "0"
release = version
# release_date = ""
#
# rst_epilog = """
# .. |release_date| replace:: {release_date}
# .. |coverage-equals-release| replace:: coverage=={release}
# .. |doc-url| replace:: https://coverage.readthedocs.io/en/coverage-{release}
# .. |br| raw:: html
#   <br/>
# """.format(release=release, release_date=release_date)


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.autodoc",
]

master_doc = "index"

pygments_style = 'sphinx'

# intersphinx_mapping = {
#     'python': ('https://docs.python.org/3', None),
#     }

# Add any paths that contain templates here, relative to this directory.
templates_path = []
if Path(conf_dir, "_templates").exists():
    templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
# Use RTD Theme if installed
try:
    import sphinx_rtd_theme
except ImportError:
    html_theme = "alabaster"
else:
    extensions.append("sphinx_rtd_theme")
    html_theme = "sphinx_rtd_theme"

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = []
if Path(conf_dir, "_static").exists():
    html_static_path = ["_static"]

html_show_sourcelink = True
