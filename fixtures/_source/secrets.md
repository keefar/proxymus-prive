# Secret fixtures — Tier C PII

Source for `fixtures/secrets.jsonl`. Run `python tools/build_fixtures.py` to regenerate.
All keys/passwords are obviously fake — formatted to look real but never copy real
vendor patterns verbatim. See `docs/MODELS.md` § "Synthetic-data rules".

---

## id: en-env-01 lang=en bucket=secrets notes="dotenv with mixed secret types"

```
DATABASE_URL=⟦CONNECTION_STRING|postgres://app:s3cr3t-not-real@db-primary.internal.example.com:5432/appdb⟧
OPENAI_API_KEY=⟦API_KEY|xk-fake-AAAAAAAAAAAAAAAAAAAAT3BlbkFJ-not-real-key-do-not-use⟧
GITHUB_TOKEN=⟦TOKEN|ghp_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE⟧
JWT_SIGNING_SECRET=⟦CREDENTIAL|dGhpc19pc19hX2Zha2Vfc2VjcmV0X2Jhc2U2NA==⟧
ADMIN_PASSWORD=⟦PASSWORD|hunter2-not-a-real-pw⟧
```

## id: de-env-01 lang=de bucket=secrets notes="dotenv mit Kommentaren"

```
# Produktivumgebung — bitte nicht ins Repo
DB_URL=⟦CONNECTION_STRING|mysql://api_user:Geh3im!2026@db-primary.internal.example.com:3306/prod⟧
SMTP_PASSWORD=⟦PASSWORD|Sommer2026!Korrekt-Pferd⟧
STRIPE_KEY=⟦API_KEY|sk_test_FAKE_51AbCdEfGhIjKlMnOpQrStUvWxYz⟧
```

## id: en-ssh-01 lang=en bucket=secrets notes="ssh private key paste"

```
-----BEGIN OPENSSH PRIVATE KEY-----
⟦PRIVATE_KEY|b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACBmYWtlLWtleS1mYWtlLWtleS1mYWtlLWtleS1mYWtlLWtleS1mYWtlLWtleQ
AAAJDsfakeFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE=⟧
-----END OPENSSH PRIVATE KEY-----
```

## id: en-code-secret-01 lang=en bucket=secrets notes="hardcoded API key in Python"

```python
# TODO: move to env var before commit
client = OpenAI(api_key=⟦API_KEY|"xk-fake-AAAAAAAAAAAAAAAAAAAAT3BlbkFJ-not-real-key"⟧)
slack_webhook = ⟦TOKEN|"https://hooks.slack.com/services/T00000000/B00000000/FAKEFAKEFAKEFAKEFAKE"⟧
```

## id: en-code-secret-02 lang=en bucket=secrets notes="DSN with creds inside SQLAlchemy"

```python
engine = create_engine(
    ⟦CONNECTION_STRING|"postgresql+psycopg://app_rw:correct-horse-battery-fake@10.0.4.21:5432/orders"⟧,
    pool_size=8,
)
```

## id: en-oauth-01 lang=en bucket=secrets notes="OAuth bearer token pasted into chat"

I logged in via the CLI but the call still fails. Token is ⟦TOKEN|Bearer eyJhbGciOiJIUzI1NiJ9.fake-payload-fake-payload-fake-payload.fake-signature-fake-signature⟧, any idea why?

## id: en-config-secret-01 lang=en bucket=secrets notes="kubernetes secret yaml"

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-creds
type: Opaque
data:
  password: ⟦PASSWORD|c3VwZXItZmFrZS1wYXNzd29yZA==⟧
  api-key: ⟦API_KEY|c2stZmFrZS1BQUFBQUFBQUFBQUFBQQ==⟧
```

## id: de-password-01 lang=de bucket=secrets notes="passwort in slack-paste"

ich krieg's nicht hin, kannst du mal probieren? login ist ⟦PERSON|alice⟧ und passwort ist ⟦PASSWORD|Frühling-2026-korrekt!⟧, ist nur ein test-account

## id: en-gpg-01 lang=en bucket=secrets notes="public key — looks like a secret but is NOT (test of false-positive avoidance)"

For verification, here is the public key for signed releases — this is intentionally public:

```
-----BEGIN PGP PUBLIC KEY BLOCK-----

mQENBGRyFakeFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE
fakefakefakefakefakefakefakefakefakefakefakefakefakefakefakefakef
-----END PGP PUBLIC KEY BLOCK-----
```

## id: en-mixed-01 lang=en bucket=secrets notes="adversarial — looks like key but is a UUID; real key is below"

The session UUID is 6ba7b810-9dad-11d1-80b4-00c04fd430c8 — not sensitive. The actual API key is ⟦API_KEY|xk-live-FAKEAAAAAAAAAAAAAAAAAAAAT3BlbkFJ-not-real⟧, keep this one out of logs.
