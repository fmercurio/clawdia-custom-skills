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
