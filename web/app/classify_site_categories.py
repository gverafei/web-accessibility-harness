"""Assign the WebAIM category vocabulary with an explicitly pinned classifier."""

import json
from datetime import datetime

import requests

from database import get_connection
from local_llm import local_chat, local_configuration
from settings import get_settings
from category_models import load_category_snapshot

CATEGORIES = (
    "Government", "Non-Profit/Charity", "Science", "Personal Finance", "Careers",
    "Law/Government/Politics", "Social Media", "Education", "Technology", "Business",
    "Gambling/Casinos", "Health", "Family & Parenting", "Gaming", "Food & Drink",
    "Religion & Spirituality", "Society", "News/Weather/Information",
    "Arts & Entertainment", "Automotive", "Pets", "Adult Content", "Travel",
    "Real Estate", "Hobbies & Interests", "Home & Garden", "Style and Fashion",
    "Shopping", "Sports",
)
ALIASES = {
    "Music": "Arts & Entertainment", "Entertainment": "Arts & Entertainment",
    "Finance": "Personal Finance", "News": "News/Weather/Information",
    "Weather": "News/Weather/Information", "Politics": "Law/Government/Politics",
    "Non-Profit": "Non-Profit/Charity", "Charity": "Non-Profit/Charity",
    "Fashion": "Style and Fashion", "E-commerce": "Shopping",
}


class CategoryResponseError(RuntimeError):
    """A paid response did not contain a usable, validated assignment."""


