"""Only the fields PR-Guard needs from a GitHub pull_request payload.

GitHub sends dozens of fields; Pydantic ignores extras. Keeping this schema small makes
the trust boundary explicit and avoids persisting the full untrusted payload.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RepoRef(_Model):
    full_name: str | None = None
    fork: bool = False


class Head(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sha: str = Field(min_length=7, max_length=64)
    ref: str = ""
    repo: RepoRef | None = None


class BaseRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sha: str = Field(min_length=7, max_length=64)


class PullRequest(_Model):
    head: Head
    base: BaseRef
    user: dict | None = None
    draft: bool = False


class Repository(_Model):
    full_name: str = Field(min_length=3, max_length=255)
    name: str = Field(min_length=1, max_length=200)
    owner: Owner


class Owner(_Model):
    login: str = Field(min_length=1, max_length=100)


class Installation(_Model):
    id: int


class Sender(_Model):
    login: str = "unknown"


class PullRequestEvent(_Model):
    action: str
    number: int = Field(gt=0)
    pull_request: PullRequest
    repository: Repository
    installation: Installation
    sender: Sender = Sender()


def payload_is_fork(event: PullRequestEvent) -> bool:
    """A PR is treated as a fork PR when head repo differs from the base repo.

    Checking only ``head.repo.fork`` misses organisation forks; comparing full names
    covers both. A deleted head repo is conservative: treat as fork.
    """

    head_repo = event.pull_request.head.repo
    if head_repo is None or head_repo.full_name is None:
        return True
    return head_repo.fork or head_repo.full_name.lower() != event.repository.full_name.lower()
