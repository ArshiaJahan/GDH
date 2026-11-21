"""The shared bulk-delete detector (features/auto_mode.is_bulk_delete)."""
import pytest

from gamedevworkstation.features.auto_mode import always_ask_reason, is_bulk_delete

POSITIVE = [
    "rm -rf keep", "rm -fr keep", "rm -Rf keep", "rm -r -f keep", "rm -r keep", "rm --recursive keep",
    "rm -f -R a b", "/bin/rm -rf x", "sudo rm -rf /tmp/x", r"\rm -rf x", "rm a.txt -r",
    "rmdir -p a/b/c", "rmdir --parents a/b",
    "find . -name '*.tmp' -delete", "find . -type f -exec rm {} +", "find . -exec rm -f {} \\;",
    "git clean -fd", "git clean -f", "git clean -xdf", "git -C sub clean -d", "git clean --force",
    "git rm -r src", "git rm -rf src", "git rm --recursive src",
    "ls | xargs rm", "find . -print0 | xargs -0 rm -f", "shred -u secret.txt",
    "rsync -a --delete src/ dst/", "rsync -a --delete-after src/ dst/",
    "Remove-Item -Recurse -Force build", "remove-item build -recurse", "ri -Rec build",
    "del /s /q build", "DEL /S build", "rd /s /q build", "rmdir /s build",
    # compound and nested
    "cd x && rm -rf y", "make || rm -rf build", "echo hi; rm -rf y", "cat f | xargs rm",
    "(cd x && rm -rf y)", "echo $(rm -rf y)", "echo `rm -rf y`", "true\nrm -rf y",
    'bash -c "rm -rf y"', "sh -c 'cd a; rm -rf b'", "bash -lc \"ls && git clean -fdx\"",
    "sudo bash -c 'sh -c \"rm -rf y\"'", "ls & rm -rf y",
]
NEGATIVE = [
    "", "   ", "rm file.txt", "rm -f file.txt", "rm -i a b", "rm a b c", "rmdir empty", "ls -R", "ls -lr",
    "find . -name '*.py'", "find . -exec grep foo {} +", "git clean -n", "git rm file.txt", "git status",
    "git commit -m 'update'", "xargs echo", "rsync -a src/ dst/", "echo hello && ls", "cat rm.txt",
    "Remove-Item file.txt", "del file.txt", "rd empty", "pytest -q && npm run build", "bash -c 'echo hi'",
    "grep -r foo .", "cp -r a b", "chmod -R 755 x",
]


@pytest.mark.parametrize("cmd", POSITIVE)
def test_positive(cmd):
    assert is_bulk_delete(cmd), cmd


@pytest.mark.parametrize("cmd", NEGATIVE)
def test_negative(cmd):
    assert not is_bulk_delete(cmd), cmd


def test_non_string_is_false():
    assert not is_bulk_delete(None)  # type: ignore[arg-type]


GIT_POSITIVE = [
    "git push --force origin main", "git push -f origin main", "git push -fu origin main", "git push origin main -f",
    "git push --force-with-lease", "git push --force-if-includes origin x", "git push --mirror",
    "git push --delete origin old", "git push -d origin old", "git push origin +main", "git push origin :old-branch",
    "git -C sub push --force", "git -c core.x=1 push -f", "git --git-dir=.git push -f",
    "git reset --hard", "git reset --hard HEAD~3", "git reset --merge", "git reset --keep HEAD~1",
    "git rebase main", "git rebase -i HEAD~3", "git rebase --onto a b c", "git pull --rebase", "git pull -r origin x",
    "git filter-branch --tree-filter x", "git filter-repo --path a",
    "git branch -D old", "git branch --delete --force old", "git branch -d -f old", "git branch -df old",
    "git tag -d v1", "git tag --delete v1",
    "git reflog expire --expire=now --all", "git reflog delete HEAD@{1}", "git gc --prune=now", "git update-ref -d refs/x",
    "git checkout --force main", "git checkout -f main", "git switch --discard-changes x", "git switch -f x",
    "git checkout -- .", "git checkout .", "git restore .", "git stash drop", "git stash clear", "git stash drop stash@{1}",
    "cd x && git push --force", "make; git reset --hard", 'bash -c "git rebase -i HEAD~2"',
    "sh -c 'ls && git push origin +main'", "(git stash clear)", "sudo git push -f",
]
GIT_NEGATIVE = [
    "git push", "git push origin main", "git push -u origin main", "git push --set-upstream origin feat",
    "git push --tags", "git fetch", "git fetch --all --prune", "git pull", "git pull origin main", "git pull --ff-only",
    "git commit -m 'rebase notes'", "git commit --amend --no-edit", "git merge feature", "git status", "git log --oneline",
    "git diff", "git branch", "git branch -a", "git branch -d merged", "git branch feature", "git tag", "git tag v1",
    "git reset", "git reset --soft HEAD~1", "git reset HEAD file", "git checkout -b feat", "git checkout main",
    "git switch main", "git restore file.txt", "git restore --staged file.txt", "git stash", "git stash pop",
    "git stash list", "git reflog", "git gc", "git update-ref refs/x abc", "git -C sub status",
    "git checkout main -- file.txt", "git cherry-pick abc",
]


@pytest.mark.parametrize("cmd", GIT_POSITIVE)
def test_git_rewrite_positive(cmd):
    assert always_ask_reason(cmd) == "git history rewrite", cmd
    assert not is_bulk_delete(cmd)


@pytest.mark.parametrize("cmd", GIT_NEGATIVE)
def test_git_rewrite_negative(cmd):
    assert always_ask_reason(cmd) is None, cmd


def test_always_ask_reason_bulk_delete_wins_and_negatives():
    assert always_ask_reason("git reset --hard && rm -rf x") == "bulk delete"
    assert always_ask_reason("git clean -fd") == "bulk delete"
    assert always_ask_reason("rm file.txt") is None and always_ask_reason("") is None
    assert always_ask_reason(None) is None  # type: ignore[arg-type]
