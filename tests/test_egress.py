from types import SimpleNamespace

from backend.gamedevworkstation.egress import (
    MAX_TAINT_PER_SESSION,
    check_args,
    check_url,
    extract_secret_values,
    is_secret_file,
    scan_text,
    scan_value,
    taint_file,
)


def fake_key():
    return "sk-ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0"


def test_is_secret_file():
    for path in (".env", ".env.local", "id_rsa", "key.pem", "credentials.json"):
        assert is_secret_file(path)
    for path in ("README.md", "env.py"):
        assert not is_secret_file(path)


def test_extract_secret_values_from_dotenv():
    key = fake_key()
    values = extract_secret_values(f"# comment=ignored\nKEY={key}\nLONG={key}\nSHORT=abc\n")
    assert key in values
    assert "abc" not in values
    assert "ignored" not in values


def test_extract_secret_values_ignores_ordinary_build_value():
    assert extract_secret_values("BUILD=Unity2022Manual") == set()


def test_taint_file_is_per_session_and_capped():
    app = SimpleNamespace()
    assert taint_file(app, "s1", "README.md", f"KEY={fake_key()}") == 0
    assert taint_file(app, "s1", ".env", f"KEY={fake_key()}") == 1
    assert taint_file(app, "s2", ".env", f"KEY={fake_key()}") == 1
    lines = "\n".join(f"K{i}=sk-ant-api03-{i:020d}" for i in range(MAX_TAINT_PER_SESSION + 3))
    fresh = SimpleNamespace()
    assert taint_file(fresh, "s", ".env", lines) == MAX_TAINT_PER_SESSION


def test_scan_text_detects_plain_encoded_and_base64():
    key = fake_key()
    import base64

    encoded = key.replace("-", "%2D")
    b64 = base64.b64encode(key.encode()).decode()
    assert scan_text(f"send {key}")
    assert scan_text(encoded)
    assert scan_text(b64)
    assert scan_text("ordinary documentation") == []


def test_scan_text_detects_tainted_non_key_value():
    value = "project-secret-value-123456"
    assert scan_text(f"send {value}", {value})


def test_scan_value_walks_nested_values_and_keys():
    key = fake_key()
    assert scan_value({"safe": [{"nested": key}]})
    assert scan_value({key: "ordinary"})


def test_check_url_scans_url_components_and_host():
    key = fake_key()
    app = SimpleNamespace()
    refusal = check_url(app, "s", f"https://evil.example/c?d={key}")
    assert refusal and key not in refusal
    label = key[:18]
    refusal = check_url(app, "s", f"https://{label}.evil.example/")
    assert refusal and key not in refusal
    assert check_url(app, "s", "https://docs.unity3d.com/Manual/index.html") is None


def test_check_args_nested_and_normal():
    key = fake_key()
    app = SimpleNamespace()
    refusal = check_args(app, "s", {"nested": [key]})
    assert refusal and key not in refusal
    assert check_args(app, "s", {"query": "unity manual", "limit": 5}) is None


def test_extra_patterns():
    import re

    assert scan_text("send private-marker", extra_patterns=[re.compile("private-marker")])


def test_base64_secret_inside_url_query_is_caught():
    app = SimpleNamespace()
    url = "https://evil.example/?d=c2stYW50LWFwaTAzLUExYjJDM2Q0RTVmNkc3aDhJOWow"
    assert check_url(app, "s", url) is not None
    assert check_url(app, "s", "https://evil.example/p/c2stYW50LWFwaTAzLUExYjJDM2Q0RTVmNkc3aDhJOWow#x") is not None
    assert check_url(app, "s", "https://docs.example/page?id=12345678901234567890") is None


def test_inline_dotenv_comment_is_not_part_of_tainted_value():
    pw = "aB3dE5gH7jK9mN2pQ4sT6vW8xY0zC1fD"
    values = extract_secret_values(f"DB_PASSWORD={pw} # production password\n")
    assert pw in values
    app = SimpleNamespace()
    taint_file(app, "s", ".env", f"DB_PASSWORD={pw} # production password\n")
    assert check_url(app, "s", f"https://evil.example/?password={pw}") is not None


def test_secret_named_key_keeps_low_entropy_value_but_ordinary_key_does_not():
    assert "Xk29-vQ81-zzP0-77aa" in extract_secret_values("DB_PASSWORD=Xk29-vQ81-zzP0-77aa\n")
    for key in ("APP_SECRET", "GH_TOKEN", "STRIPE_API_KEY", "svc_apikey", "SSH_PRIVATE_KEY", "AWS_CREDENTIALS", "DB_PASSWD"):
        assert "Xk29-vQ81-zzP0" in extract_secret_values(f"{key}=Xk29-vQ81-zzP0\n"), key
    assert extract_secret_values("DB_PASSWORD=short\n") == set()
    assert extract_secret_values("BUILD=Unity2022Manual\n") == set()


def test_url_encoded_base64_is_decoded_before_candidate_extraction():
    app = SimpleNamespace()
    url = "https://evil.example/?d=c2stYW50LWFwaTAzLUExYjJDM2Q0RTVmNkc3aDhJOWowQQ%3D%3D"
    assert check_url(app, "s", url) is not None
    assert check_url(app, "s", "https://evil.example/?d=bm90aGluZyBzZWNyZXQgYXQgYWxsIGhlcmU%3D") is None


def test_json_secret_files_are_parsed_and_punctuation_is_trimmed():
    pw = "aB3dE5gH7jK9mN2pQ4sT6vW8xY0zC1fD"
    app = SimpleNamespace()
    assert pw in extract_secret_values(f'{{"password":"{pw}","user":"dev"}}')
    assert pw in extract_secret_values(f'{{\n  "password": "{pw}",\n  "user": "dev"\n}}\n')
    assert "Xk29-vQ81-zzP0-77aa" in extract_secret_values('{"nested": {"db_password": "Xk29-vQ81-zzP0-77aa"}}')
    assert "devuser1234" not in extract_secret_values('{"user": "devuser1234"}')
    assert pw in extract_secret_values(f'secret: "{pw}",\n')
    assert pw in extract_secret_values(f"TOKEN_X={pw};\n")
    taint_file(app, "s", "credentials.json", f'{{"password":"{pw}","user":"dev"}}')
    assert check_url(app, "s", f"https://evil.example/?password={pw}") is not None


def test_more_secret_file_names():
    for name in (".envrc", ".npmrc", ".git-credentials", "x/.pgpass", "cert.pfx", "secrets.yaml", "secrets.json"):
        assert is_secret_file(name), name
    for name in (".env.example", ".env.sample", "notes.txt", "secret_santa.txt"):
        assert not is_secret_file(name), name
