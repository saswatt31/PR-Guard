from app.webhooks.payloads import PullRequestEvent, payload_is_fork
from tests.factories import pull_request_payload


def event(payload: dict) -> PullRequestEvent:
    return PullRequestEvent.model_validate(payload)


def test_same_repo_is_not_fork() -> None:
    assert payload_is_fork(event(pull_request_payload())) is False


def test_head_repo_fork_flag_is_detected() -> None:
    payload = pull_request_payload(fork=True)
    assert payload_is_fork(event(payload)) is True


def test_different_head_repo_is_treated_as_fork_even_without_flag() -> None:
    payload = pull_request_payload(head_repo="other/demo", fork=False)
    assert payload_is_fork(event(payload)) is True


def test_deleted_head_repo_is_conservatively_a_fork() -> None:
    payload = pull_request_payload()
    payload["pull_request"]["head"]["repo"] = None
    assert payload_is_fork(event(payload)) is True


def test_full_name_comparison_is_case_insensitive() -> None:
    payload = pull_request_payload()
    payload["repository"]["full_name"] = "ACME/DEMO"
    assert payload_is_fork(event(payload)) is False
