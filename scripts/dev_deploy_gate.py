#!/usr/bin/env python3
"""Two guards over the dev deploy path. Both read GitHub; neither touches AWS.

`resolve-ref` answers one question for a manually dispatched `Deploy Dev` run:
which commit may this run deploy? A dispatch has no push event behind it, so the
ref it names is checked against `dev`'s history before anything is deployed -
the branch head, or a commit already merged into it. That makes a lost push
event recoverable with one command, and keeps an unreleased tree off
`https://dev.kernelworx.app`.

`check-drift` answers the question no other job asked: does the deployed dev
environment serve `dev`'s head? A merge that produces no `Deploy Dev` run (a
push event GitHub never emitted) leaves `dev` claiming a fix the environment
does not run, and nothing goes red. The check compares `dev`'s head with the
head of the last successful `Deploy Dev` run and fails loudly when they differ.
It deploys nothing: it holds no cloud credentials, no OIDC token, and no
deployable workflow.

Both commands speak only to the GitHub REST API with the run's own `GITHUB_TOKEN`
(`contents: read` plus, for the drift check, `actions: read`).

Recovery, once drift is confirmed:

    gh workflow run deploy-dev.yml --ref dev -f ref=dev

Docs: docs/scripts/README.md, "Dev deploy: recovering a lost push event".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

API_VERSION = "2022-11-28"
USER_AGENT = "kernelworx-dev-deploy-gate"

# A ref is a branch/tag name or a full commit SHA. The character class keeps a
# hand-typed value from turning into a URL path trick on the way to the API.
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# A workflow run that has not reached a conclusion yet. A deploy for `dev`'s
# head in this state is not drift: the environment is on its way.
OPEN_STATUSES = frozenset({"queued", "pending", "requested", "in_progress", "waiting"})

# `compare/{base}...{head}` statuses that prove base is reachable from head.
ANCESTOR_STATUSES = frozenset({"identical", "ahead"})


class GateError(RuntimeError):
    """A guard could not be answered: bad input, or the API said no."""


def _http_get(url: str, headers: dict[str, str]) -> tuple[int, str]:
    """Fetch `url` and return its status code and body. Replaced in tests."""
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise GateError(f"cannot reach the GitHub API at {url}: {exc.reason}") from exc


class GitHubApi:
    """A read-only GitHub REST client built from the workflow's own token."""

    def __init__(
        self,
        repository: str,
        token: str,
        api_root: str,
        http_get: Callable[[str, dict[str, str]], tuple[int, str]] | None = None,
    ) -> None:
        self.repository = repository
        self._token = token
        self._api_root = api_root.rstrip("/")
        # Resolved at call time, not bound as a default, so a test can replace
        # the module's transport without rebuilding the client.
        self._http_get = http_get or _http_get

    @classmethod
    def from_environment(cls) -> GitHubApi:
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        if not repository or "/" not in repository:
            raise GateError("GITHUB_REPOSITORY is not set to owner/name; run this inside a workflow or pass --repository")
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
        if not token:
            raise GateError("GITHUB_TOKEN (or GH_TOKEN) is not set; the guard reads the API as the workflow's own identity")
        api_root = os.environ.get("GITHUB_API_URL") or "https://api.github.com"
        return cls(repository, token, api_root)

    def get(self, path: str, **params: object) -> dict[str, Any]:
        url = f"{self._api_root}/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        }
        status, body = self._http_get(url, headers)
        if status >= 300:
            detail = _api_error_body(body)
            raise GateError(f"GitHub API {status} for {path}: {detail}")
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise GateError(f"GitHub API returned a non-JSON body for {path}") from exc
        if not isinstance(decoded, dict):
            raise GateError(f"GitHub API returned an unexpected shape for {path}")
        return decoded


def _api_error_body(body: str) -> str:
    """The message GitHub puts in an error body, or a trimmed raw snippet."""
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        return (body[:300] or "empty response").strip()
    if isinstance(decoded, dict):
        message = decoded.get("message")
        if isinstance(message, str) and message:
            return message
    return (body[:300] or "empty response").strip()


def _require_sha(value: object, label: str) -> str:
    if isinstance(value, str) and SHA_RE.match(value):
        return value
    raise GateError(f"{label} is not a full commit SHA: {value!r}")


