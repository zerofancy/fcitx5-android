#!/usr/bin/env bash
# Enter passwords locally; they are never passed as command-line arguments.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

read -r -s -p 'Keystore password: ' signing_store_password
printf '\n'
read -r -s -p 'Private key password (Enter to reuse keystore password): ' signing_key_password
printf '\n'
signing_key_password=${signing_key_password:-$signing_store_password}

SIGN_STORE_PASSWORD="$signing_store_password" ./gradlew \
    --no-daemon --no-configuration-cache --console=plain -PkeyringSigning=false \
    :setSecretValue --name=android_store_password
SIGN_KEY_PASSWORD="$signing_key_password" ./gradlew \
    --no-daemon --no-configuration-cache --console=plain -PkeyringSigning=false \
    :setSecretValue --name=android_key_password

printf 'Passwords saved. Enable keyringSigning=true in local.properties, then run ./gradlew --no-configuration-cache :app:verifyReleaseSigning\n'
