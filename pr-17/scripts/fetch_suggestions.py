"""Write open topic-suggestion issues to suggestions/issues.yml for the Suggestion box listing.

Runs as a Quarto pre-render step. Issues count as suggestions when they carry the
`suggestion` label or their title starts with "[Topic]:" (the issue form's prefix).
On any network error the previous file is kept, or an empty list is written.
"""

import json
import os
import re
import urllib.request

REPO = os.environ.get("GITHUB_REPOSITORY", "cheac-ai/cheac-ai.github.io")
OUT = os.path.join(os.path.dirname(__file__), "..", "suggestions", "issues.yml")
PREFIX = "[Topic]:"


def fetch_issues():
    url = f"https://api.github.com/repos/{REPO}/issues?state=open&per_page=100"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def form_field(body, heading):
    """Return the answer under a '### heading' in an issue-form body."""
    match = re.search(rf"^### {re.escape(heading)}\s*\n(.*?)(?=^### |\Z)", body or "", re.S | re.M)
    if not match:
        return ""
    text = match.group(1).strip()
    return "" if text == "_No response_" else text


def is_suggestion(issue):
    if "pull_request" in issue:
        return False
    labels = {label["name"] for label in issue.get("labels", [])}
    return "suggestion" in labels or issue["title"].startswith(PREFIX)


def quote(text):
    return json.dumps(" ".join(text.split()), ensure_ascii=False)


def main():
    try:
        issues = [issue for issue in fetch_issues() if is_suggestion(issue)]
    except Exception as error:  # offline or rate-limited: keep what we have
        print(f"fetch_suggestions: {error}")
        if not os.path.exists(OUT):
            open(OUT, "w").write("[]\n")
        return

    lines = []
    for issue in issues:
        title = form_field(issue["body"], "Topic") or issue["title"].removeprefix(PREFIX).strip()
        # The list shows the first paragraph; the issue holds the rest.
        question = form_field(issue["body"], "What should be discussed?").split("\n\n")[0]
        if len(question) > 200:
            question = question[:197].rstrip() + "…"
        lines += [
            f"- title: {quote(title)}",
            f"  description: {quote(question)}",
            f"  path: {issue['html_url']}",
            f"  date: {issue['created_at']}",
        ]
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n" if lines else "[]\n")
    print(f"fetch_suggestions: {len(issues)} suggestion(s)")


if __name__ == "__main__":
    main()
