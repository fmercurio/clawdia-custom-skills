# Privacy and Redaction Notes

This package is generic and must not contain real operational data.

Do not include:

- taxpayer IDs/CNPJ/CPF
- company legal names
- customer names
- invoice values tied to real customers
- emails, phones, addresses
- certificate files or paths
- portal usernames/passwords
- secret-manager entry names
- screenshots from real portals
- internal server URLs or IP addresses

Keep real data in a private local config or secret manager. When sharing improvements to this skill, replace examples with placeholders such as `<CUSTOMER_CNPJ_OR_CPF_DIGITS>`.

Filled config files should live outside the reusable skill package in a private directory (`0700`) with file mode `0600`.

Screenshots, browser traces, logs, filled YAML files, and portal paths are raw evidence. Keep them in a private run directory (`0700`), do not commit them, and do not paste raw paths or values into shared issues, chats, or docs.

Shared reports should use only counts, booleans, configured customer keys, draft states, and redacted labels. Confirm that evidence was captured without exposing the evidence contents.