def resolve_ref(api: GitHubApi, ref: str, branch: str) -> str:
    """Resolve `ref` to a full SHA that `dev` may deploy.

    `ref` must be the branch itself or a commit reachable from it. A dispatch
    against a feature branch, or a commit that was never merged into `dev`, is
    refused: the dev environment must only ever serve `dev`'s history.
    """
    if not REF_RE.match(ref) or ".." in ref:
        raise GateError(f"ref {ref!r} is not a usable branch, tag, or full commit SHA")
    commit = api.get(f"repos/{api.repository}/commits/{urllib.parse.quote(ref, safe='')}")
    sha = _require_sha(commit.get("sha"), f"commit for {ref!r}")
    comparison = api.get(f"repos/{api.repository}/compare/{sha}...{urllib.parse.quote(branch, safe='')}")
    status = comparison.get("status")
    if not isinstance(status, str):
        raise GateError(f"cannot compare {sha[:12]} with {branch}: the API returned no comparison status")
    if status not in ANCESTOR_STATUSES:
        raise GateError(
            f"{ref} ({sha[:12]}) is {status} relative to {branch}: a dev deploy may only target "
            f"the {branch} head or a commit already merged into {branch}"
        )
    return sha


@dataclass(frozen=True)
class WorkflowRun:
    """The fields of a `Deploy Dev` run the drift decision reads."""

    run_id: int
    head_sha: str
    status: str
    conclusion: str
    created_at: str
    html_url: str
    event: str


def _as_run(raw: dict[str, Any]) -> WorkflowRun:
    return WorkflowRun(
        run_id=int(raw.get("id", 0)),
        head_sha=str(raw.get("head_sha", "")),
        status=str(raw.get("status", "")),
        conclusion=str(raw.get("conclusion") or ""),
        created_at=str(raw.get("created_at", "")),
        html_url=str(raw.get("html_url", "")),
        event=str(raw.get("event", "")),
    )


