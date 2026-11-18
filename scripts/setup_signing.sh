#!/usr/bin/env bash
# One-time: a self-signed code-signing certificate, "GameDevWorkstation Local Signing", in your login
# keychain, trusted for code signing only. scripts/build_mac.sh then signs every build with it, so
# the Keychain's "Always Allow" carries over from build to build (an ad-hoc signature changes each
# build). The private key never leaves your login keychain; nothing is uploaded.
#
# macOS asks for your password to trust the certificate (and once more when codesign first uses the
# key: choose Always Allow). Undo: delete "GameDevWorkstation Local Signing" in Keychain Access.
# If you have Xcode with an Apple ID, an "Apple Development" certificate works too and needs no script.
set -euo pipefail
NAME="GameDevWorkstation Local Signing"
KC="$HOME/Library/Keychains/login.keychain-db"
if security find-identity -v -p codesigning | grep -q "\"$NAME\""; then
  echo "\"$NAME\" is already set up."; exit 0
fi
TMP="$(mktemp -d -t gdw-signing)"
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/cert.cnf" <<CNF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $NAME
[ext]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
CNF
/usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -keyout "$TMP/key.pem" -out "$TMP/cert.pem" -days 3650 -config "$TMP/cert.cnf" 2>/dev/null
PASS="$(/usr/bin/openssl rand -hex 16)"
/usr/bin/openssl pkcs12 -export -inkey "$TMP/key.pem" -in "$TMP/cert.pem" -out "$TMP/id.p12" -passout "pass:$PASS" -name "$NAME" 2>/dev/null \
  || /usr/bin/openssl pkcs12 -export -legacy -inkey "$TMP/key.pem" -in "$TMP/cert.pem" -out "$TMP/id.p12" -passout "pass:$PASS" -name "$NAME"
security import "$TMP/id.p12" -k "$KC" -P "$PASS" -T /usr/bin/codesign
echo "Trusting it for code signing (macOS asks for your password)…"
security add-trusted-cert -r trustRoot -p codeSign -k "$KC" "$TMP/cert.pem"
security find-identity -v -p codesigning | grep "\"$NAME\"" && echo "Done: builds are now signed with \"$NAME\"."
