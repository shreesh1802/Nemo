# Nemo

An always-on AI companion that lives on your screen as a small robot. Hover over
it or speak, and it acts on your behalf: copy and paste chores, research, repo
security scans, and more. Built on NVIDIA Nemotron models served by Nebius
Token Factory.

Status: early scaffold. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Run the agent service

```bash
cd services/agent
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy ..\..\.env.example .env      # then fill in NEBIUS_API_KEY
python scripts/list_models.py     # copy the Nemotron IDs into .env
uvicorn nemo_agent.server:app --reload
pytest
```

## License

MIT
