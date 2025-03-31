# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'Opti-VGI'
copyright = '2025, Nithin Manne, Jason Harper'
author = 'Nithin Manne, Jason Harper'
release = '1.0.0'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

sys.path.insert(0, os.path.abspath('../..'))

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.intersphinx',
    'sphinx.ext.githubpages',
    'sphinx_autodoc_typehints',
]

templates_path = ['_templates']
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'furo'
html_static_path = ['_static']


# -- Other Configuration Options -----------------------------------------------

always_document_param_types = True
typehints_fully_qualified = False
typehints_document_rtype = True
typehints_use_rtype = False

# Intersphinx configuration
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
}