def _age_minutes(created_at: str, now: datetime) -> int | None:
    """Minutes between a run's `created_at` and `now`, or None if unparseable."""
    if not created_at:
        return None
    try:
        stamp = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0, int((now - stamp).total_seconds() // 60))


@dataclass(frozen=True)
class DriftReport:
    """One verdict about whether `dev`'s head is deployed, with the evidence."""

    state: str
    ok: bool
    dev_sha: str
    dev_date: str
    deploy_sha: str | None
    deploy_run: WorkflowRun | None
    age_minutes: int | None
    window: int
    total_count: int
    open_runs: tuple[WorkflowRun, ...]
    failed_runs: tuple[WorkflowRun, ...]

    @property
    def headline(self) -> str:
        """The one line that has to stand on its own in the Actions annotations list."""
        deployed = self.deploy_sha or "no successful deploy run in the inspected window"
        if self.state == "aligned":
            return f"dev head {self.dev_sha} is deployed"
        if self.state == "deploy_in_progress":
            return f"dev head {self.dev_sha} has a Deploy Dev run in progress (not drift yet)"
        if self.state == "failed_deploy":
            return (
                f"DEPLOY DRIFT: dev head {self.dev_sha} is not deployed - its Deploy Dev run failed; "
                f"last successful deploy is {deployed}"
            )
        if self.state == "no_run_for_head":
            return (
                f"DEPLOY DRIFT: dev head {self.dev_sha} has no Deploy Dev run at all; "
                f"last successful deploy is {deployed}"
            )
        return f"DEPLOY DRIFT: dev head {self.dev_sha} has no successful Deploy Dev run to compare against"


def classify_drift(dev_sha: str, dev_date: str, runs: list[WorkflowRun], now: datetime, window: int, total_count: int) -> DriftReport:
    """Decide whether `dev`'s head is what the last successful deploy served."""
    for run in runs:
        if run.head_sha == dev_sha and run.status == "completed" and run.conclusion == "success":
            return DriftReport("aligned", True, dev_sha, dev_date, dev_sha, run, _age_minutes(run.created_at, now), window, total_count, (), ())
    open_runs = tuple(run for run in runs if run.head_sha == dev_sha and run.status in OPEN_STATUSES)
    if open_runs:
        return DriftReport("deploy_in_progress", True, dev_sha, dev_date, None, None, None, window, total_count, open_runs, ())
    failed_runs = tuple(
        run for run in runs if run.head_sha == dev_sha and run.status == "completed" and run.conclusion != "success"
    )
    last_success = next((run for run in runs if run.status == "completed" and run.conclusion == "success"), None)
    deploy_sha = last_success.head_sha if last_success else None
    age = _age_minutes(last_success.created_at, now) if last_success else None
    if failed_runs:
        state = "failed_deploy"
    elif last_success:
        state = "no_run_for_head"
    else:
        state = "no_successful_run"
    return DriftReport(state, False, dev_sha, dev_date, deploy_sha, last_success, age, window, total_count, open_runs, failed_runs)


def check_drift(api: GitHubApi, branch: str, workflow_file: str, per_page: int, now: datetime) -> DriftReport:
    """Read `dev`'s head and the `Deploy Dev` runs for it, then classify."""
    head = api.get(f"repos/{api.repository}/commits/{urllib.parse.quote(branch, safe='')}")
    dev_sha = _require_sha(head.get("sha"), f"{branch} head")
    commit = head.get("commit") if isinstance(head.get("commit"), dict) else {}
    committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
    dev_date = str(committer.get("date") or "")
    payload = api.get(
        f"repos/{api.repository}/actions/workflows/{urllib.parse.quote(workflow_file, safe='')}/runs",
        branch=branch,
        per_page=per_page,
    )
    raw_runs = payload.get("workflow_runs")
    if not isinstance(raw_runs, list):
        raise GateError(f"the runs listing for {workflow_file} returned no workflow_runs list")
    runs = [_as_run(run) for run in raw_runs if isinstance(run, dict)]
    total_count = int(payload.get("total_count", len(runs)))
    return classify_drift(dev_sha, dev_date, runs, now, len(runs), total_count)


def _write_output(name: str, value: str) -> None:
    """Publish a step output when running as a workflow step."""
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def _run_description(run: WorkflowRun, now: datetime) -> str:
    age = _age_minutes(run.created_at, now)
    age_text = f"{age} min ago" if age is not None else f"created {run.created_at}"
    return (
        f"- run {run.run_id} ({run.event}, head {run.head_sha[:12]}, {run.status}"
        f"{f'/{run.conclusion}' if run.conclusion else ''}, {age_text})\n  {run.html_url}"
    )


def render_report(report: DriftReport, branch: str, workflow_file: str, now: datetime) -> None:
    """Print the verdict, and write it to the step summary when there is one."""
    lines = [
        f"dev head: {report.dev_sha} ({report.dev_date or 'date unknown'})",
        (
            f"last successful {workflow_file} run for {branch}: "
            f"head {(report.deploy_sha or 'none')} "
            f"(run {report.deploy_run.run_id if report.deploy_run else 'none'}, "
            f"{report.age_minutes if report.age_minutes is not None else '?'} min ago)"
        ),
    ]
    if report.open_runs:
        lines.append("deploy runs in progress for the dev head:")
        lines.extend(_run_description(run, now) for run in report.open_runs)
    if report.failed_runs:
        lines.append("failed deploy runs for the dev head:")
        lines.extend(_run_description(run, now) for run in report.failed_runs)
    if report.window < report.total_count:
        lines.append(f"(only the {report.window} most recent of {report.total_count} runs were inspected)")
    print("\n".join(lines))

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        verdict = "aligned" if report.ok else report.state
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"## Dev deploy state: {verdict}\n\n")
            handle.write(f"- `{branch}` head: `{report.dev_sha}`\n")
            if report.deploy_run:
                handle.write(f"- last successful deploy: `{report.deploy_sha}` in run {report.deploy_run.run_id}\n")
            for run in report.failed_runs + report.open_runs:
                handle.write(f"- run {run.run_id}: head `{run.head_sha[:12]}`, {run.status}/{run.conclusion}\n")
            if not report.ok:
                handle.write(
                    f"\nRecover with `gh workflow run {workflow_file.replace('.yml', '')}.yml --ref {branch} -f ref={branch}`.\n"
                )

    if not report.ok:
        print(f"::error::{report.headline}", flush=True)
        print(
            f"Recover without writing to {branch}: gh workflow run "
            f"{workflow_file} --ref {branch} -f ref={branch}",
            flush=True,
        )
    elif report.state == "deploy_in_progress":
        print(f"::notice::{report.headline}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "dev deploy guard")
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve-ref", help="resolve a dispatch ref to a deployable dev commit")
    resolve.add_argument("--ref", default="dev", help="branch, tag, or full commit SHA to deploy (default: dev)")
    resolve.add_argument("--branch", default="dev", help="branch whose history the ref must sit on (default: dev)")

    drift = subparsers.add_parser("check-drift", help="report whether dev's head has a successful deploy run")
    drift.add_argument("--branch", default="dev", help="branch to compare (default: dev)")
    drift.add_argument("--workflow-file", default="deploy-dev.yml", help="deploy workflow file (default: deploy-dev.yml)")
    drift.add_argument("--per-page", type=int, default=50, help="deploy runs to inspect (default: 50)")

    resolve.add_argument("--repository", default="", help="owner/name (default: GITHUB_REPOSITORY)")
    drift.add_argument("--repository", default="", help="owner/name (default: GITHUB_REPOSITORY)")

    args = parser.parse_args(argv)

    try:
        if args.repository:
            token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
            api_root = os.environ.get("GITHUB_API_URL") or "https://api.github.com"
            api = GitHubApi(args.repository, token, api_root)
        else:
            api = GitHubApi.from_environment()

        if args.command == "resolve-ref":
            sha = resolve_ref(api, args.ref, args.branch)
            _write_output("sha", sha)
            print(f"deploying {sha} ({args.ref}) - it is on {args.branch}'s history")
            return 0

        now = datetime.now(timezone.utc)
        report = check_drift(api, args.branch, args.workflow_file, args.per_page, now)
        render_report(report, args.branch, args.workflow_file, now)
        return 0 if report.ok else 1
    except GateError as exc:
        print(f"::error::{exc}", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
