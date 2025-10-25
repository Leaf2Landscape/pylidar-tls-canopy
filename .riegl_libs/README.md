# Encrypted RIEGL Libraries

This directory contains **GPG-encrypted** RIEGL proprietary libraries.

## Files

- `rivlib.tar.gz.gpg` - Encrypted RiVLib SDK
- `rdblib.tar.gz.gpg` - Encrypted RDBLib SDK

## Security

These files are encrypted with AES256 and **safe to commit to public repositories**.

The decryption passphrase is stored in GitHub Secrets as `DECRYPTION_PASSPHRASE`.

## Usage

### GitHub Actions (Automatic)
The workflow automatically decrypts these files during Docker builds.

### Local Decryption
```bash
# Set passphrase (get from team admin)
export DECRYPTION_PASSPHRASE="your-passphrase"

# Decrypt
echo "$DECRYPTION_PASSPHRASE" | gpg --decrypt --batch --passphrase-fd 0 \
  rivlib.tar.gz.gpg > rivlib.tar.gz

echo "$DECRYPTION_PASSPHRASE" | gpg --decrypt --batch --passphrase-fd 0 \
  rdblib.tar.gz.gpg > rdblib.tar.gz

# Extract
tar -xzf rivlib.tar.gz
tar -xzf rdblib.tar.gz
```

## Updating

See `docs/GitHub_Actions_Setup.md` for instructions on updating the encrypted libraries.
