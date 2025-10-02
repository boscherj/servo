# servo
[![Docs](https://github.com/boscherj/servo/actions/workflows/docs.yml/badge.svg)](https://github.com/boscherj/servo/actions/workflows/docs.yml)
📘 [Consulter la documentation](https://boscherj.github.io/servo/)

Environnement Python avec **uv**, layout `src/`, tests **pytest**, lint/format **ruff** + **black**, hooks **pre-commit**, et configuration **VS Code**.

## Installation rapide

```bash
uv venv --python 3
source .venv/bin/activate
uv pip install -r requirements.txt
pre-commit install
