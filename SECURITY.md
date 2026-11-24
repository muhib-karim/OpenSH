# Security policy

## Reporting a vulnerability

Please report security vulnerabilities privately through GitHub Security Advisories on this repository ("Security" tab, then "Report a vulnerability"):
https://github.com/muhib-karim/OpenSH/security/advisories/new

Do not open a public GitHub issue for suspected security vulnerabilities. Include the affected commit or release, steps to reproduce, and the potential impact. You should receive an acknowledgement within a few days.

## Supported versions

Only the latest release and the default branch receive security fixes.

## Secrets and scope

- Never commit API keys, tokens, credentials, or private certificates to this repository.
- API keys stay in local environment variables or OS keychain/config outside Git; report command-safety-guard bypasses privately.
