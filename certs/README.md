# Supabase public CA certificate

Download **your project's** Server root certificate / CA certificate from the
Supabase Dashboard → Database Settings → SSL Configuration. Copy the downloaded
PEM certificate to **certs/supabase-ca.crt** and commit that public CA file through
GitHub's Add file → Upload files. Do not change its contents or create a dummy CA.

Only the public CA belongs here. Never upload a database URL, password, private
key, exported user data, .env or secrets.toml. No real project CA was available
when this change was developed; this directory intentionally contains no
placeholder .crt that could be mistaken for a trusted certificate.

Alternatively, store the full PEM certificate in the encrypted GitHub Actions
Repository Secret **SUPABASE_CA_CERT**. The read-only diagnostic writes it to a
private temporary file for the duration of the command, then deletes it. The
repository certificate takes precedence; an invalid repository file fails
closed rather than falling back to a different CA or the system trust store.

Browser-only setup and exact verification steps: [Supabase explicit CA](../docs/SUPABASE_CA.md).
