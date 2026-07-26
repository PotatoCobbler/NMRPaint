# NMRpaint

NMRpaint is an interactive tool for designing NMR pulse sequences and exporting Bruker-style pulse programs.

The project is maintained as a Python package and deployed as a browser application with Voici and Pyodide. The local and web versions use the same source code.

> **License status:** This repository is publicly accessible, but NMRpaint is not currently open-source software. See [`LICENSE`](LICENSE).

---

## Project Structure

```text
nmrpaint/
├── .github/
│   └── workflows/
│       └── deploy-voici.yml
├── apps/
│   └── NMRpaint_local.ipynb
├── scripts/
├── src/
│   └── nmrpaint/
│       ├── __init__.py
│       ├── app.py
│       ├── exporters.py
│       ├── resource_manager.py
│       └── resources/
│           ├── elements/
│           ├── defs/
│           └── cpdlib/
├── tests/
├── voici/
│   ├── content/
│   │   └── NMRpaint.ipynb
│   ├── jupyter-lite.json
│   ├── jupyter_lite_config.json
│   └── pypi/
├── AUTHORS.md
├── CITATION.cff
├── LICENSE
├── NOTICE
├── handover.md
├── pyproject.toml
└── README.md
```

### Source of truth

The maintained application source is:

```text
src/nmrpaint/app.py
```

Supporting modules:

| Path | Responsibility |
|---|---|
| `src/nmrpaint/app.py` | GUI, canvas, callbacks, application state, and pulse-program generation |
| `src/nmrpaint/exporters.py` | Local file export and browser downloads |
| `src/nmrpaint/resource_manager.py` | Packaged resource access |
| `src/nmrpaint/resources/` | Elements, definitions, and CPD resources |
| `tests/` | Automated tests |
| `apps/NMRpaint_local.ipynb` | Local development launcher |
| `voici/content/NMRpaint.ipynb` | Browser application launcher |
| `.github/workflows/deploy-voici.yml` | Automated test, build, and deployment workflow |

Do not place application logic in the launcher notebooks. Do not continue development in files under `legacy/`.

---

## Development Setup

Python 3.11 is used for the validated development environment.

Create the main environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install build pytest
```

Run the tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Open the local application through:

```text
apps/NMRpaint_local.ipynb
```

and select the `.venv` kernel.

---

## Updating the Application

For a normal functional change:

1. Edit the relevant file under `src/nmrpaint/`.
2. Add or update tests under `tests/`.
3. Run the test suite.
4. Test the local launcher.
5. Build and test Voici when browser behavior may be affected.
6. Commit source changes only.
7. Confirm that GitHub Actions succeeds after merging.

### Resource updates

Edit resources only under:

```text
src/nmrpaint/resources/
```

Do not create duplicate root-level copies of `elements`, `defs`, or `cpdlib`.

### Version updates

Keep the version consistent in:

```text
pyproject.toml
src/nmrpaint/__init__.py
voici/content/NMRpaint.ipynb
CITATION.cff
```

The version requested by the browser launcher must match the wheel built by the deployment workflow.

---

## Building the Package

From the repository root:

```powershell
Remove-Item .\build -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .\dist -Recurse -Force -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m build --wheel
```

The wheel is generated under:

```text
dist/
```

Generated build output must not be committed.

---

## Building Voici Locally

Voici uses a separate environment because its JupyterLite and Pyodide dependencies are version-sensitive.

Create the environment:

```powershell
python -m venv .venv-voici
.\.venv-voici\Scripts\python.exe -m pip install --upgrade pip
```

Install the validated stack:

```powershell
.\.venv-voici\Scripts\python.exe -m pip install `
    -e . `
    build `
    "voici-core==0.10.0" `
    "jupyterlite-core[lab,serve]==0.7.0" `
    "jupyterlite-pyodide-kernel==0.7.0" `
    "jupyterlab==4.5.0" `
    "notebook==7.5.0" `
    jupyter-server `
    jupyterlab-server
```

Build the wheel and copy it into the Voici package index:

```powershell
.\.venv\Scripts\python.exe -m build --wheel
New-Item .\voici\pypi -ItemType Directory -Force | Out-Null
Remove-Item .\voici\pypi\nmrpaint-*.whl -Force -ErrorAction SilentlyContinue
Copy-Item .\dist\nmrpaint-*.whl .\voici\pypi\
```

Build the site:

```powershell
cd .\voici
$env:PYTHONUTF8 = "1"

Remove-Item .\_output -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .\.jupyterlite.doit.db -Force -ErrorAction SilentlyContinue

..\.venv-voici\Scripts\voici.exe build `
    --contents .\content\NMRpaint.ipynb `
    --output-dir .\_output
```

Serve locally:

```powershell
..\.venv-voici\Scripts\python.exe `
    -m http.server 8011 `
    --directory .\_output
```

Open:

```text
http://127.0.0.1:8011/voici/render/NMRpaint.html
```

Do not upgrade the browser dependency stack independently without testing the complete build.

---

## Deployment

GitHub Pages deployment is controlled by:

```text
.github/workflows/deploy-voici.yml
```

A push or merge to `main` runs:

```text
tests
→ wheel build
→ Voici build
→ GitHub Pages deployment
```

Only the Voici deployment workflow should publish GitHub Pages.

After deployment, verify:

- the page loads without the Notebook interface;
- the Pyodide kernel starts;
- the canvas and controls are interactive;
- pulse-program generation works;
- browser download works; and
- the browser console contains no fatal kernel or frontend errors.

---

## Contribution Workflow

Use one branch per logical change and submit a pull request against `main`.

Before merging:

- review the changed files;
- confirm required checks pass;
- avoid unrelated formatting changes;
- confirm no generated files are included.

Generated or local-only paths include:

```text
.venv/
.venv-voici/
build/
dist/
output/
voici/_output/
voici/pypi/*.whl
.pytest_cache/
```

For browser-only GitHub editing and repository handover, see [`handover.md`](handover.md).

---

## Troubleshooting

### Voici remains on `Running`

Open the browser developer console. Common causes are:

- no Pyodide kernel available;
- incompatible JupyterLite frontend modules;
- a package-version mismatch between the wheel and launcher notebook.

### Windows build fails with `cp950`

Run:

```powershell
$env:PYTHONUTF8 = "1"
```

before building Voici.

### Source changes do not appear online

Confirm that:

- the change was merged into `main`;
- the deployment workflow completed;
- a new wheel was built;
- the launcher requests the same package version; and
- the browser is not serving cached content.

---

## Documentation

- [`use_manual.md`](use_manual.md) — end-user instructions
- [`handover.md`](handover.md) — repository transfer and GitHub onboarding
- [`AUTHORS.md`](AUTHORS.md) — authors and contributors
- [`CITATION.cff`](CITATION.cff) — software citation metadata
- [`LICENSE`](LICENSE) — current interim licensing notice

---

## License

NMRpaint is currently distributed under an interim all-rights-reserved licensing notice.

Public availability of this repository does not grant permission to use, copy, modify, redistribute, sublicense, or commercialize the software. Scientific, educational, institutional, and commercial use currently requires prior written permission from the copyright holder.

See [`LICENSE`](LICENSE) for the controlling terms.
