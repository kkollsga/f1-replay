# Sphinx configuration for f1-replay documentation

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

project = "f1-replay"
copyright = "2024, F1 Replay Development"
author = "F1 Replay Development"

# Extensions
extensions = [
    "myst_parser",
    "sphinxcontrib.mermaid",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
]

# MyST-Parser settings (enables markdown docs)
myst_enable_extensions = [
    "colon_fence",
    "fieldlist",
    "deflist",
]
myst_heading_anchors = 3

# Napoleon settings (Google-style docstrings)
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True

# Autodoc settings
autodoc_member_order = "bysource"
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}

# Mock heavy imports so ReadTheDocs doesn't need them
autodoc_mock_imports = [
    "fastf1",
    "pandas",
    "numpy",
    "polars",
    "scipy",
    "flask",
    "orjson",
    "flask_cors",
    "matplotlib",
]

# Source settings
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# Theme
html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 3,
    "collapse_navigation": False,
}

# Root document
root_doc = "index"

# Exclude patterns
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
