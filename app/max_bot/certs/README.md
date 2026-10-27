# MAX API root CA

Public Russian Trusted Root CA, added only to the MAX client's SSLContext.
System roots, certificate validation and hostname verification remain enabled.

Official source: https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt
Official guidance: https://www.gosuslugi.ru/crt
MAX reference: https://github.com/max-messenger/max-agents-skill/blob/main/references/tls-trust.md

SHA-256 certificate fingerprint (DER):
D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31

Valid until 2032-02-27 21:04:15 UTC. Downloaded over verified HTTPS;
fingerprint, CA basic constraint and self-signature were verified before bundling.
Before replacing the certificate, verify its identity against the current official
MAX/Gosuslugi guidance. Do not substitute an unverified intermediate certificate.