def classify(experiment_id, batch_size=40):
    settings = get_settings()
    config = local_configuration(settings)
    if not config:
        raise RuntimeError("A pinned local Ollama model is required for reproducible categorization.")
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT id,url,captured_url,page_title FROM experiment_results
           WHERE experiment_id=%s AND status='completed' AND site_category IS NULL
           ORDER BY id""",
        (experiment_id,),
    )
    rows = cursor.fetchall()
    updated = 0
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset:offset + batch_size]
        observations = [{"id": row["id"], "url": row.get("captured_url") or row["url"],
                         "title": row.get("page_title") or ""} for row in batch]
        prompt = (
            "Classify every website into exactly one category from this closed vocabulary:\n"
            + json.dumps(CATEGORIES) + "\n"
            "Use only the URL and captured page title. Return one JSON object whose keys are the numeric ids "
            "and values are exact vocabulary strings. Do not omit ids and do not add commentary.\n"
            + json.dumps(observations, ensure_ascii=False)
        )
        content, _input_tokens, _output_tokens = local_chat(
            config, [{"role": "user", "content": prompt}], json_mode=True,
            temperature=0, output_token_limit=4000,
        )
        payload = json.loads(content)
        if isinstance(payload, dict) and isinstance(payload.get("categories"), dict):
            payload = payload["categories"]
        if isinstance(payload, dict):
            payload = {key: ALIASES.get(value, value) for key, value in payload.items()}
        if not isinstance(payload, dict):
            raise RuntimeError("The local category classifier returned a non-object response.")
        expected = {str(row["id"]) for row in batch}
        if set(payload) != expected or any(value not in CATEGORIES for value in payload.values()):
            raise RuntimeError("The local category classifier omitted an id or returned an unknown category: " + content[:1000])
        source = f"ollama/{config['model']} · closed WebAIM 2026 vocabulary · temperature 0"
        for result_id, category in payload.items():
            cursor.execute(
                "UPDATE experiment_results SET site_category=%s,site_category_source=%s WHERE id=%s",
                (category, source, int(result_id)),
            )
            updated += 1
        conn.commit()
    cursor.close()
    conn.close()
    return updated


def classify_managed_urls(batch_size=10, one_batch=False, model=None, experiment_id=None, model_config=None):
    """Classify latest uncategorized completed observations shown in Manage URLs."""
    settings = get_settings()
    snapshot = load_category_snapshot(model_config, model)
    decisions = bool(snapshot and snapshot['provider'] == 'decisions')
    cloud = snapshot['provider'] in {'cloud','decisions'} if snapshot else bool(model and not model.startswith('ollama/'))
    config = snapshot['config'] if snapshot else (None if cloud else local_configuration(settings))
    if not config and not cloud:
        raise RuntimeError("A configured local Ollama model is required for categorization.")
    source_model = model if model else "ollama/" + config["model"]
    if not snapshot and model and model.startswith('ollama/'):
        config = {**config, 'model': model.removeprefix('ollama/')}
    if cloud and not config:
        # Compatibility for pre-snapshot jobs: keep their explicit provider/model.
        config = {'base_url': settings['openrouter_base_url'], 'model': model,
                  'reasoning_effort': 'low' if model.startswith('openai/') else None,
                  'supported_parameters': ['reasoning', 'response_format'] if model.startswith('openai/') else []}
    if cloud and not settings.get('openrouter_api_key'):
        raise RuntimeError('Configure the OpenRouter API key before categorization.')
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        scope = ' AND r.experiment_id=%s' if experiment_id else ''
        limit = ' LIMIT %s' if one_batch else ''
        parameters = ([experiment_id] if experiment_id else []) + ([batch_size] if one_batch else [])
        cursor.execute(
            """SELECT ranked.id,ranked.url,ranked.normalized_url,ranked.captured_url,ranked.page_title
               FROM (
                 SELECT r.id,r.url,r.normalized_url,r.captured_url,r.page_title,r.site_category,
                        ROW_NUMBER() OVER (
                   PARTITION BY COALESCE(r.normalized_url,CONCAT('id:',r.id))
                   ORDER BY COALESCE(r.evaluated_at,r.created_at) DESC,r.id DESC
                 ) result_rank
                 FROM experiment_results r WHERE r.status='completed'""" + scope + """
               ) ranked
               WHERE ranked.result_rank=1 AND ranked.site_category IS NULL
               ORDER BY ranked.id""" + limit, tuple(parameters)
        )
        rows = cursor.fetchall()
        if one_batch:
            rows = rows[:batch_size]
        updated = 0
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset:offset + batch_size]
            observations = [{
                "id": row["id"], "url": row.get("captured_url") or row["url"],
                "title": row.get("page_title") or "",
            } for row in batch]
            prompt = (
                "Classify every website into exactly one category from this closed vocabulary:\n"
                + json.dumps(CATEGORIES) + "\n"
                "Use only the URL and captured page title. Return one JSON object whose keys are the numeric ids "
                "and values are exact vocabulary strings. Do not omit ids and do not add commentary.\n"
                + json.dumps(observations, ensure_ascii=False)
            )
            if decisions:
                from managed_category_decisions import classify_batch
                content = classify_batch(settings, config, observations)
            elif cloud:
                request_payload = {'model': source_model, 'messages': [{'role': 'user', 'content': prompt}],
                                   'max_tokens': 4000}
                if 'response_format' in config['supported_parameters']:
                    request_payload['response_format'] = {'type': 'json_object'}
                if config.get('reasoning_effort') is not None:
                    request_payload['reasoning'] = {'effort': config['reasoning_effort']}
                response = requests.post(
                    config['base_url'].rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {settings['openrouter_api_key']}", "Content-Type": "application/json"},
                    json=request_payload,
                    timeout=300,
                )
                response.raise_for_status()
                envelope = response.json()
                usage = envelope.get("usage") or {}
                usage_conn = get_connection(); usage_cursor = usage_conn.cursor()
                usage_cursor.execute(
                    """UPDATE url_category_jobs SET input_tokens=input_tokens+%s,
                       output_tokens=output_tokens+%s,cost_usd=cost_usd+%s,updated_at=%s WHERE id=1""",
                    (int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0),
                     float(usage.get("cost") or 0), datetime.now()),
                )
                usage_conn.commit(); usage_cursor.close(); usage_conn.close()
                choices = envelope.get("choices") or []
                content = ((choices[0].get("message") or {}).get("content") if choices else None)
                if not content:
                    raise RuntimeError("The selected model returned no category response.")
            else:
                content, _input_tokens, _output_tokens = local_chat(
                    config, [{"role": "user", "content": prompt}], json_mode=True,
                    temperature=0, output_token_limit=4000,
                )
            payload = json.loads(content)
            if isinstance(payload, dict) and isinstance(payload.get("categories"), dict):
                payload = payload["categories"]
            if isinstance(payload, dict):
                payload = {key: ALIASES.get(value, value) if isinstance(value, str) else value
                           for key, value in payload.items()}
            expected = {str(row["id"]) for row in batch}
            # Each validated assignment is independent. Keep a nonempty valid
            # subset; omitted IDs remain NULL and are requested in the next
            # bounded batch. Never accept fabricated IDs or unknown labels.
            if not isinstance(payload, dict) or not payload or not set(payload).issubset(expected) or any(
                value not in CATEGORIES for value in payload.values()
            ):
                raise CategoryResponseError(
                    "The selected classifier returned empty, unexpected or unknown categories. "
                    + (json.dumps(payload, ensure_ascii=False)[:1000] if isinstance(payload, dict) else 'Non-object response')
                )
            effort = config.get('reasoning_effort')
            sampling = 'Decisions API · typed choices' if decisions else (('light reasoning' if effort == 'low' else 'reasoning ' + (effort or 'provider default')) if cloud else 'temperature 0')
            source = f"{source_model} · closed WebAIM 2026 vocabulary · {sampling}"
            rows_by_id = {str(row["id"]): row for row in batch}
            for result_id, category in payload.items():
                normalized_url = rows_by_id[result_id].get("normalized_url")
                if normalized_url:
                    cursor.execute(
                        """UPDATE experiment_results SET site_category=%s,site_category_source=%s
                           WHERE normalized_url=%s AND site_category IS NULL"""
                        + (' AND experiment_id=%s' if experiment_id else ''),
                        (category, source, normalized_url, experiment_id) if experiment_id else (category, source, normalized_url),
                    )
                else:
                    cursor.execute(
                        """UPDATE experiment_results SET site_category=%s,site_category_source=%s
                           WHERE id=%s AND site_category IS NULL""",
                        (category, source, int(result_id)),
                    )
                updated += 1
            conn.commit()
        return updated, source_model
    finally:
        cursor.close()
        conn.close()


def process_managed_url_categorization(batch_size=10):
    """Run the persisted Manage URLs categorization job until completion or stop."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM url_category_jobs WHERE id=1")
    job = cursor.fetchone()
    if not job or job.get("status") not in {"queued", "running", "stopping"}:
        cursor.close(); conn.close()
        return
    if job.get("status") == "stopping":
        cursor.execute(
            "UPDATE url_category_jobs SET status='stopped',updated_at=%s WHERE id=1",
            (datetime.now(),),
        )
        conn.commit(); cursor.close(); conn.close()
        return
    cursor.execute(
        "UPDATE url_category_jobs SET status='running',updated_at=%s WHERE id=1",
        (datetime.now(),),
    )
    conn.commit(); cursor.close(); conn.close()
    try:
        while True:
            conn = get_connection(); cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT status,total_urls,completed_urls FROM url_category_jobs WHERE id=1")
            state = cursor.fetchone() or {}
            cursor.close(); conn.close()
            if state.get("status") == "stopping":
                conn = get_connection(); cursor = conn.cursor()
                cursor.execute("UPDATE url_category_jobs SET status='stopped',updated_at=%s WHERE id=1", (datetime.now(),))
                conn.commit(); cursor.close(); conn.close()
                return
            for validation_attempt in range(3):
                try:
                    updated, model = classify_managed_urls(
                        batch_size=batch_size if validation_attempt == 0 else 1,
                        one_batch=True, model=job.get("model"),
                        experiment_id=job.get('experiment_id'),
                        model_config=job.get('model_config_json'),
                    )
                    break
                except (CategoryResponseError, json.JSONDecodeError):
                    # Two bounded single-record retries, using the same pinned
                    # model. Each paid call was already accounted for before
                    # parsing. No guessed categories or provider substitution.
                    if validation_attempt == 2:
                        raise
            conn = get_connection(); cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT status,total_urls,completed_urls FROM url_category_jobs WHERE id=1")
            state = cursor.fetchone() or {}
            completed = min(
                int(state.get("total_urls") or 0),
                int(state.get("completed_urls") or 0) + updated,
            )
            status = "stopped" if state.get("status") == "stopping" else (
                "completed" if not updated else "running"
            )
            cursor.execute(
                """UPDATE url_category_jobs
                   SET status=%s,completed_urls=%s,model=%s,error_message=NULL,updated_at=%s
                   WHERE id=1""",
                (status, completed, model, datetime.now()),
            )
            conn.commit(); cursor.close(); conn.close()
            if status != "running":
                return
    except Exception as error:
        if isinstance(error, requests.RequestException):
            public_error = "Could not connect to the selected category model. Check that Ollama is running or that the remote provider is configured."
        elif isinstance(error, json.JSONDecodeError):
            public_error = "The selected category model returned an invalid response. Try the other model or restart the job."
        else:
            public_error = "Automatic categorization stopped because the selected model could not complete a batch."
        conn = get_connection(); cursor = conn.cursor()
        cursor.execute(
            """UPDATE url_category_jobs
               SET status='failed',error_message=%s,updated_at=%s WHERE id=1""",
            (public_error, datetime.now()),
        )
        conn.commit(); cursor.close(); conn.close()
        raise


if __name__ == "__main__":
    import argparse
    from main import app
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=40)
    args = parser.parse_args()
    with app.app_context():
        print(classify(args.experiment, args.batch_size))
