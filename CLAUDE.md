# Rules for working on this project

## Strict AI Behavior
- **No Assumptions:** If something wasn't explicitly specified, ask before proceeding. Don't make unilateral design decisions.
- **Answer Only What Is Asked:** Focus entirely on the prompt. Only write code when explicitly asked; otherwise, answer the question directly. Prefer small or no-code solutions.
- **Stay in Scope:** Do not write unit tests unless explicitly requested. Do not discuss Git diffs unless they are the subject of the prompt.

## Data Provenance & Investigative Standards
- **Cite Everything:** Always include the exact sources, URLs, and retrieval timestamps for everything you cite, consult, or scrape.
- **Idempotency & Caching:** When writing scraping or extraction scripts, always implement local caching (e.g., save raw HTML/JSON) to avoid hitting target servers repeatedly during debugging.
- **Rate Limiting:** Always include polite delays (e.g., `time.sleep`) when writing web scrapers.
- **Secure Credentials:** NEVER hardcode API keys, database credentials, or target personal data in scripts. Always use `os.getenv()` or `python-dotenv` with a `.env` file.
- **Immutability of Raw Data:** Treat the data/raw/ directory (or any directory containing source data) as strictly read-only. Never write to, modify, delete, or overwrite original source files. Always write outputs and transformations to data/interim or data/processed/.

## Code Style & Architecture
- Follow PEP 8 style guidelines and modern Python conventions.
- Never use fully-qualified calls like `package.module.function()` when a clean import at the top of the file suffices. 
- DRY the code: Check if existing helper functions in the project's utility modules can be reused before writing new logic.
- Avoid adding arguments to a function that will always take the same value.
- Don't use bare `except:` or `except Exception: pass`. Catch specific exceptions.

## Types, Data Structures & Logging
- Use type hints on all function signatures (parameters and return types).
- Use `dataclasses` or `pydantic` models for structured data instead of loose dictionaries.
- Use `logging` (or `rich`) for messages and errors, not bare `print()` for diagnostics.

## File Handling & Environment
- Use `pathlib.Path` for all file manipulation and path handling. Do not use `os.path` string manipulation.
- Always explicitly specify `encoding="utf-8"` when reading or writing text files.
- When an important package is missing, add it to `pyproject.toml` or via `uv add <package>` / `poetry add <package>` depending on the project's package manager.

## DataFrames (Polars & Pandas)
- Prefix all DataFrame variables with `df_`.
- Prefer Parquet (`.parquet`) over CSV for intermediate data storage. 
- When using Polars, prefer `pl.scan_parquet()` over `pl.read_parquet()` for large datasets to utilize lazy evaluation.
- When reading CSVs, do not specify default arguments (like `dtype`) unless needed to suppress type-inference warnings; keep reads clean.

## Documentation & Formatting
- Every time you create a resource, add properly formatted comments and documentation. Be clear but concise.
- Document all functions using Google-style docstrings.
- Add comments line by line for complex logic. Do not comment obvious code.
- After writing code, format it with `ruff format .` and lint it with `ruff check .`. Fix any issues those tools reveal. Run `mypy` on the source directory for type checking.
